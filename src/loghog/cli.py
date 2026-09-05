"""The command line.

Eight commands. Four of them write, and the four that do are the pipeline:
ingest, then score, then cluster, then select.

    loghog ingest      read a log into a window of redacted canonical records
    loghog score       score every record for how much it would teach
    loghog cluster     group near-duplicates so one outage is one case
    loghog select      choose the shortlist, stratified and one per cluster
    loghog drift       compare two windows: what changed, and how sure
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

Phase B adds two meanings to 1 and one to 2, and both are the same rule applied
again. `score` exits 1 when a signal could not be evaluated *because of how the
window was built*; `select` exits 1 when the global cap truncated a shortlist
that had more worth taking, and 2 when it chose nothing at all. An absence
somebody chose — no goldens file, a window too small for a percentile — stays 0.
"""

import sys
from argparse import ArgumentParser

from loghog import (
    __version__,
    cli_emit,
    cli_health,
    cli_ingest,
    cli_inspect,
    cli_label,
    cli_score,
    cli_select,
)
from loghog.cli_common import EXIT_CANNOT_RUN


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(
        prog="loghog",
        description="Turn production logs into an evaluation dataset, privately.",
    )
    parser.add_argument("--version", action="version", version=f"loghog {__version__}")
    subparsers = parser.add_subparsers(dest="command")
    cli_ingest.add_parser(subparsers)
    cli_score.add_parsers(subparsers)
    cli_select.add_parsers(subparsers)
    cli_label.add_parsers(subparsers)
    cli_emit.add_parsers(subparsers)
    cli_health.add_parsers(subparsers)
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
