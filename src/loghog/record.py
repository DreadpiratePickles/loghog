"""The canonical record: the one shape every source format collapses to.

Everything downstream — scoring, clustering, selection, labelling, emitting —
reads this and nothing else. That is the whole point of a canonical form: the
knowledge that a particular vendor calls the answer `completion.text` lives in
one mapping file, and no stage after ingestion has to know it.

The invariants are strict on purpose. A loose record means every later stage
re-checks the same things, and a log line that lied gets to lie all the way into
a golden case.
"""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from loghog.errors import (
    FieldTypeError,
    MissingFieldError,
    RecordError,
    TimestampError,
)

TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
"""UTC, second resolution, an explicit `Z`, no offset.

By the time a `Record` exists the instant has already been resolved to UTC by
the coercion layer. Allowing a second representation here would mean two things
that must be kept in step, and they would not be.
"""

RECORD_KEYS = frozenset(
    {
        "record_id",
        "ts_utc",
        "input_text",
        "output_text",
        "prompt_version",
        "arm",
        "latency_ms",
        "input_tokens",
        "output_tokens",
        "cost_micro_usd",
        "error",
        "feedback",
        "judge_verdicts",
    }
)

COUNT_FIELDS = ("latency_ms", "input_tokens", "output_tokens", "cost_micro_usd")
OPTIONAL_TEXT_FIELDS = ("prompt_version", "arm", "feedback", "error")

REDACTED_TEXT_FIELDS = ("input_text", "output_text", "feedback", "error")
"""The named fields that hold text the customer wrote, in one place.

Both the redactor (`ingest.run`) and the write guard (`window.store`) traverse
exactly this list, by importing it rather than by each declaring its own copy.
Two tuples that must agree are two tuples that can disagree, and the first time
they did, a fifth text field reached disk unredacted.

The fifth field is `judge_verdicts[].criterion`, which cannot appear here
because it lives inside a tuple rather than on the record. Both callers handle
it explicitly, and `tests/test_window_store.py` asserts the guard covers it.

`record_id`, `prompt_version` and `arm` are deliberately absent. They are
identifiers and labels, not prose: redacting an id would break dedupe, the
manifest and every cross-reference a later stage makes.
"""

_WHITESPACE = re.compile(r"\s+")


def _require_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise FieldTypeError(
            f"{field_name} must be a string, got {type(value).__name__}"
        )
    if not value.strip():
        raise MissingFieldError(f"{field_name} is empty")
    return value


def _check_optional_text(value: object, *, field_name: str) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise FieldTypeError(f"{field_name} must be a string or absent, got {type(value).__name__}")
    if not value.strip():
        raise MissingFieldError(
            f"{field_name} is present but empty. Absent and blank are different facts; "
            "use null for absent."
        )


def _check_count(value: object, *, field_name: str) -> None:
    if value is None:
        return
    # `bool` is an `int` in Python, and `True` would silently become 1 — a
    # latency of one millisecond, or a cost of one micro-USD.
    if isinstance(value, bool) or not isinstance(value, int):
        raise FieldTypeError(
            f"{field_name} must be an integer or absent, got {type(value).__name__}. "
            "Money is integer micro-USD and a token count is a count; a float here is a "
            "unit error waiting to be summed a million times."
        )
    if value < 0:
        raise FieldTypeError(f"{field_name} cannot be negative, got {value}")


@dataclass(frozen=True)
class JudgeVerdict:
    """One criterion, and whether the output met it.

    `passed` is strictly a `bool`. `1` and `"true"` both mean "passed" to a
    careless reader and neither is a verdict: a judge either said yes or it did
    not, and anything else is a parse that failed quietly.
    """

    criterion: str
    passed: bool

    def __post_init__(self) -> None:
        _require_text(self.criterion, field_name="criterion")
        if not isinstance(self.passed, bool):
            raise FieldTypeError(
                f"a verdict's passed must be a bool, got {type(self.passed).__name__}"
            )

    def to_json_dict(self) -> dict[str, Any]:
        return {"criterion": self.criterion, "passed": self.passed}


@dataclass(frozen=True)
class Record:
    """One request somebody made of a model in production. Frozen: it happened."""

    record_id: str
    ts_utc: str
    input_text: str
    output_text: str | None = None
    prompt_version: str | None = None
    arm: str | None = None
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_micro_usd: int | None = None
    error: str | None = None
    feedback: str | None = None
    judge_verdicts: tuple[JudgeVerdict, ...] = field(default=())

    def __post_init__(self) -> None:
        record_id = _require_text(self.record_id, field_name="record_id")
        if "\n" in record_id or "\r" in record_id:
            raise FieldTypeError(
                f"record_id {record_id!r} contains a newline. Records are one JSON object "
                "per line; an id with a newline in it cannot survive the file it is written to."
            )
        _require_text(self.input_text, field_name="input_text")
        self._check_timestamp()
        for name in OPTIONAL_TEXT_FIELDS:
            _check_optional_text(getattr(self, name), field_name=name)
        if self.output_text is not None:
            _require_text(self.output_text, field_name="output_text")
        for name in COUNT_FIELDS:
            _check_count(getattr(self, name), field_name=name)
        self._check_outcome()
        self._check_verdicts()

    def _check_timestamp(self) -> None:
        if not isinstance(self.ts_utc, str):
            raise TimestampError(f"ts_utc must be a string, got {type(self.ts_utc).__name__}")
        try:
            datetime.strptime(self.ts_utc, TIMESTAMP_FORMAT)
        except ValueError as exc:
            raise TimestampError(
                f"ts_utc {self.ts_utc!r} is not {TIMESTAMP_FORMAT} ({exc}). "
                "Offsets are resolved during coercion; by the time a record exists the "
                "instant is already UTC."
            ) from exc

    def _check_outcome(self) -> None:
        has_output = self.output_text is not None
        has_error = self.error is not None
        if has_output and has_error:
            raise RecordError(
                f"record {self.record_id!r} carries both an output and an error "
                f"({self.error!r}). A call either produced an answer or it did not."
            )
        if not has_output and not has_error:
            raise RecordError(
                f"record {self.record_id!r} carries neither an output nor an error. "
                "A failed read must not become a successful no-op."
            )

    def _check_verdicts(self) -> None:
        if not isinstance(self.judge_verdicts, tuple):
            raise FieldTypeError(
                f"judge_verdicts must be a tuple, got {type(self.judge_verdicts).__name__}"
            )
        seen: set[str] = set()
        for verdict in self.judge_verdicts:
            if not isinstance(verdict, JudgeVerdict):
                raise FieldTypeError(
                    f"judge_verdicts must hold JudgeVerdict, got {type(verdict).__name__}"
                )
            if verdict.criterion in seen:
                raise RecordError(
                    f"record {self.record_id!r} answers criterion {verdict.criterion!r} twice"
                )
            seen.add(verdict.criterion)

    @property
    def failed(self) -> bool:
        """Whether this request failed. The complement of having an output."""
        return self.error is not None

    def input_fingerprint(self) -> str:
        """The dedupe key: a hash of the normalised input."""
        return input_fingerprint(self.input_text)

    def to_json_dict(self) -> dict[str, Any]:
        """The record as one JSON object, keys sorted.

        Sorted so that a diff of two windows is about the records rather than
        about the order somebody happened to construct the dict in.
        """
        return {
            "arm": self.arm,
            "cost_micro_usd": self.cost_micro_usd,
            "error": self.error,
            "feedback": self.feedback,
            "input_text": self.input_text,
            "input_tokens": self.input_tokens,
            "judge_verdicts": [verdict.to_json_dict() for verdict in self.judge_verdicts],
            "latency_ms": self.latency_ms,
            "output_text": self.output_text,
            "output_tokens": self.output_tokens,
            "prompt_version": self.prompt_version,
            "record_id": self.record_id,
            "ts_utc": self.ts_utc,
        }


def record_from_json_dict(payload: object) -> Record:
    """Validate one record read back from a window.

    Raises:
        RecordError: the payload is not a record this version understands.
            Missing and unknown keys are both refused: a window written by a
            later schema is not a window this code can be trusted to read.
    """
    if not isinstance(payload, dict):
        raise RecordError(f"a record must be a JSON object, got {type(payload).__name__}")
    missing = sorted(RECORD_KEYS - set(payload))
    unknown = sorted(set(payload) - RECORD_KEYS)
    if missing or unknown:
        raise RecordError(f"record has missing key(s) {missing} and unknown key(s) {unknown}")
    fields = dict(payload)
    fields["judge_verdicts"] = _verdicts_from_json(fields["judge_verdicts"])
    try:
        return Record(**fields)
    except RecordError:
        raise
    except (TypeError, ValueError) as exc:
        raise RecordError(f"record {payload.get('record_id')!r} is invalid: {exc}") from exc


def _verdicts_from_json(value: object) -> tuple[JudgeVerdict, ...]:
    if not isinstance(value, list):
        raise FieldTypeError(f"judge_verdicts must be a list, got {type(value).__name__}")
    verdicts = []
    for entry in value:
        if not isinstance(entry, dict):
            raise FieldTypeError(f"a verdict must be an object, got {type(entry).__name__}")
        unknown = sorted(set(entry) - {"criterion", "passed"})
        if unknown:
            raise FieldTypeError(f"a verdict has unknown key(s) {unknown}")
        try:
            verdicts.append(
                JudgeVerdict(criterion=entry.get("criterion"), passed=entry.get("passed"))
            )
        except RecordError:
            raise
        except (TypeError, ValueError) as exc:
            raise FieldTypeError(f"a verdict is invalid: {exc}") from exc
    return tuple(verdicts)


def normalise_for_dedupe(text: str) -> str:
    """Lowercase, collapse runs of whitespace, strip the ends.

    Deliberately conservative. This is *exact* deduplication after cosmetic
    noise is removed — the same message pasted twice with a different indent is
    one message. Near-duplicate detection is a different question with a
    different answer, and it belongs to stage 04, not here.
    """
    if not isinstance(text, str):
        raise FieldTypeError(f"text must be a string, got {type(text).__name__}")
    return _WHITESPACE.sub(" ", text).strip().lower()


def input_fingerprint(text: str) -> str:
    """SHA-256 of the normalised input, as hex."""
    return hashlib.sha256(normalise_for_dedupe(text).encode("utf-8")).hexdigest()
