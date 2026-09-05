"""The manifest: where a window came from, and what happened on the way in.

A window with no manifest is a pile of JSON somebody has to take on trust. The
manifest is what makes it evidence — which files, at which hashes, read under
which mapping at which hash, how many lines were rejected and for what, and
exactly how much personal data came out of the text.

The counts are checked against each other rather than merely stored. Every line
of a source is a row, a blank or a rejection, and if that arithmetic does not
hold then a line went missing and the report is a lie.
"""

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from loghog import __version__
from loghog.errors import ManifestError

MANIFEST_SCHEMA_VERSION = 2
"""Version 2 adds `expect_output_json` to every source.

A window written by version 1 cannot say whether its outputs were meant to parse
as JSON, and defaulting that to "no" would make stage 03's `format_violation`
permanently quiet on exactly the windows somebody most wanted it for. So a
version-1 manifest is refused and the window is re-ingested, which is one
command over a per-run artefact that was never committed."""

DEDUPE_ALGORITHM = "sha256(lowercased, whitespace-collapsed, redacted input_text)"

_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "loghog_version",
        "window",
        "created_utc",
        "updated_utc",
        "synthetic",
        "sources",
        "counts",
        "redaction",
        "errors_by_type",
        "dedupe_enabled",
        "dedupe_algorithm",
    }
)


@dataclass(frozen=True)
class SourceEntry:
    """One file that was read into this window."""

    path: str
    source_format: str
    mapping: str
    mapping_sha256: str
    sha256: str
    bytes: int
    ingested_utc: str
    redactions: int
    expect_output_json: bool = False

    def __post_init__(self) -> None:
        if Path(self.path).is_absolute():
            raise ManifestError(
                f"source path {self.path!r} is absolute. A manifest is evidence, and "
                "somebody's home directory in it helps nobody."
            )
        for name in ("sha256", "mapping_sha256"):
            digest = getattr(self, name)
            if not isinstance(digest, str) or len(digest) != 64:
                raise ManifestError(f"{name} must be a 64-character sha256, got {digest!r}")
        if not isinstance(self.expect_output_json, bool):
            raise ManifestError(
                f"expect_output_json must be true or false, got {self.expect_output_json!r}"
            )
        for name in ("bytes", "redactions"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ManifestError(f"{name} must be a non-negative integer, got {value!r}")

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "bytes": self.bytes,
            "expect_output_json": self.expect_output_json,
            "ingested_utc": self.ingested_utc,
            "mapping": self.mapping,
            "mapping_sha256": self.mapping_sha256,
            "path": self.path,
            "redactions": self.redactions,
            "sha256": self.sha256,
            "source_format": self.source_format,
        }


_COUNT_NAMES = (
    "lines_read",
    "blank_lines",
    "rows",
    "unparsed",
    "invalid",
    "records_written",
    "duplicates_dropped",
    "truncated",
)


@dataclass(frozen=True)
class IngestCounts:
    """What happened to every line of every source.

    Two buckets for a bad line, not one, because they are two different
    problems with two different fixes. `unparsed` is a line the source format
    could not read at all — broken JSON, a CSV row with too many cells — and
    means the export is damaged. `invalid` is a row that read perfectly and
    could not become a record — a missing timestamp, an answer that never came
    — and usually means the mapping is pointed at the wrong field.

    A thousand of the first is an upstream conversation; a thousand of the
    second is a one-line edit to a TOML file. Collapsing them into "rejected"
    would hide which.
    """

    lines_read: int
    blank_lines: int
    rows: int
    unparsed: int
    invalid: int
    records_written: int
    duplicates_dropped: int
    truncated: int

    def __post_init__(self) -> None:
        for name in _COUNT_NAMES:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ManifestError(f"{name} must be a non-negative integer, got {value!r}")

    @property
    def rejected(self) -> int:
        """Every line that did not become a record, for whichever reason."""
        return self.unparsed + self.invalid

    def to_json_dict(self) -> dict[str, Any]:
        payload = {name: getattr(self, name) for name in _COUNT_NAMES}
        payload["rejected"] = self.rejected
        return dict(sorted(payload.items()))

    def plus(self, other: "IngestCounts") -> "IngestCounts":
        return IngestCounts(**{
            name: getattr(self, name) + getattr(other, name) for name in _COUNT_NAMES
        })


@dataclass(frozen=True)
class Manifest:
    """One window's provenance."""

    window: str
    created_utc: str
    updated_utc: str
    synthetic: bool
    sources: tuple[SourceEntry, ...]
    counts: IngestCounts
    redaction: dict[str, Any]
    errors_by_type: dict[str, int]
    dedupe_enabled: bool

    def __post_init__(self) -> None:
        if not self.sources:
            raise ManifestError("a window manifest names at least one source")
        counts = self.counts
        # Two invariants, and between them every line of every source has
        # exactly one home. If either fails, a line went missing or was counted
        # twice, and the whole report is a guess.
        if counts.lines_read != counts.rows + counts.blank_lines + counts.unparsed:
            raise ManifestError(
                f"the counts do not add up: {counts.lines_read} lines read but "
                f"{counts.rows} rows + {counts.blank_lines} blank + {counts.unparsed} unparsed."
            )
        if counts.rows != counts.records_written + counts.duplicates_dropped + counts.invalid:
            raise ManifestError(
                f"the rows do not add up: {counts.rows} rows but {counts.records_written} "
                f"written + {counts.duplicates_dropped} deduplicated + {counts.invalid} invalid."
            )

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "counts": self.counts.to_json_dict(),
            "created_utc": self.created_utc,
            "dedupe_algorithm": DEDUPE_ALGORITHM,
            "dedupe_enabled": self.dedupe_enabled,
            "errors_by_type": dict(sorted(self.errors_by_type.items())),
            "loghog_version": __version__,
            "redaction": self.redaction,
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "sources": [source.to_json_dict() for source in self.sources],
            "synthetic": self.synthetic,
            "updated_utc": self.updated_utc,
            "window": self.window,
        }

    def merge(
        self,
        *,
        sources: tuple[SourceEntry, ...],
        counts: IngestCounts,
        redaction: dict[str, Any],
        errors_by_type: dict[str, int],
        updated_utc: str,
    ) -> "Manifest":
        """Fold a second run into this window's manifest.

        Raises:
            ManifestError: a source is being ingested twice at the same hash.
                Doing it again would double every count for no new records.
        """
        seen = {(source.path, source.sha256) for source in self.sources}
        for source in sources:
            if (source.path, source.sha256) in seen:
                raise ManifestError(
                    f"{source.path} at this hash has already been ingested into window "
                    f"{self.window!r}. Appending it again would double the counts."
                )
        merged_classes = dict(self.redaction.get("by_class", {}))
        for pii_class, count in redaction.get("by_class", {}).items():
            merged_classes[pii_class] = merged_classes.get(pii_class, 0) + count
        merged_errors = dict(self.errors_by_type)
        for error_type, count in errors_by_type.items():
            merged_errors[error_type] = merged_errors.get(error_type, 0) + count
        return replace(
            self,
            sources=self.sources + sources,
            counts=self.counts.plus(counts),
            redaction={
                # A window is redacted only if EVERY run into it was. Anything
                # else lets one debugging session quietly launder the flag.
                "enabled": bool(self.redaction.get("enabled")) and bool(redaction.get("enabled")),
                "by_class": dict(sorted(merged_classes.items())),
                "total": int(self.redaction.get("total", 0)) + int(redaction.get("total", 0)),
            },
            errors_by_type=merged_errors,
            updated_utc=updated_utc,
        )


def manifest_from_json_dict(payload: object) -> Manifest:
    """Validate a manifest read back from disk.

    Raises:
        ManifestError: not an object, not this schema version, or missing a key.
    """
    if not isinstance(payload, dict):
        raise ManifestError(f"a manifest must be a JSON object, got {type(payload).__name__}")
    version = payload.get("schema_version")
    if version != MANIFEST_SCHEMA_VERSION:
        raise ManifestError(
            f"manifest schema_version is {version!r}; this build reads "
            f"{MANIFEST_SCHEMA_VERSION}"
        )
    missing = sorted(_MANIFEST_KEYS - set(payload))
    if missing:
        raise ManifestError(f"manifest is missing key(s): {', '.join(missing)}")
    try:
        return Manifest(
            window=payload["window"],
            created_utc=payload["created_utc"],
            updated_utc=payload["updated_utc"],
            synthetic=payload["synthetic"],
            sources=tuple(
                SourceEntry(
                    path=entry["path"],
                    source_format=entry["source_format"],
                    mapping=entry["mapping"],
                    mapping_sha256=entry["mapping_sha256"],
                    sha256=entry["sha256"],
                    bytes=entry["bytes"],
                    ingested_utc=entry["ingested_utc"],
                    redactions=entry["redactions"],
                    expect_output_json=entry["expect_output_json"],
                )
                for entry in payload["sources"]
            ),
            counts=_counts_from_json(payload["counts"]),
            redaction=payload["redaction"],
            errors_by_type=payload["errors_by_type"],
            dedupe_enabled=payload["dedupe_enabled"],
        )
    except ManifestError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise ManifestError(f"manifest is not readable: {exc}") from exc


def _counts_from_json(payload: object) -> IngestCounts:
    """`rejected` is derived, so it is ignored on the way back in rather than
    trusted: a manifest whose stored total disagreed with its parts would
    otherwise be readable."""
    if not isinstance(payload, dict):
        raise ManifestError(f"counts must be an object, got {type(payload).__name__}")
    return IngestCounts(**{name: payload[name] for name in _COUNT_NAMES})
