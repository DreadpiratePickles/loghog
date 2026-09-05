"""The human-readable ingest report.

Two rules, and they are the same rule twice.

**It quotes nothing.** Not a record, not a rejected line, not a redaction. A
report is the artefact people paste into a ticket, attach to a mail and leave in
a shared drive, and a report that quotes the data is a second copy of the data
in exactly the places nobody was thinking about privacy.

**It says what it is on its first line.** A window built from the sample log
says `SYNTHETIC` before anything else; a window written with redaction off says
`UNREDACTED`. Both are facts a reader needs before the numbers, not after them.
"""

from loghog.errors import LineFailure
from loghog.window.manifest import DEDUPE_ALGORITHM, Manifest

SYNTHETIC_BANNER = (
    "SYNTHETIC — built from an invented sample log, not from production traffic. "
    "No customer wrote any of the text this window holds."
)
UNREDACTED_BANNER = (
    "UNREDACTED — [privacy] redact was false for at least one run into this window. "
    "The records hold production text as it came, and nothing here has been checked."
)


def render_report(manifest: Manifest, failures: tuple[LineFailure, ...]) -> str:
    """Render `ingest.md` for one window."""
    lines: list[str] = []
    if manifest.synthetic:
        lines += [SYNTHETIC_BANNER, ""]
    if not manifest.redaction.get("enabled"):
        lines += [UNREDACTED_BANNER, ""]
    counts = manifest.counts
    lines += [
        f"# Window `{manifest.window}`",
        "",
        f"Created {manifest.created_utc}, last written {manifest.updated_utc}.",
        "",
        "## Sources",
        "",
        "| File | Format | Mapping | SHA-256 | Bytes |",
        "|---|---|---|---|---:|",
    ]
    for source in manifest.sources:
        lines.append(
            f"| `{source.path}` | {source.source_format} | `{source.mapping}` "
            f"| `{source.sha256[:12]}…` | {source.bytes} |"
        )
    lines += [
        "",
        "## What happened to every line",
        "",
        "| | Count |",
        "|---|---:|",
        f"| Lines read | {counts.lines_read} |",
        f"| Blank | {counts.blank_lines} |",
        f"| Unparsed — the format could not read them | {counts.unparsed} |",
        f"| Rows parsed | {counts.rows} |",
        f"| Invalid — read, but not a record | {counts.invalid} |",
        f"| Dropped as duplicates | {counts.duplicates_dropped} |",
        f"| Truncated fields | {counts.truncated} |",
        f"| **Records written** | **{counts.records_written}** |",
        "",
        "Every line is a row, a blank or an unparsed line, and every row is a "
        "record, a duplicate or an invalid row. Both sums are checked before the "
        "manifest is written: a window whose arithmetic does not close is refused "
        "rather than reported.",
        "",
        "The two kinds of bad line are separated because they have different "
        "fixes. Unparsed means the export is damaged and that is a conversation "
        "upstream. Invalid usually means the mapping is pointed at the wrong "
        "field, and that is a one-line edit.",
        "",
        "## Rejections, by type",
        "",
    ]
    if manifest.errors_by_type:
        lines += ["| Error | Count |", "|---|---:|"]
        lines += [
            f"| `{error_type}` | {count} |"
            for error_type, count in sorted(manifest.errors_by_type.items())
        ]
        lines += [
            "",
            f"Every one of the {len(failures)} rejected line(s) is in `errors.jsonl` "
            "with its line number, its type and a reason. None of them quotes the line.",
        ]
    else:
        lines.append("None. Every non-blank line became a record.")
    lines += ["", "## Redaction", ""]
    if manifest.redaction.get("enabled"):
        by_class = manifest.redaction.get("by_class", {})
        if by_class:
            lines += ["| Class | Replacements |", "|---|---:|"]
            lines += [f"| `{name}` | {count} |" for name, count in sorted(by_class.items())]
            lines += [
                "",
                f"{manifest.redaction.get('total', 0)} value(s) replaced by stable tokens. "
                "The same value has the same token everywhere in this window, and the "
                "map from token to value was never written down.",
            ]
        else:
            lines.append("On, and it found nothing to replace.")
    else:
        lines.append("**Off.** See the banner at the top of this file.")
    lines += [
        "",
        "## Deduplication",
        "",
        f"{'On' if manifest.dedupe_enabled else 'Off'} — `{DEDUPE_ALGORITHM}`.",
        "",
    ]
    return "\n".join(lines) + "\n"
