"""`loghog ingest` — the one command that writes a window."""

from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path

from loghog.cli_common import add_config_option, config_from, fail, render_class_counts
from loghog.errors import LoghogError
from loghog.ingest.mapping import SOURCE_FORMATS
from loghog.ingest.report import SYNTHETIC_BANNER, UNREDACTED_BANNER
from loghog.ingest.run import EXIT_NOTHING, ingest
from loghog.window.store import ERRORS_NAME, REPORT_NAME


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "ingest",
        help="read a log file into a window of canonical, redacted records",
        description=(
            "Read one log file under one field mapping, redact every text field, "
            "deduplicate by the hash of the normalised input, and write a window "
            "with a manifest that says where it all came from."
        ),
    )
    parser.add_argument("--input", type=Path, required=True, help="the log file to read")
    parser.add_argument(
        "--format", choices=SOURCE_FORMATS, required=True, help="the source file's format"
    )
    parser.add_argument(
        "--mapping",
        required=True,
        help="a built-in mapping name, or a path to a mapping file",
    )
    parser.add_argument(
        "--window",
        default=None,
        help="the window to write into (default: today's UTC date)",
    )
    parser.add_argument(
        "--out", type=Path, default=None, help="write the window here instead of records/<window>"
    )
    parser.add_argument(
        "--sidecar",
        type=Path,
        default=None,
        help="a file to rejoin text from, for mappings whose log stores a hash",
    )
    parser.add_argument(
        "--append", action="store_true", help="add to a window that already exists"
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="mark the window as built from invented data; banners say so",
    )
    parser.add_argument(
        "--allow-unredacted",
        action="store_true",
        help="required, alongside [privacy] redact = false, to write raw text",
    )
    add_config_option(parser)
    parser.set_defaults(handler=run)


def run(args: Namespace) -> int:
    try:
        config = config_from(args)
        window = args.window or datetime.now(UTC).strftime("%Y-%m-%d")
        outcome = ingest(
            config,
            input_path=args.input,
            source_format=args.format,
            mapping_reference=args.mapping,
            window=window,
            out_dir=args.out,
            sidecar_path=args.sidecar,
            append=args.append,
            synthetic=args.synthetic,
            allow_unredacted=args.allow_unredacted,
        )
    except LoghogError as exc:
        return fail(str(exc))

    if outcome.exit_code == EXIT_NOTHING:
        print(f"Nothing was written: no line of {args.input} became a record.")
        print(f"{len(outcome.failures)} line(s) were rejected. The first few:")
        for failure in outcome.failures[:3]:
            print(f"  line {failure.line_no}: {failure.error_type}: {failure.detail}")
        return outcome.exit_code

    manifest = outcome.manifest
    counts = manifest.counts
    lines: list[str] = []
    if manifest.synthetic:
        lines.append(SYNTHETIC_BANNER)
    if not manifest.redaction.get("enabled"):
        lines.append(UNREDACTED_BANNER)
    lines += [
        f"Window {manifest.window!r} at {outcome.directory}",
        f"  {counts.lines_read} line(s) read: {counts.rows} row(s), "
        f"{counts.blank_lines} blank, {counts.unparsed} unparsed",
        f"  {counts.records_written} record(s) written, "
        f"{counts.duplicates_dropped} deduplicated, {counts.invalid} invalid",
    ]
    if counts.truncated:
        lines.append(f"  {counts.truncated} field(s) truncated at {config.max_text_chars} chars")
    lines.append(f"  redaction: {manifest.redaction.get('total', 0)} replacement(s)")
    lines += render_class_counts(manifest.redaction.get("by_class", {}))
    if outcome.failures:
        lines.append(f"  {len(outcome.failures)} rejected line(s) listed in {ERRORS_NAME}")
    lines.append(f"  the full report is in {REPORT_NAME}")
    print("\n".join(lines))
    return outcome.exit_code
