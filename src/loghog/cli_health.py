"""`loghog health` — stage 08, the question nobody asks until it is too late.

It has no unhealthy exit code, and that is deliberate. The threshold at which a
dataset becomes unhealthy is a decision this stage does not make; encoding one in
an exit code would make it — quietly, in a constant, for everybody who ever runs
it. The report gives the numbers and the interval, and a team decides.

It also decides nothing else: it retires no case, adds no case and changes no
goldens file. The command that adds one is `loghog promote`, and it needs a name.
"""

from argparse import Namespace
from pathlib import Path

from loghog.cli_common import add_config_option, config_from, fail
from loghog.errors import LoghogError
from loghog.health.run import health_report


def add_parsers(subparsers) -> None:
    health = subparsers.add_parser(
        "health",
        help="is this eval set still about the system you are running?",
        description=(
            "Coverage of a window's clusters by a goldens file, with a Wilson interval; "
            "the same threshold read the other way as staleness; a signal-by-signal "
            "coverage table; the uncovered clusters ranked as what to mine next; and "
            "pairs of cases that are near-duplicates of each other. Writes "
            "health/<window>.md and .json, neither of which quotes anything."
        ),
    )
    health.add_argument("--window", required=True, help="a recent window to check against")
    health.add_argument(
        "--goldens",
        required=True,
        type=Path,
        help="the goldens file to check, read with project 1's loader",
    )
    add_config_option(health)
    health.set_defaults(handler=run_health)


def run_health(args: Namespace) -> int:
    try:
        config = config_from(args)
        outcome = health_report(config, window=args.window, goldens_path=args.goldens)
    except LoghogError as exc:
        return fail(str(exc))

    coverage = outcome.coverage
    low, high = coverage.interval
    comparison = outcome.comparison
    lines = [
        f"Dataset {outcome.goldens_path.name!r} against window {outcome.window!r}: "
        f"{outcome.staleness.total} case(s), {coverage.total} cluster(s).",
        f"  coverage {coverage.covered}/{coverage.total} ({coverage.share:.0%}), "
        f"Wilson {low:.0%}–{high:.0%}",
        f"  staleness {outcome.staleness.stale}/{outcome.staleness.total} "
        f"({outcome.staleness.share:.0%}) — no traffic here looks like them",
        f"  signalled clusters covered {comparison.signalled_covered}/"
        f"{comparison.signalled_total}, ordinary {comparison.ordinary_covered}/"
        f"{comparison.ordinary_total}, Fisher p = {comparison.p_value:.3f}",
        f"  {outcome.uncovered_clusters} cluster(s) have no case at all; the "
        f"{len(outcome.recommendations)} biggest are ranked in the report",
        f"  written to {outcome.markdown_path.name} and {outcome.json_path.name}",
    ]
    print("\n".join(lines))
    return 0
