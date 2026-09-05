"""Every way this package can fail, as a type a caller can branch on.

Five categories, because there are exactly five things a caller does about a
failure:

- `ConfigError` — the run cannot start. Fix the file and try again.
- `RecordError` — *this line* is not a usable record. Count it, report it, keep
  going. Sixty thousand of these is a mapping problem, not sixty thousand
  problems, which is why the report groups by type.
- `SourceError` — the file itself is not readable as the format it claims.
- `RedactionError` — a refusal to write. Never recoverable by retrying.
- `WindowError` — what is already on disk contradicts what is about to be
  written.

The distinction between `RecordError` and `SourceError` is load bearing: a bad
line is counted and the run continues, a bad file stops it. Collapsing the two
would make a typo in a mapping look like sixty thousand bad log lines.
"""

from dataclasses import dataclass
from typing import Any


class LoghogError(Exception):
    """Base class for every failure raised by this package."""


# --- configuration ----------------------------------------------------------


class ConfigError(LoghogError):
    """The run cannot start: configuration is missing, unreadable or invalid."""


class ConfigFileError(ConfigError):
    """`loghog.toml` is absent, unparseable, or says something impossible."""


class MappingError(ConfigError):
    """A field mapping is absent, unparseable, or names something unknown.

    A mapping is configuration, not data: a mapping that names a field the
    canonical record does not have is a mistake in a file a human wrote, and it
    stops the run rather than failing sixty thousand lines one at a time.
    """


# --- records ----------------------------------------------------------------


class RecordError(LoghogError):
    """One source row is not a usable canonical record."""


class MissingFieldError(RecordError):
    """A field the canonical record requires is absent or empty."""


class FieldTypeError(RecordError):
    """A field is present but is not the type — or the sign — the record needs."""


class TimestampError(RecordError):
    """A timestamp cannot be resolved to an unambiguous UTC instant."""


# --- sources ----------------------------------------------------------------


class SourceError(LoghogError):
    """The source file cannot be read as the format it was declared to be."""


class SourceFormatError(SourceError):
    """An unsupported format, an unreadable file, or a CSV with no header."""


class LineParseError(SourceError):
    """One line is not readable as the format the file was declared to be.

    File-level rather than record-level in its ancestry, because it is a fact
    about the bytes rather than about the fields — but it is carried as a
    `LineFailure` and the run continues, exactly like a bad record.
    """


@dataclass(frozen=True)
class LineFailure:
    """One rejected line, kept so that it can be counted and reported.

    This is not an exception. A rejected line is data — the per-line error
    report is a file somebody reads — and the run carries these forward rather
    than raising on the first one.
    """

    line_no: int
    error_type: str
    detail: str

    def __post_init__(self) -> None:
        if not isinstance(self.line_no, int) or isinstance(self.line_no, bool):
            raise SourceError(f"line_no must be an int, got {type(self.line_no).__name__}")
        if self.line_no < 1:
            raise SourceError(f"line numbers start at 1, got {self.line_no}")
        if not isinstance(self.error_type, str) or not self.error_type.strip():
            raise SourceError("a rejected line must name the type of failure")
        if not isinstance(self.detail, str):
            raise SourceError(f"detail must be a str, got {type(self.detail).__name__}")

    @classmethod
    def from_exception(cls, line_no: int, exc: Exception) -> "LineFailure":
        """Build a failure from the exception that rejected the line."""
        return cls(line_no=line_no, error_type=type(exc).__name__, detail=str(exc))

    def to_json_dict(self) -> dict[str, Any]:
        return {"detail": self.detail, "error_type": self.error_type, "line_no": self.line_no}


# --- privacy ----------------------------------------------------------------


class RedactionError(LoghogError):
    """Redaction was asked to do something it will not do."""


class UnredactedWriteError(RedactionError):
    """A write of text that has not been through the redactor was refused.

    The default is that this cannot happen: `[privacy] redact = true` means
    every text field passes through the redactor before it reaches a file. This
    error is what makes the default a guarantee rather than a habit.
    """


# --- windows ----------------------------------------------------------------


class WindowError(LoghogError):
    """What is on disk contradicts what is about to be written."""


class ManifestError(WindowError):
    """A window's manifest is absent, unparseable, or not this schema version."""


class WindowConflictError(WindowError):
    """The window already exists and the run was not told to append to it."""
