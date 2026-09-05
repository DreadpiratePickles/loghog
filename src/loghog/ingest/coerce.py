"""Turning whatever the log said into the type the canonical record insists on.

CSV hands every cell over as a string; JSON hands over whatever the producer
felt like on the day. This is the boundary where that stops being true.

It is strict in one specific way: a value that cannot be resolved *without
guessing* is a typed error naming the field, never a default. A blank CSV cell
is an absent number, not a zero — reading it as zero would put a thousand free
calls in a cost total. A naive timestamp is an error, not an assumption — a log
written in Berlin and read in London is off by an hour for the rest of its life,
and nothing downstream would ever notice.
"""

from datetime import UTC, datetime
from typing import Any

from loghog.errors import FieldTypeError, MissingFieldError, TimestampError
from loghog.record import TIMESTAMP_FORMAT, JudgeVerdict

TRUNCATION_MARKER = " …[TRUNCATED]"
"""Appended to text that was cut. Visible in the record itself, because a later
stage judging a truncated output should be able to see that it is judging one."""

EPOCH_MILLISECOND_THRESHOLD = 100_000_000_000
"""Above this, an epoch is milliseconds. 1e11 seconds is the year 5138, and 1e11
milliseconds is 1973 — there is no plausible log in the gap."""

_TRUE_WORDS = frozenset({"true", "yes", "y", "1", "t"})
_FALSE_WORDS = frozenset({"false", "no", "n", "0", "f"})

_NAIVE_FORMATS = ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S")


def truncate(text: str, max_chars: int) -> tuple[str, bool]:
    """Cut `text` to `max_chars`, appending a marker when it was cut."""
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars] + TRUNCATION_MARKER, True


def coerce_text(value: Any, *, field_name: str, allow_number: bool = False) -> str:
    """A string. Numbers are refused unless the field is an identifier.

    `input_text = 42` is a mapping pointed at the wrong field, not an input. But
    plenty of logs number their rows, and `12345` is a perfectly good record id.
    """
    if value is None:
        raise MissingFieldError(f"{field_name} is null")
    if isinstance(value, str):
        return value
    if allow_number and isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    raise FieldTypeError(f"{field_name} must be text, got {type(value).__name__}")


def coerce_int(value: Any, *, field_name: str) -> int:
    """A non-negative whole number, from an int, a whole float or a numeric string."""
    if value is None:
        raise MissingFieldError(f"{field_name} is null")
    if isinstance(value, bool):
        raise FieldTypeError(f"{field_name} must be a number, got a bool")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return _whole(value, field_name=field_name)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            # A blank cell is an absent value. Reading it as zero would be the
            # tool inventing a measurement nobody took.
            raise MissingFieldError(f"{field_name} is blank")
        try:
            return int(text)
        except ValueError:
            pass
        try:
            return _whole(float(text), field_name=field_name)
        except ValueError as exc:
            raise FieldTypeError(f"{field_name} is not a number: {text!r}") from exc
    raise FieldTypeError(f"{field_name} must be a number, got {type(value).__name__}")


def _whole(value: float, *, field_name: str) -> int:
    if value != int(value):
        # Rounding here would be this layer quietly deciding what half a
        # millisecond is worth. It is not its decision to make.
        raise FieldTypeError(
            f"{field_name} is {value}, which is not whole. Round it in the producer, "
            "where somebody knows which way it should go."
        )
    return int(value)


def coerce_bool(value: Any, *, field_name: str) -> bool:
    """A strict bool, from a bool, 0/1, or one of the usual words."""
    if value is None:
        raise MissingFieldError(f"{field_name} is null")
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value in (0, 1):
            return bool(value)
        raise FieldTypeError(f"{field_name} must be true or false, got {value}")
    if isinstance(value, str):
        word = value.strip().lower()
        if word in _TRUE_WORDS:
            return True
        if word in _FALSE_WORDS:
            return False
        raise FieldTypeError(f"{field_name} must be true or false, got {value!r}")
    raise FieldTypeError(f"{field_name} must be true or false, got {type(value).__name__}")


def coerce_timestamp(value: Any, *, field_name: str, naive_is_utc: bool = False) -> str:
    """Resolve `value` to an unambiguous UTC instant in the canonical format.

    Accepts ISO 8601 with an offset or a `Z`, epoch seconds, and epoch
    milliseconds. Sub-second precision is dropped rather than rounded: a record
    is filed by the second and a rounded instant could move it across a day
    boundary.

    Raises:
        TimestampError: unparseable, or naive while `naive_is_utc` is false.
    """
    if value is None:
        raise MissingFieldError(f"{field_name} is null")
    if isinstance(value, bool):
        raise TimestampError(f"{field_name} must be a timestamp, got a bool")
    moment = _parse_moment(value, field_name=field_name, naive_is_utc=naive_is_utc)
    return moment.astimezone(UTC).replace(microsecond=0).strftime(TIMESTAMP_FORMAT)


def _parse_moment(value: Any, *, field_name: str, naive_is_utc: bool) -> datetime:
    if isinstance(value, int | float):
        return _from_epoch(value, field_name=field_name)
    if not isinstance(value, str):
        raise TimestampError(f"{field_name} must be a timestamp, got {type(value).__name__}")
    text = value.strip()
    if not text:
        raise MissingFieldError(f"{field_name} is blank")
    if text.lstrip("-").isdigit():
        return _from_epoch(int(text), field_name=field_name)
    parsed = _parse_iso(text)
    if parsed is None:
        raise TimestampError(
            f"{field_name} {text!r} is not a timestamp this tool can resolve. "
            "ISO 8601 with an offset, an epoch in seconds or milliseconds."
        )
    if parsed.tzinfo is None:
        if not naive_is_utc:
            raise TimestampError(
                f"{field_name} {text!r} carries no timezone. Set naive_is_utc = true in the "
                "mapping's [timestamp] section if the producer writes UTC — but check first: "
                "a log written in one timezone and read in another is silently wrong forever."
            )
        return parsed.replace(tzinfo=UTC)
    return parsed


def _parse_iso(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    for pattern in _NAIVE_FORMATS:
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    return None


def _from_epoch(value: float, *, field_name: str) -> datetime:
    if value < 0:
        raise TimestampError(f"{field_name} is a negative epoch ({value})")
    seconds = value / 1000 if value >= EPOCH_MILLISECOND_THRESHOLD else value
    try:
        return datetime.fromtimestamp(seconds, UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise TimestampError(f"{field_name} {value!r} is not a usable epoch: {exc}") from exc


def coerce_verdicts(
    value: Any, *, field_name: str, criterion_key: str, passed_key: str
) -> tuple[JudgeVerdict, ...]:
    """Judge verdicts, from either shape logs use.

    A list of objects (`[{"criterion": ..., "passed": ...}]`) or one object
    keyed by criterion (`{"is short": true}`). Both are common and neither is
    ambiguous, so both are read rather than one being declared correct.
    """
    if value is None:
        raise MissingFieldError(f"{field_name} is null")
    if isinstance(value, dict):
        return tuple(
            JudgeVerdict(
                criterion=coerce_text(criterion, field_name=f"{field_name}.criterion"),
                passed=coerce_bool(passed, field_name=f"{field_name}[{criterion}]"),
            )
            for criterion, passed in value.items()
        )
    if not isinstance(value, list):
        raise FieldTypeError(
            f"{field_name} must be a list or an object, got {type(value).__name__}"
        )
    verdicts = []
    for position, entry in enumerate(value):
        if not isinstance(entry, dict):
            raise FieldTypeError(
                f"{field_name}[{position}] must be an object, got {type(entry).__name__}"
            )
        if criterion_key not in entry:
            raise MissingFieldError(f"{field_name}[{position}] has no {criterion_key!r}")
        if passed_key not in entry:
            raise MissingFieldError(f"{field_name}[{position}] has no {passed_key!r}")
        verdicts.append(
            JudgeVerdict(
                criterion=coerce_text(
                    entry[criterion_key], field_name=f"{field_name}[{position}].{criterion_key}"
                ),
                passed=coerce_bool(
                    entry[passed_key], field_name=f"{field_name}[{position}].{passed_key}"
                ),
            )
        )
    return tuple(verdicts)
