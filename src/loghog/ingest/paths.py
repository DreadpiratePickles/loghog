"""Reaching into a nested payload by a dotted path.

`generation.usage.input_tokens`, `messages.-1.content`. A segment that reads as
an integer indexes a list; anything else is a key. Dictionary keys win over list
indices when both could apply, because `{"0": ...}` is a perfectly well-formed
payload and reading it as an index would be a silent mis-read.

Absent is a first-class answer. A path that resolves to nothing returns the
`MISSING` sentinel rather than `None`, because a log line whose `feedback` is
literally `null` and one that has no `feedback` key at all are different facts,
and this is the layer where that distinction has to survive.
"""

from typing import Any

from loghog.errors import MappingError

WHOLE_PAYLOAD = "."
"""The path that means "the row itself" — for a mapping whose extractor wants
the whole object rather than a field of it."""


class _Missing:
    """The absence of a value, distinct from a value that is null."""

    _instance: "_Missing | None" = None

    def __new__(cls) -> "_Missing":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "MISSING"


MISSING = _Missing()


def extract_path(payload: object, path: str) -> Any:
    """Follow `path` into `payload`, or return `MISSING`.

    Raises:
        MappingError: the path itself is malformed. That is a mistake in a file
            a human wrote, not a log line that happens to be short of a field,
            and it stops the run rather than failing every line in turn.
    """
    if not isinstance(path, str) or not path.strip():
        raise MappingError(f"a field path must be a non-empty string, got {path!r}")
    if path == WHOLE_PAYLOAD:
        return payload
    segments = path.split(".")
    if any(not segment for segment in segments):
        raise MappingError(f"path {path!r} has an empty segment")
    current: Any = payload
    for segment in segments:
        current = _step(current, segment)
        if current is MISSING:
            return MISSING
    return current


def _step(current: Any, segment: str) -> Any:
    if isinstance(current, dict):
        return current.get(segment, MISSING)
    if isinstance(current, list):
        try:
            index = int(segment)
        except ValueError:
            return MISSING
        if -len(current) <= index < len(current):
            return current[index]
        return MISSING
    return MISSING
