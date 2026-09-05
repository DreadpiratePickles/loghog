"""Reading and writing the artefacts the stages after ingestion leave in a window.

Separate from `store` because they are separate concerns with separate rules.
`store` is all-or-nothing and append-only: a window's records are evidence and
nothing rewrites them. These are *derived*, and derived artefacts are replaced
rather than appended — re-scoring a window with a different set of weights must
produce a file describing that window, not two files stapled together.

They inherit one thing from `store`: the permissions. A score's evidence names
patterns and counts rather than text, but the candidate files these feed hold
the redacted case itself, and a mode nobody thought about is how that stops
being true.
"""

import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from loghog.errors import ScoreError, SelectionError
from loghog.window.store import FILE_MODE, WindowStore


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write one JSON document atomically, at the window's file mode."""
    _ensure_parent(path)
    text = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.chmod(temporary, FILE_MODE)
    temporary.replace(path)


def write_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    """Replace a JSONL file with `rows`, one object per line."""
    _ensure_parent(path)
    lines = [json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    os.chmod(path, FILE_MODE)


def write_text(path: Path, text: str) -> None:
    """Replace a human-readable report."""
    _ensure_parent(path)
    path.write_text(text, encoding="utf-8")
    os.chmod(path, FILE_MODE)


def read_jsonl(path: Path, *, what: str) -> list[dict[str, Any]]:
    """Every object in a JSONL file.

    Raises:
        ScoreError: the file is absent or a line is not a JSON object. Both are
            refused rather than skipped: half a scores file is a ranking over a
            window nobody can name.
    """
    if not path.is_file():
        raise ScoreError(f"no {what} at {path}")
    rows = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = raw.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ScoreError(f"{path} line {number} is not readable JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ScoreError(f"{path} line {number} is not a JSON object")
        rows.append(payload)
    return rows


def read_scores(store: WindowStore) -> dict[str, int]:
    """Record id -> score, for the stages that only need the ranking.

    Raises:
        ScoreError: the window has not been scored, or a line is malformed.
    """
    if not store.scores_path.is_file():
        raise ScoreError(
            f"window {store.directory.name!r} has no scores. Run `loghog score --window "
            f"{store.directory.name}` first."
        )
    scores: dict[str, int] = {}
    for payload in read_jsonl(store.scores_path, what="scores file"):
        record_id, score = payload.get("record_id"), payload.get("score")
        if not isinstance(record_id, str) or isinstance(score, bool) or not isinstance(score, int):
            raise ScoreError(f"{store.scores_path} holds a row that is not a score: {payload!r}")
        scores[record_id] = score
    return scores


def read_signals(store: WindowStore) -> dict[str, tuple[str, ...]]:
    """Record id -> the names of the signals it fired, in the order they were written."""
    signals: dict[str, tuple[str, ...]] = {}
    for payload in read_jsonl(store.scores_path, what="scores file"):
        entries = payload.get("signals")
        if not isinstance(entries, list):
            raise ScoreError(f"{store.scores_path} holds a row with no signals list")
        signals[payload["record_id"]] = tuple(entry["name"] for entry in entries)
    return signals


def read_clusters(store: WindowStore) -> dict[str, Any]:
    """The clusters document.

    Raises:
        SelectionError: the window has not been clustered. Named for the stage
            that needs it, with the command that produces it.
    """
    if not store.clusters_path.is_file():
        raise SelectionError(
            f"window {store.directory.name!r} has not been clustered. Run "
            f"`loghog cluster --window {store.directory.name}` first."
        )
    try:
        payload = json.loads(store.clusters_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SelectionError(f"{store.clusters_path} is not readable JSON: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("clusters"), list):
        raise SelectionError(f"{store.clusters_path} is not a clusters document")
    return payload


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
