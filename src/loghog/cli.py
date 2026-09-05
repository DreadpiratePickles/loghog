"""The command line.

Four commands, and only one of them writes anything:

    loghog ingest      read a log into a window of redacted canonical records
    loghog redact      show what redaction would do to a piece of text
    loghog window      summarise or list what has been ingested
    loghog mappings    name the built-in field mappings

Exit codes are the contract, and there are four of them:

    0  it worked
    1  it worked, and some lines were rejected — read the report
    2  it ran and produced nothing; the reason is on stdout
    3  it could not run: a missing file, a contradictory mapping, a refusal

1 and 2 are the two that matter. A partial success that returned 0 is the
failure this tool exists to prevent, because nobody reads the report of a
command that succeeded.
"""

import sys
from argparse import ArgumentParser

from loghog import __version__, cli_ingest, cli_inspect
from loghog.cli_common import EXIT_CANNOT_RUN


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(
        prog="loghog",
        description="Turn production logs into an evaluation dataset, privately.",
    )
    parser.add_argument("--version", action="version", version=f"loghog {__version__}")
    subparsers = parser.add_subparsers(dest="command")
    cli_ingest.add_parser(subparsers)
    cli_inspect.add_parsers(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return EXIT_CANNOT_RUN
    return handler(args)
