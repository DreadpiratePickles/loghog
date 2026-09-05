"""Stage 01 and stage 02, composed: read, map, redact, deduplicate, write.

The order is the design. Redaction happens between building a record and
deciding whether the window already has it, which means two things at once: no
personal data reaches a file, and deduplication compares the text an eval case
would actually contain rather than the text a customer happened to type their
name into.

Exit codes are part of the contract, because a partial success that returns 0 is
the failure this tool exists to prevent — nobody reads the report of a command
that succeeded.

    0  every non-blank line became a record
    1  records were written, and some lines were rejected
    2  nothing was written; the reason is in the report
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from loghog.config_file import LoghogConfig
from loghog.errors import (
    LineFailure,
    LoghogError,
    ManifestError,
    MappingError,
    RecordError,
    SourceFormatError,
    UnredactedWriteError,
)
from loghog.ingest.mapping import FieldMapping, resolve_mapping
from loghog.ingest.normalise import build_record
from loghog.ingest.readers import ReadLine, read_source, source_sha256
from loghog.ingest.report import render_report
from loghog.ingest.sidecar import load_sidecar
from loghog.privacy.redact import Redactor
from loghog.record import TIMESTAMP_FORMAT, Record
from loghog.window.dedupe import Deduper
from loghog.window.manifest import IngestCounts, Manifest, SourceEntry
from loghog.window.store import WindowStore

EXIT_OK = 0
EXIT_PARTIAL = 1
EXIT_NOTHING = 2

_REDACTED_FIELDS = ("input_text", "output_text", "feedback", "error")


@dataclass(frozen=True)
class IngestOutcome:
    """What one `loghog ingest` did."""

    window: str
    directory: Path
    manifest: Manifest | None
    failures: tuple[LineFailure, ...]
    exit_code: int


def ingest(
    config: LoghogConfig,
    *,
    input_path: Path,
    source_format: str,
    mapping_reference: str,
    window: str,
    out_dir: Path | None = None,
    sidecar_path: Path | None = None,
    append: bool = False,
    synthetic: bool = False,
    allow_unredacted: bool = False,
    now: datetime | None = None,
) -> IngestOutcome:
    """Ingest one file into one window.

    Raises:
        LoghogError: anything that stops the run before a record is written —
            a mapping that contradicts the format, a window that already
            exists, redaction turned off without the override. A problem with
            an individual *line* is never a raise; it is a counted failure.
    """
    mapping = resolve_mapping(mapping_reference, mappings_dir=config.mappings_dir)
    _check_format(mapping, source_format)
    if mapping.sidecar is not None and sidecar_path is None:
        raise MappingError(
            f"mapping {mapping.name!r} declares a [sidecar]: its log stores "
            f"{mapping.sidecar.target} only as a hash. Pass --sidecar <file>."
        )
    if not config.redact and not allow_unredacted:
        raise UnredactedWriteError(
            "[privacy] redact is false. Writing production text unredacted needs "
            "--allow-unredacted as well, typed by a person at the moment of the decision."
        )

    directory = Path(out_dir) if out_dir is not None else config.records_dir / window
    store = WindowStore(directory)
    store.check_writable(append=append)

    if not Path(input_path).is_file():
        # Checked here, and not left to the reader, because the source is
        # hashed for the manifest before the first line is read — and an
        # OSError escaping this function would be the one failure in the tool
        # that reached an operator as a traceback.
        raise SourceFormatError(f"no source file at {input_path}")
    source_path = _relative(input_path, config)
    source_digest = source_sha256(input_path)
    existing = store.read_manifest() if append else None
    if existing is not None:
        # Checked before the file is read rather than after. Re-ingesting a file
        # a window already holds would double every count for no new records,
        # and finding that out at the end wastes the whole pass.
        for entry in existing.sources:
            if (entry.path, entry.sha256) == (source_path, source_digest):
                raise ManifestError(
                    f"{source_path} at this hash has already been ingested into window "
                    f"{window!r} (on {entry.ingested_utc}). Nothing was read."
                )

    sidecar = load_sidecar(sidecar_path, mapping.sidecar) if sidecar_path is not None else None
    redactor = Redactor(name_allowlist=config.name_allowlist, enabled=config.redact)
    deduper = Deduper(
        enabled=config.dedupe,
        seen=store.existing_fingerprints() if append else (),
    )

    records: list[Record] = []
    failures: list[LineFailure] = []
    lines_read = blanks = rows = truncated = unparsed = invalid = 0

    for line in read_source(input_path, source_format):
        lines_read += 1
        if line.blank:
            blanks += 1
            continue
        if line.failure is not None:
            # The source format could not read the line at all, so it never
            # became a row. It is counted as unparsed and nowhere else.
            unparsed += 1
            failures.append(line.failure)
            continue
        rows += 1
        outcome = _record_for(line, mapping, config, sidecar, redactor)
        if isinstance(outcome, LineFailure):
            # A row that read perfectly and could not become a record.
            invalid += 1
            failures.append(outcome)
            continue
        record, was_truncated = outcome
        truncated += was_truncated
        if deduper.is_new(record):
            records.append(record)

    stamp = _stamp(now)
    counts = IngestCounts(
        lines_read=lines_read,
        blank_lines=blanks,
        rows=rows,
        unparsed=unparsed,
        invalid=invalid,
        records_written=len(records),
        duplicates_dropped=deduper.dropped,
        truncated=truncated,
    )
    if not records:
        # Nothing is written, not even an empty window: a window with no records
        # and a manifest describing them is a thing later stages would read.
        return IngestOutcome(
            window=window,
            directory=directory,
            manifest=None,
            failures=tuple(failures),
            exit_code=EXIT_NOTHING,
        )

    report = redactor.report().to_json_dict()
    source = SourceEntry(
        path=source_path,
        source_format=source_format,
        mapping=mapping.name,
        mapping_sha256=mapping.sha256,
        sha256=source_digest,
        bytes=Path(input_path).stat().st_size,
        ingested_utc=stamp,
        redactions=report["total"],
        expect_output_json=mapping.expect_output_json,
    )
    redaction = {
        "enabled": report["enabled"],
        "by_class": report["by_class"],
        "total": report["total"],
    }
    errors_by_type = _by_type(failures)
    if existing is not None:
        manifest = existing.merge(
            sources=(source,),
            counts=counts,
            redaction=redaction,
            errors_by_type=errors_by_type,
            updated_utc=stamp,
        )
    else:
        manifest = Manifest(
            window=window,
            created_utc=stamp,
            updated_utc=stamp,
            synthetic=synthetic,
            sources=(source,),
            counts=counts,
            redaction=redaction,
            errors_by_type=errors_by_type,
            dedupe_enabled=config.dedupe,
        )

    store.append_records(
        records, redaction_enabled=config.redact, allow_unredacted=allow_unredacted
    )
    store.append_errors(failures)
    store.write_manifest(manifest)
    store.write_report(render_report(manifest, tuple(failures)))
    return IngestOutcome(
        window=window,
        directory=directory,
        manifest=manifest,
        failures=tuple(failures),
        exit_code=EXIT_PARTIAL if failures else EXIT_OK,
    )


def _record_for(
    line: ReadLine,
    mapping: FieldMapping,
    config: LoghogConfig,
    sidecar: dict[str, str] | None,
    redactor: Redactor,
) -> tuple[Record, int] | LineFailure:
    try:
        built = build_record(
            line.payload, mapping, max_text_chars=config.max_text_chars, sidecar=sidecar
        )
        return _redacted(built.record, redactor), len(built.truncated_fields)
    except RecordError as exc:
        return LineFailure.from_exception(line.line_no, exc)
    except LoghogError:
        # A configuration problem discovered mid-file — an unknown extractor, a
        # sidecar that was never supplied. It stops the run rather than failing
        # every remaining line for the same reason.
        raise


def _redacted(record: Record, redactor: Redactor) -> Record:
    """Every text field of a record, through the redactor, before anything is written."""
    from dataclasses import replace

    return replace(
        record,
        **{name: redactor.redact(getattr(record, name)) for name in _REDACTED_FIELDS},
    )


def _check_format(mapping: FieldMapping, source_format: str) -> None:
    if mapping.source_format != source_format:
        raise MappingError(
            f"--format {source_format} contradicts mapping {mapping.name!r}, which declares "
            f"source_format = {mapping.source_format!r}. One of the two is wrong, and "
            "guessing which would read the file the wrong way."
        )


def _by_type(failures: list[LineFailure]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for failure in failures:
        counts[failure.error_type] = counts.get(failure.error_type, 0) + 1
    return counts


def _relative(path: Path, config: LoghogConfig) -> str:
    """The source path as recorded in the manifest — relative wherever it can be.

    A manifest is evidence, and somebody's home directory in it helps nobody.
    A file outside the repository is recorded by name alone for the same reason.
    """
    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(config.root))
    except ValueError:
        return resolved.name


def _stamp(now: datetime | None) -> str:
    moment = now or datetime.now(UTC)
    return moment.astimezone(UTC).replace(microsecond=0).strftime(TIMESTAMP_FORMAT)

