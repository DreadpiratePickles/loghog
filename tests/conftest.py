"""Shared test helpers.

`write_config` copies the *committed* `loghog.toml` into a temporary directory
rather than inventing a configuration in code. The paths, the privacy switch and
the limits a test exercises should be the ones a reader of the repository would
run; a fixture that drifted from the real file would be testing nothing anybody
uses. Every substitution is asserted to have matched, so a test cannot silently
keep testing a default after the committed file's wording moves.
"""

import json
import shutil
from collections.abc import Sequence
from pathlib import Path

from loghog.config_file import LoghogConfig, load_config
from loghog.record import Record

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMITTED_CONFIG = REPO_ROOT / "loghog.toml"
MAPPINGS_DIR = REPO_ROOT / "mappings"
SAMPLES_DIR = REPO_ROOT / "samples"


def write_config(directory: Path, substitutions: Sequence[tuple[str, str]] = ()) -> Path:
    """Copy the committed `loghog.toml` into `directory`, applying substitutions."""
    text = COMMITTED_CONFIG.read_text(encoding="utf-8")
    for old, new in substitutions:
        if old not in text:
            raise AssertionError(f"substitution target not present in loghog.toml: {old!r}")
        text = text.replace(old, new)
    path = directory / "loghog.toml"
    path.write_text(text, encoding="utf-8")
    # The committed mappings travel with the committed configuration. `[paths]
    # mappings_dir` resolves against the config file, so a temporary root
    # without them would make every `--mapping <name>` in the suite resolve to
    # nothing — and the suite would then be testing a mapping directory that
    # does not exist rather than the three the repository ships.
    if not (directory / "mappings").exists():
        shutil.copytree(MAPPINGS_DIR, directory / "mappings")
    return path


def load_test_config(
    directory: Path, substitutions: Sequence[tuple[str, str]] = ()
) -> LoghogConfig:
    """The committed configuration, rooted in a throwaway directory."""
    return load_config(write_config(directory, substitutions))


def make_record(**overrides) -> Record:
    """One valid successful record, with any field overridden."""
    fields = {
        "record_id": "req-001",
        "ts_utc": "2026-09-05T10:00:00Z",
        "input_text": "My lamp flickers above half brightness.",
        "output_text": "Customer reports a flickering lamp.",
    }
    fields.update(overrides)
    return Record(**fields)


def write_jsonl(path: Path, rows: Sequence[object]) -> Path:
    """Write `rows` as one JSON object per line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(row, ensure_ascii=False) if not isinstance(row, str) else row
             for row in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_lines(path: Path, text: str) -> Path:
    """Write raw text verbatim — for the malformed-input tests."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def chat_row(index: int, *, user: str, assistant: str | None = "A reply.") -> dict:
    """One OpenAI-style chat completion log line."""
    messages = [
        {"role": "system", "content": "You are a support assistant."},
        {"role": "user", "content": user},
    ]
    if assistant is not None:
        messages.append({"role": "assistant", "content": assistant})
    return {
        "id": f"chat-{index:03d}",
        "created": 1_788_000_000 + index,
        "model": "some-model",
        "messages": messages,
        "usage": {"prompt_tokens": 100 + index, "completion_tokens": 20 + index},
        "latency_ms": 300 + index,
    }
