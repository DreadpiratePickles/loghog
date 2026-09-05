"""Rendering a labelled candidate as project 1's golden-case YAML.

The contract this module is written against is not "valid YAML". It is
**`regression_detect.goldens.load_goldens` must accept the file**, because a
case project 1 cannot parse is not a case — it is a text file with opinions in
it. The suite therefore loads what this module writes with that exact function
rather than with a schema restated here, which is the only version of the check
that cannot drift.

Two rendering problems are worth naming, because both work on the demo data and
fail on the first real record.

**A production input is arbitrary text.** It contains colons, quotes, leading
spaces, emoji, blank lines, redaction tokens and — in one memorable case — three
backticks. So every scalar is rendered as a literal block, that rendering is
**parsed back and compared to the original**, and anything that does not survive
the round trip falls back to a double-quoted scalar. Guessing which texts are
safe is how a run silently mangles the one case that mattered.

**The id must be snake_case.** Project 1's ids match
`^[a-z][a-z0-9]*(_[a-z0-9]+)*$` and are stable for ever, because its baselines
key on them. A record id like `chat-001` and a window like `2026-09-04` both
fail that, so the id is built by slugging both and joining them:
`loghog_2026_09_04_chat_001`. The window is in there so that emitting two
windows into one goldens file collides only when it genuinely is the same record
twice — and `promote` refuses that loudly rather than appending a duplicate id
project 1 would reject on load.
"""

import json
import re
from dataclasses import dataclass

import yaml

from loghog.errors import EmitError

LOGHOG_TAG = "loghog"
"""The first tag on every case this tool writes, so `grep -c "- loghog"` answers
"how much of this eval set was proposed by a machine and signed off by a
human"."""

CASE_ID_PREFIX = "loghog"
INDENT = 2

SYNTHETIC_BANNER = (
    "# SYNTHETIC — produced by `loghog label --dry-run`. No model was called: the\n"
    "# criteria below are a fixed placeholder list, identical for every case, and they\n"
    "# are not a reading of these records. Do not promote them."
)

_NON_SLUG = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class EmitCase:
    """One shortlisted record, its drafted criteria, and where both came from."""

    case_id: str
    record_id: str
    window: str
    input_text: str
    output_text: str | None
    stratum: str
    score: int
    signals: tuple[str, ...]
    criteria: tuple[str, ...]
    notes: str
    model_id: str
    dry_run: bool

    @property
    def tags(self) -> tuple[str, ...]:
        """`loghog` first, then every signal that fired, in registry order."""
        return (LOGHOG_TAG, *self.signals)


def slug(value: str) -> str:
    """Lowercase, underscore-separated, and safe as a golden-case id fragment.

    Raises:
        EmitError: nothing survives the slugging. An id built from an empty
            fragment would collide with every other empty one.
    """
    slugged = _NON_SLUG.sub("_", str(value).lower()).strip("_")
    if not slugged:
        raise EmitError(f"{value!r} contains nothing that can become a case id")
    return slugged


def case_id_for(*, window: str, record_id: str) -> str:
    """The golden-case id for one record, stable across runs."""
    return f"{CASE_ID_PREFIX}_{slug(window)}_{slug(record_id)}"


def case_notes(case: EmitCase) -> str:
    """The provenance a reviewer needs, and a golden case has room for.

    Every case says where it came from, what made it interesting, who drafted
    its criteria, and — in its own words — that nobody has read it yet.
    """
    signals = ", ".join(case.signals) or "none; this is ordinary traffic"
    lines = [
        f"MINED BY loghog, NOT REVIEWED. Window {case.window}, record {case.record_id}, "
        f"stratum {case.stratum}, score {case.score}.",
        f"Signals: {signals}.",
        f"Criteria drafted by {case.model_id} and not yet read by a human.",
    ]
    if case.notes:
        lines.append(f"Drafter's note: {case.notes}")
    if case.dry_run:
        lines.insert(
            0,
            "SYNTHETIC: these criteria are placeholders from a dry run. No model read "
            "this record.",
        )
    return "\n".join(lines)


def _quoted(value: str) -> str:
    """A double-quoted YAML scalar. JSON's escaping is a subset of YAML's."""
    return json.dumps(value, ensure_ascii=False)


def _block_attempt(key: str, value: str, style: str) -> list[str] | None:
    """One literal-block rendering of `key: value`, verified by parsing it back.

    Returns `None` when the round trip does not reproduce the value exactly.
    Rendered and probed at indent zero; the caller re-indents the whole thing,
    which preserves the relative structure the parse depended on.
    """
    body = value[:-1] if style == "|" and value.endswith("\n") else value
    if style == "|" and not value.endswith("\n"):
        return None
    lines = [f"{key}: {style}"] + [
        f"{' ' * INDENT}{line}" if line else "" for line in body.split("\n")
    ]
    try:
        loaded = yaml.safe_load("\n".join(lines))
    except yaml.YAMLError:
        return None
    if not isinstance(loaded, dict) or loaded.get(key) != value:
        return None
    return lines


def render_mapping_scalar(key: str, value: str, indent: int) -> list[str]:
    """`key: value` as a literal block where that survives a round trip, quoted otherwise."""
    for style in ("|-", "|"):
        lines = _block_attempt(key, value, style)
        if lines is not None:
            return [f"{' ' * indent}{line}" if line else "" for line in lines]
    return [f"{' ' * indent}{key}: {_quoted(value)}"]


def render_sequence_item(value: str, indent: int) -> str:
    """`- value` as a plain scalar where that round-trips, quoted otherwise.

    This is where project 1's documented YAML gotcha lives: a criterion
    containing a colon and a space is a *mapping* unless it is quoted, and the
    file then fails to parse rather than failing to mean what it says.
    """
    try:
        loaded = yaml.safe_load(f"- {value}")
    except yaml.YAMLError:
        loaded = None
    if isinstance(loaded, list) and loaded == [value]:
        return f"{' ' * indent}- {value}"
    return f"{' ' * indent}- {_quoted(value)}"


def render_case(case: EmitCase) -> list[str]:
    """One golden case, in project 1's shape.

    Raises:
        EmitError: the case has no criteria. A case with none is not one project
            1 will load, and inventing one here would put a sentence nobody
            wrote into an acceptance test.
    """
    if not case.criteria:
        raise EmitError(
            f"case {case.case_id!r} has no drafted criteria, so it cannot be emitted. "
            "A case with invented criteria is worse than a case that is missing."
        )
    lines = [f"- id: {case.case_id}", f"{' ' * INDENT}tags: [{', '.join(case.tags)}]"]
    lines.extend(render_mapping_scalar("input", case.input_text, INDENT))
    lines.append(f"{' ' * INDENT}criteria:")
    lines.extend(render_sequence_item(text, INDENT + INDENT) for text in case.criteria)
    lines.extend(render_mapping_scalar("notes", case_notes(case), INDENT))
    return lines


def render_cases_yaml(cases: list[EmitCase], *, window: str, dry_run: bool) -> str:
    """The whole candidates file, verified against what it was built from.

    Raises:
        EmitError: there are no cases, one of them has no criteria, or the
            rendered file does not parse back to exactly the cases it was given.
            Verified rather than trusted: this file becomes somebody's
            definition of correct, and an input mangled on the way out would be
            a criterion about a record that never existed.
    """
    if not cases:
        raise EmitError(
            f"no candidate in window {window!r} has drafted criteria, so there is no "
            "dataset to write. An empty goldens file is one project 1 refuses to load."
        )
    header = [
        f"# Evaluation candidates mined by loghog from window {window}.",
        "#",
        "# DRAFTS. Every case below was selected by a machine from production traffic",
        "# and its criteria were drafted by a model. None of them has been read by a",
        "# human. Promote the ones you accept, one id at a time:",
        "#",
        "#   loghog promote --file <this file> --ids <a,b> \\",
        "#       --into <goldens.yaml> --reviewed-by <your name>",
        "#",
        "# The schema is project 1's golden-case schema, so this file loads with",
        "# regression_detect.goldens.load_goldens exactly as it stands.",
        "#",
        "# The inputs below have been through loghog's redactor: [EMAIL_1] and its",
        "# relatives stand where personal data was. That is the only reason this file",
        "# can leave the machine it was built on.",
    ]
    if dry_run:
        header = [SYNTHETIC_BANNER, *header]

    body: list[str] = []
    for case in cases:
        if body:
            body.append("")
        body.extend(render_case(case))

    text = "\n".join([*header, "", *body]) + "\n"
    _verify(text, cases)
    return text


def _verify(text: str, cases: list[EmitCase]) -> None:
    try:
        loaded = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise EmitError(f"the rendered candidates file is not valid YAML: {exc}") from exc
    if not isinstance(loaded, list) or len(loaded) != len(cases):
        raise EmitError("the rendered candidates file did not parse back to one case per candidate")
    for entry, case in zip(loaded, cases, strict=True):
        if entry.get("id") != case.case_id:
            raise EmitError(f"case id {entry.get('id')!r} is not {case.case_id!r}")
        if entry.get("input") != case.input_text:
            raise EmitError(
                f"case {case.case_id!r}: the input did not survive rendering. A criterion "
                "about a mangled input is a criterion about nothing."
            )
        if tuple(entry.get("criteria", ())) != case.criteria:
            raise EmitError(f"case {case.case_id!r}: the criteria did not survive rendering")


__all__ = [
    "CASE_ID_PREFIX",
    "INDENT",
    "LOGHOG_TAG",
    "SYNTHETIC_BANNER",
    "EmitCase",
    "case_id_for",
    "case_notes",
    "render_case",
    "render_cases_yaml",
    "render_mapping_scalar",
    "render_sequence_item",
    "slug",
]
