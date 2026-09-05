"""`loghog promote`: the one place a drafted case becomes a golden case.

Everything upstream of this file is a proposal. A golden case is an acceptance
criterion — the thing every later change is measured against — so adopting one
written by a model, from customer text, that nobody read would let the system
quietly define what "correct" means. That is the failure this whole half of the
tool is arranged to prevent, and this module is where the prevention lives:
nothing is promoted that a named human listed by id on a command line.

Three choices carry the module.

**The target is appended to as text, not rewritten.** Loading a goldens file and
dumping it back through PyYAML produces a valid file with every comment deleted
— and in a goldens file the comments are half the content: the category
checklist, the worked examples, the note explaining why a case exists. So the
accepted cases are rendered and appended, and the result is **re-loaded with
`load_goldens` before it is kept**. If the append produced something project 1
cannot read, nothing is written.

**A duplicate id is refused, loudly.** Project 1 rejects a dataset with a
repeated id, so appending one would break the file for every later run, and it
would break it at load time rather than here.

**A dry-run placeholder is refused too.** `loghog label --dry-run` writes four
fixed criteria, identical for every case, and the file it produces says "do not
promote them" in its first three lines. A tool that prints that and then does it
anyway has taught its operator that its warnings are decorative, so the sentence
is enforced rather than printed: any case still carrying the `[SYNTHETIC]`
marker in a criterion or in its notes is refused by id.

**The reviewer's name goes in the notes.** A case whose provenance says "mined"
and nothing else cannot answer "who decided this was correct?" — which is the
question that matters the first time the case fails somebody's build.
"""

import os
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from regression_detect.goldens import GoldenCase, GoldenDatasetError, load_goldens

from loghog.emit.cases import INDENT, render_mapping_scalar, render_sequence_item
from loghog.errors import PromoteError
from loghog.label.draft import SYNTHETIC_MARKER

GOLDENS_FILE_MODE = 0o644
REVIEWED_PREFIX = "REVIEWED AND PROMOTED"


@dataclass(frozen=True)
class PromoteResult:
    """What one promotion did."""

    promoted: tuple[str, ...]
    into: Path
    total_cases: int
    reviewed_by: str


def parse_ids(raw: str) -> tuple[str, ...]:
    """Split a `--ids` value, preserving order and refusing repeats.

    Raises:
        PromoteError: the value names no ids, or names one twice. A repeat is
            refused rather than deduplicated: somebody who typed an id twice
            probably meant a different second id.
    """
    ids = [part.strip() for part in str(raw).split(",") if part.strip()]
    if not ids:
        raise PromoteError(
            "--ids named no case. Promotion is per case on purpose: 'all of them' is "
            "not a review."
        )
    seen: set[str] = set()
    for case_id in ids:
        if case_id in seen:
            raise PromoteError(f"--ids names {case_id!r} twice")
        seen.add(case_id)
    return tuple(ids)


def _load(path: Path, *, what: str) -> list[GoldenCase]:
    try:
        return load_goldens(path)
    except GoldenDatasetError as exc:
        raise PromoteError(f"could not read the {what} at {path}: {exc}") from exc


def render_promoted_case(case: GoldenCase, *, reviewed_by: str, ts_utc: str) -> list[str]:
    """One accepted case, with the reviewer recorded in its notes."""
    stamped = f"{REVIEWED_PREFIX} by {reviewed_by} on {ts_utc}."
    notes = f"{case.notes}\n{stamped}" if case.notes else stamped
    lines = [f"- id: {case.id}", f"{' ' * INDENT}tags: [{', '.join(case.tags)}]"]
    lines.extend(render_mapping_scalar("input", case.input, INDENT))
    lines.append(f"{' ' * INDENT}criteria:")
    lines.extend(render_sequence_item(text, INDENT + INDENT) for text in case.criteria)
    lines.extend(render_mapping_scalar("notes", notes, INDENT))
    return lines


def promote(
    *,
    candidates_path: Path,
    case_ids: Sequence[str],
    into: Path,
    reviewed_by: str | None,
    ts_utc: str,
) -> PromoteResult:
    """Append the named cases to a goldens file, under a reviewer's name.

    Raises:
        PromoteError: the reviewer is unnamed, no id was given, either file
            cannot be loaded, an id is not in the candidates file, an id is
            already in the target, or the appended result is not a dataset
            project 1 can load. Nothing is written when any of them fires.
    """
    if not isinstance(reviewed_by, str) or not reviewed_by.strip():
        raise PromoteError(
            "--reviewed-by is required. A golden case is an acceptance criterion, and "
            "the file has to be able to say who decided it was one."
        )
    reviewer = reviewed_by.strip()
    wanted = tuple(case_ids)
    if not wanted:
        raise PromoteError(
            "no case was named. Promotion is per case on purpose: 'all of them' is not "
            "a review."
        )

    candidates_path, into = Path(candidates_path), Path(into)
    available = {case.id: case for case in _load(candidates_path, what="candidates file")}
    missing = [case_id for case_id in wanted if case_id not in available]
    if missing:
        raise PromoteError(
            f"{candidates_path} has no case with the id(s) {', '.join(missing)}. "
            f"It holds: {', '.join(sorted(available)) or 'nothing'}."
        )

    placeholders = [case_id for case_id in wanted if _is_placeholder(available[case_id])]
    if placeholders:
        raise PromoteError(
            f"{', '.join(placeholders)} still carr{'ies' if len(placeholders) == 1 else 'y'} "
            f"the {SYNTHETIC_MARKER} marker, which means the criteria came from "
            "`loghog label --dry-run` and are a fixed placeholder list identical for every "
            "case. Nothing read the record. Re-run `loghog label` without --dry-run, or "
            "write the criteria by hand and remove the marker from the notes."
        )

    existing = _load(into, what="goldens file") if into.exists() else []
    already = [case_id for case_id in wanted if case_id in {case.id for case in existing}]
    if already:
        raise PromoteError(
            f"{into} already holds the case(s) {', '.join(already)}. A golden id is "
            "stable for ever — baselines key on it — so promoting one twice is refused "
            "rather than appended."
        )

    blocks = [
        "\n".join(render_promoted_case(available[case_id], reviewed_by=reviewer, ts_utc=ts_utc))
        for case_id in wanted
    ]
    previous = into.read_text(encoding="utf-8") if into.exists() else ""
    preamble = (
        previous.rstrip("\n")
        if previous.strip()
        else _new_file_header(reviewer, ts_utc).rstrip("\n")
    )
    text = "\n\n".join([preamble, *blocks]) + "\n"

    _verify(text, expected=len(existing) + len(wanted), into=into)
    _write_atomic(into, text)
    return PromoteResult(
        promoted=wanted,
        into=into,
        total_cases=len(existing) + len(wanted),
        reviewed_by=reviewer,
    )


def _is_placeholder(case: GoldenCase) -> bool:
    """Whether this case's criteria came from a dry run rather than from a model.

    The notes are checked as well as the criteria. Somebody who rewrote the four
    placeholder criteria by hand has done most of a review — but the notes still
    say nothing read this record, and that sentence is either true or it should
    not be in the file.
    """
    if any(SYNTHETIC_MARKER in criterion for criterion in case.criteria):
        return True
    return SYNTHETIC_MARKER in (case.notes or "") or "dry run" in (case.notes or "").lower()


def _new_file_header(reviewer: str, ts_utc: str) -> str:
    return (
        f"# Golden cases. Started by `loghog promote` on {ts_utc}, first reviewed by "
        f"{reviewer}.\n"
        "# Every case here was mined from production traffic, redacted before it was\n"
        "# written, and adopted by a person who read it."
    )


def _verify(text: str, *, expected: int, into: Path) -> None:
    """Load the would-be file before replacing the real one.

    Raises:
        PromoteError: the result is not a dataset project 1 can load, or does
            not hold the expected number of cases.
    """
    with tempfile.TemporaryDirectory() as directory:
        probe = Path(directory) / "probe.yaml"
        probe.write_text(text, encoding="utf-8")
        try:
            cases = load_goldens(probe)
        except GoldenDatasetError as exc:
            raise PromoteError(
                f"the promotion would have made {into} unreadable by project 1's loader "
                f"({exc}). Nothing was written."
            ) from exc
    if len(cases) != expected:
        raise PromoteError(
            f"the promotion would have produced {len(cases)} case(s) where {expected} "
            f"were expected. Nothing was written to {into}."
        )


def _write_atomic(path: Path, text: str) -> None:
    """Write, fsync, chmod, rename. A goldens file is committed state.

    Not `window.artifacts.write_text`, deliberately. That helper writes at mode
    0600 under a 0700 directory because everything it writes is a window
    artefact holding production text. A goldens file is the opposite: it is
    reviewed, committed and read by a team, so it is written 0644 and into
    whatever directory the operator named.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, GOLDENS_FILE_MODE)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


__all__ = [
    "REVIEWED_PREFIX",
    "PromoteResult",
    "parse_ids",
    "promote",
    "render_promoted_case",
]
