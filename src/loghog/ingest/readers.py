"""Reading a source file line by line, and never losing one silently.

Every line of the file ends up in exactly one of three buckets — a row, a blank,
or a failure — and the three counts add up to the number of lines. That
arithmetic is the property the per-line error report rests on: "we ingested
58,102 of 60,000 lines" is only a useful sentence if the missing 1,898 are
enumerated somewhere.

A failure never quotes the line. The error report is a file people paste into
tickets and attach to mails, and a broken JSON line quoted in full is the
customer's text in a place nobody was thinking about privacy.
"""

import csv
import hashlib
import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loghog.errors import LineFailure, LineParseError, SourceFormatError

SOURCE_FORMATS: tuple[str, ...] = ("jsonl", "csv")

_HASH_CHUNK_BYTES = 1 << 20


@dataclass(frozen=True)
class ReadLine:
    """One line of the source, in exactly one of three states."""

    line_no: int
    payload: Mapping[str, Any] | None = None
    failure: LineFailure | None = None
    blank: bool = False


def source_sha256(path: Path) -> str:
    """SHA-256 of the file's bytes, for the window manifest.

    The manifest records where a window came from, and a path is not an answer:
    files move and get regenerated. The hash is what makes "this window came
    from that file" checkable a year later.
    """
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def read_source(path: Path, source_format: str) -> Iterator[ReadLine]:
    """Yield one `ReadLine` per line of `path`.

    Raises:
        SourceFormatError: the format is unsupported, the file is missing, or
            the file's own structure (a CSV header) is unusable. Anything
            wrong with an individual *line* is a `LineFailure`, not a raise.
    """
    if source_format not in SOURCE_FORMATS:
        raise SourceFormatError(
            f"unsupported format {source_format!r}; supported: {', '.join(SOURCE_FORMATS)}"
        )
    path = Path(path)
    if not path.is_file():
        raise SourceFormatError(f"no source file at {path}")
    if source_format == "jsonl":
        yield from _read_jsonl(path)
    else:
        yield from _read_csv(path)


def _read_jsonl(path: Path) -> Iterator[ReadLine]:
    # utf-8-sig, because an editor or an export pipeline on Windows will put a
    # byte-order mark on the first line and `json.loads` will refuse it — one
    # unreadable line at the top of every file, for a reason nobody enjoys
    # discovering twice.
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line_no, raw in enumerate(handle, start=1):
            text = raw.strip()
            if not text:
                yield ReadLine(line_no=line_no, blank=True)
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                yield ReadLine(
                    line_no=line_no,
                    failure=LineFailure(
                        line_no=line_no,
                        error_type="LineParseError",
                        # `exc.msg` and not `exc`: the full message includes the
                        # offending fragment of the line.
                        detail=f"not valid JSON ({exc.msg} at column {exc.colno})",
                    ),
                )
                continue
            if not isinstance(payload, dict):
                yield ReadLine(
                    line_no=line_no,
                    failure=LineFailure.from_exception(
                        line_no,
                        LineParseError(
                            f"a log line must be a JSON object, got {type(payload).__name__}"
                        ),
                    ),
                )
                continue
            yield ReadLine(line_no=line_no, payload=payload)


def _read_csv(path: Path) -> Iterator[ReadLine]:
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            raise SourceFormatError(
                f"{path} is empty; a CSV source needs a header row naming its columns"
            ) from None
        _check_header(header, path=path)
        width = len(header)
        for row in reader:
            line_no = reader.line_num - 1
            if not row:
                yield ReadLine(line_no=line_no, blank=True)
                continue
            if len(row) > width:
                yield ReadLine(
                    line_no=line_no,
                    failure=LineFailure(
                        line_no=line_no,
                        error_type="LineParseError",
                        detail=f"{len(row)} cells for {width} columns",
                    ),
                )
                continue
            # Short rows are filled with None rather than "", so that a missing
            # cell reads as absent and an empty cell reads as empty.
            padded = list(row) + [None] * (width - len(row))
            yield ReadLine(line_no=line_no, payload=dict(zip(header, padded, strict=True)))


def _check_header(header: list[str], *, path: Path) -> None:
    cleaned = [column.strip() for column in header]
    if any(not column for column in cleaned):
        raise SourceFormatError(f"{path} has a blank header cell; every column needs a name")
    duplicates = sorted({column for column in cleaned if cleaned.count(column) > 1})
    if duplicates:
        # `csv.DictReader` silently keeps the last of a duplicate pair, which
        # would drop a column without ever saying so.
        raise SourceFormatError(
            f"{path} has duplicate header column(s): {', '.join(duplicates)}"
        )
