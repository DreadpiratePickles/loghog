"""Writing a window, and refusing to write one that still carries personal data.

The refusal is the point of this module. `[privacy] redact = true` is a promise,
and a promise kept by a habit somewhere upstream is not a promise — it is a hope
about code somebody might refactor next month. So every record is re-checked at
the moment it is about to become bytes on a disk, against the five structural
classes a regex can be sure about, and a window that fails is not written at
all.

All-or-nothing, deliberately. A half-written window is worse than no window,
because its manifest would describe records that are not there.
"""

import json
import os
from collections.abc import Iterable, Sequence
from pathlib import Path

from loghog.errors import (
    LineFailure,
    ManifestError,
    UnredactedWriteError,
    WindowConflictError,
)
from loghog.privacy.detect import STRUCTURAL_CLASSES, find_spans
from loghog.record import Record, record_from_json_dict
from loghog.window.manifest import Manifest, manifest_from_json_dict

RECORDS_NAME = "records.jsonl"
MANIFEST_NAME = "manifest.json"
ERRORS_NAME = "errors.jsonl"
REPORT_NAME = "ingest.md"

DIRECTORY_MODE = 0o700
FILE_MODE = 0o600

_GUARDED_FIELDS = ("input_text", "output_text", "feedback", "error")


class WindowStore:
    """One window directory: its records, its manifest, its errors, its report."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    @property
    def records_path(self) -> Path:
        return self.directory / RECORDS_NAME

    @property
    def manifest_path(self) -> Path:
        return self.directory / MANIFEST_NAME

    @property
    def errors_path(self) -> Path:
        return self.directory / ERRORS_NAME

    @property
    def report_path(self) -> Path:
        return self.directory / REPORT_NAME

    @property
    def exists(self) -> bool:
        return self.records_path.is_file() or self.manifest_path.is_file()

    def check_writable(self, *, append: bool) -> None:
        """Raise unless this window may be written in the requested mode.

        Raises:
            WindowConflictError: a fresh run into a window that exists, or an
                append into one that does not. Both are almost always a typo in
                `--window`, and both would be destructive to guess at.
        """
        if append and not self.exists:
            raise WindowConflictError(
                f"window {self.directory.name!r} does not exist, so there is nothing to "
                "append to. Drop --append to create it."
            )
        if not append and self.exists:
            raise WindowConflictError(
                f"window {self.directory.name!r} already exists at {self.directory}. "
                "Pass --append to add to it, or choose another --window."
            )

    # --- records ------------------------------------------------------------

    def append_records(
        self,
        records: Sequence[Record],
        *,
        redaction_enabled: bool,
        allow_unredacted: bool = False,
    ) -> None:
        """Write records, after checking every one of them.

        Raises:
            UnredactedWriteError: redaction is off and was not explicitly
                overridden, or a record still carries structural personal data
                even though redaction was on — which means the redactor failed,
                and no command-line flag lets that through.
        """
        if not redaction_enabled and not allow_unredacted:
            raise UnredactedWriteError(
                "[privacy] redact is false. Writing production text unredacted needs "
                "--allow-unredacted on the command line as well: two switches, in two "
                "places, one of them typed by a person at the moment of the decision."
            )
        if redaction_enabled:
            for record in records:
                self._guard(record)
        self._ensure_directory()
        with self.records_path.open("a", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record.to_json_dict(), ensure_ascii=False) + "\n")
        os.chmod(self.records_path, FILE_MODE)

    @staticmethod
    def _guard(record: Record) -> None:
        for field_name in _GUARDED_FIELDS:
            value = getattr(record, field_name)
            if not value:
                continue
            leaked = sorted(
                {
                    span.pii_class
                    for span in find_spans(value)
                    if span.pii_class in STRUCTURAL_CLASSES
                }
            )
            if leaked:
                # The class, never the value: this message goes into logs and
                # tickets, and quoting what leaked would leak it again.
                raise UnredactedWriteError(
                    f"record {record.record_id!r} still carries {', '.join(leaked)} in "
                    f"{field_name} after redaction. Nothing was written."
                )

    def existing_fingerprints(self) -> set[str]:
        """Every input fingerprint already in this window.

        A corrupt line stops the read rather than being skipped: a window whose
        records cannot all be parsed is a window whose deduplication would be
        quietly incomplete.
        """
        if not self.records_path.is_file():
            return set()
        fingerprints = set()
        with self.records_path.open("r", encoding="utf-8") as handle:
            for raw in handle:
                text = raw.strip()
                if not text:
                    continue
                record = record_from_json_dict(json.loads(text))
                fingerprints.add(record.input_fingerprint())
        return fingerprints

    # --- manifest -----------------------------------------------------------

    def write_manifest(self, manifest: Manifest) -> None:
        """Write the manifest atomically: a neighbour, then a rename."""
        self._ensure_directory()
        payload = json.dumps(manifest.to_json_dict(), indent=2, ensure_ascii=False) + "\n"
        temporary = self.manifest_path.with_suffix(".json.tmp")
        temporary.write_text(payload, encoding="utf-8")
        os.chmod(temporary, FILE_MODE)
        temporary.replace(self.manifest_path)

    def read_manifest(self) -> Manifest:
        """Read this window's manifest.

        Raises:
            ManifestError: absent or unreadable.
        """
        if not self.manifest_path.is_file():
            raise ManifestError(f"no manifest at {self.manifest_path}")
        try:
            payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ManifestError(f"{self.manifest_path} is not readable JSON: {exc}") from exc
        return manifest_from_json_dict(payload)

    # --- the other two files ------------------------------------------------

    def append_errors(self, failures: Iterable[LineFailure]) -> None:
        """Append the per-line error report.

        Created even when empty, so that its absence means "no run has written
        here" rather than "no line failed".
        """
        self._ensure_directory()
        with self.errors_path.open("a", encoding="utf-8") as handle:
            for failure in failures:
                handle.write(json.dumps(failure.to_json_dict(), ensure_ascii=False) + "\n")
        os.chmod(self.errors_path, FILE_MODE)

    def write_report(self, text: str) -> None:
        """Write the human-readable ingest report, replacing any earlier one."""
        self._ensure_directory()
        self.report_path.write_text(text, encoding="utf-8")
        os.chmod(self.report_path, FILE_MODE)

    def _ensure_directory(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True, mode=DIRECTORY_MODE)
        os.chmod(self.directory, DIRECTORY_MODE)
