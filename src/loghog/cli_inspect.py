"""`loghog redact`, `loghog window` and `loghog mappings` — the read-only commands.

`redact` is the important one. A redactor nobody has checked against their own
data is a redactor nobody should trust, and this is the command that lets
somebody paste a real ticket in and see exactly what would survive — without
writing anything anywhere.
"""

from argparse import Namespace
from pathlib import Path

from loghog.cli_common import add_config_option, config_from, fail, render_class_counts
from loghog.errors import LoghogError
from loghog.ingest.mapping import BUILTIN_MAPPINGS, load_mapping
from loghog.ingest.report import SYNTHETIC_BANNER, UNREDACTED_BANNER
from loghog.privacy.redact import Redactor
from loghog.window.store import WindowStore

EXIT_OK = 0


def add_parsers(subparsers) -> None:
    redact = subparsers.add_parser(
        "redact",
        help="show what redaction would do to a piece of text",
        description=(
            "Run the redactor over text from --text or --input and print the result. "
            "Writes nothing. This is how you check the detectors against your own "
            "data before trusting them with a window of it."
        ),
    )
    source = redact.add_mutually_exclusive_group()
    source.add_argument("--text", default=None, help="the text to redact")
    source.add_argument("--input", type=Path, default=None, help="a text file to redact")
    add_config_option(redact)
    redact.set_defaults(handler=run_redact)

    window = subparsers.add_parser("window", help="inspect what has been ingested")
    window_commands = window.add_subparsers(dest="window_command")
    show = window_commands.add_parser("show", help="summarise one window's manifest")
    show.add_argument("--window", required=True, help="the window to summarise")
    add_config_option(show)
    show.set_defaults(handler=run_window_show)
    listing = window_commands.add_parser("list", help="name every window on disk")
    add_config_option(listing)
    listing.set_defaults(handler=run_window_list)
    window.set_defaults(handler=lambda args: fail("usage: loghog window {show,list}"))

    mappings = subparsers.add_parser("mappings", help="inspect the field mappings")
    mapping_commands = mappings.add_subparsers(dest="mappings_command")
    mapping_list = mapping_commands.add_parser("list", help="name every built-in mapping")
    add_config_option(mapping_list)
    mapping_list.set_defaults(handler=run_mappings_list)
    mappings.set_defaults(handler=lambda args: fail("usage: loghog mappings list"))


def run_redact(args: Namespace) -> int:
    try:
        config = config_from(args)
    except LoghogError as exc:
        return fail(str(exc))
    if args.text is None and args.input is None:
        return fail("loghog redact needs --text or --input")
    if args.input is not None:
        if not args.input.is_file():
            return fail(f"no file at {args.input}")
        text = args.input.read_text(encoding="utf-8", errors="replace")
    else:
        text = args.text

    redactor = Redactor(name_allowlist=config.name_allowlist, enabled=config.redact)
    result = redactor.redact(text)
    report = redactor.report()
    print(result)
    print()
    if report.total == 0:
        print("Found nothing to redact.")
        return EXIT_OK
    print(f"Replaced {report.total} value(s), {sum(report.distinct_by_class.values())} distinct:")
    for line in render_class_counts(report.by_class):
        print(line)
    return EXIT_OK


def run_window_show(args: Namespace) -> int:
    try:
        config = config_from(args)
        store = WindowStore(config.records_dir / args.window)
        manifest = store.read_manifest()
    except LoghogError as exc:
        return fail(str(exc))
    counts = manifest.counts
    lines: list[str] = []
    if manifest.synthetic:
        lines.append(SYNTHETIC_BANNER)
    if not manifest.redaction.get("enabled"):
        lines.append(UNREDACTED_BANNER)
    lines += [
        f"Window {manifest.window!r}, created {manifest.created_utc}, "
        f"last written {manifest.updated_utc}",
        f"  {counts.records_written} record(s) written from {len(manifest.sources)} source(s)",
        f"  {counts.rejected} line(s) rejected: {counts.unparsed} unparsed, "
        f"{counts.invalid} invalid",
        f"  {counts.duplicates_dropped} deduplicated",
        f"  redaction: {'on' if manifest.redaction.get('enabled') else 'OFF'}, "
        f"{manifest.redaction.get('total', 0)} replacement(s)",
    ]
    lines += render_class_counts(manifest.redaction.get("by_class", {}))
    lines.append("  sources:")
    for source in manifest.sources:
        lines.append(
            f"    {source.path}  [{source.source_format}]  mapping={source.mapping}  "
            f"sha256={source.sha256[:12]}…"
        )
    print("\n".join(lines))
    return EXIT_OK


def run_window_list(args: Namespace) -> int:
    try:
        config = config_from(args)
    except LoghogError as exc:
        return fail(str(exc))
    if not config.records_dir.is_dir():
        print("No windows yet.")
        return EXIT_OK
    windows = sorted(
        path.name for path in config.records_dir.iterdir() if WindowStore(path).exists
    )
    if not windows:
        print("No windows yet.")
        return EXIT_OK
    for name in windows:
        print(name)
    return EXIT_OK


def run_mappings_list(args: Namespace) -> int:
    try:
        config = config_from(args)
    except LoghogError as exc:
        return fail(str(exc))
    for name in BUILTIN_MAPPINGS:
        path = config.mappings_dir / f"{name}.toml"
        if not path.is_file():
            print(f"{name}  (missing from {config.mappings_dir})")
            continue
        mapping = load_mapping(path)
        needs = " needs --sidecar" if mapping.sidecar is not None else ""
        print(f"{mapping.name}  [{mapping.source_format}]{needs}")
        print(f"    {mapping.description}")
    return EXIT_OK
