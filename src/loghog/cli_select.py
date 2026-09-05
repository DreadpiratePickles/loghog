"""`loghog select` and `loghog drift` — stage 05 and the window comparison.

`select` exits 1 when the global cap truncated the shortlist and 2 when nothing
was chosen. An *unfilled stratum* does not change the code: most windows contain
no injection attempts, and a code that was 1 on almost every run would stop
being read. It is printed instead, on the terminal and in `selection.md`, which
is where a shortfall belongs.
"""

from argparse import Namespace
from pathlib import Path

from loghog.cli_common import add_config_option, config_from, fail, load_existing_inputs
from loghog.drift.run import drift_report
from loghog.errors import LoghogError
from loghog.select.run import (
    CANDIDATES_NAME,
    EXIT_NOTHING,
    SELECTION_REPORT_NAME,
    select_candidates,
)


def add_parsers(subparsers) -> None:
    select = subparsers.add_parser(
        "select",
        help="choose the shortlist: highest signal, one per cluster, stratified",
        description=(
            "Turn a scored, clustered window into a shortlist, with the reason each "
            f"record was chosen beside it. Writes {CANDIDATES_NAME} and "
            f"{SELECTION_REPORT_NAME}. Every record that did not make it was refused by "
            "exactly one named cap, and the summary counts each."
        ),
    )
    select.add_argument("--window", required=True, help="the window to select from")
    select.add_argument(
        "--max-candidates",
        type=int,
        default=None,
        help="override [select] max_candidates for this run",
    )
    select.add_argument(
        "--existing",
        type=Path,
        default=None,
        help="a goldens file whose cases are suppressed, read with project 1's loader",
    )
    add_config_option(select)
    select.set_defaults(handler=run_select)

    drift = subparsers.add_parser(
        "drift",
        help="compare two windows: signal rates, new subjects, length, error rates",
        description=(
            "Has the traffic moved? Signal rates, the share of the later window's "
            "clusters the earlier one never saw, a KS statistic over input lengths, and "
            "error and negative-feedback rates with Wilson intervals. Both windows must "
            "have been scored and clustered. The report holds no text from either."
        ),
    )
    drift.add_argument("--from", dest="earlier", required=True, help="the earlier window")
    drift.add_argument("--to", dest="later", required=True, help="the later window")
    add_config_option(drift)
    drift.set_defaults(handler=run_drift)


def run_select(args: Namespace) -> int:
    try:
        config = config_from(args)
        golden_inputs = load_existing_inputs(args.existing)
        outcome = select_candidates(
            config,
            window=args.window,
            max_candidates=args.max_candidates,
            golden_inputs=golden_inputs,
        )
    except LoghogError as exc:
        return fail(str(exc))

    lines = [
        f"Window {outcome.window!r}: {outcome.selected_count} candidate(s) of "
        f"{outcome.considered} scored record(s), at most {outcome.max_candidates} "
        f"and at most {outcome.max_per_cluster} per cluster."
    ]
    chosen = [stratum for stratum in outcome.strata if stratum.selected]
    for stratum in chosen:
        lines.append(f"  {stratum.name}  {stratum.selected} of {stratum.quota}")
    if outcome.dropped:
        lines.append("  dropped, by cap:")
        lines += [
            f"    {name}  {count}" for name, count in sorted(outcome.dropped.items())
        ]
    unfilled = outcome.unfilled
    if unfilled:
        named = ", ".join(f"{name} ({short} short)" for name, short in unfilled)
        lines.append(f"  unfilled strata, never topped up from another: {named}")
    if outcome.exit_code == EXIT_NOTHING:
        lines.append("  nothing was selected. Every quota is zero, or every record was capped.")
    lines.append(f"  the full summary is in {SELECTION_REPORT_NAME}")
    print("\n".join(lines))
    return outcome.exit_code


def run_drift(args: Namespace) -> int:
    try:
        config = config_from(args)
        outcome = drift_report(config, earlier=args.earlier, later=args.later)
    except LoghogError as exc:
        return fail(str(exc))

    novelty = outcome.novelty
    errors = outcome.rates["error"]
    lengths = outcome.input_length
    lines = [
        f"Drift {outcome.earlier!r} -> {outcome.later!r}: "
        f"{lengths.earlier_n} record(s) then, {lengths.later_n} now.",
        f"  {novelty.new_clusters} new cluster(s) of {novelty.total_clusters} "
        f"({novelty.share:.0%}) — nothing in {outcome.earlier!r} looks like them",
        f"  error rate {errors.earlier_rate:.1%} -> {errors.later_rate:.1%} "
        f"({'intervals separated' if errors.separated else 'intervals overlap'})",
        f"  input length KS statistic {lengths.ks_statistic:.3f}, median "
        f"{lengths.earlier_median:.0f} -> {lengths.later_median:.0f} chars",
        f"  written to {outcome.markdown_path.name} and {outcome.json_path.name}",
    ]
    print("\n".join(lines))
    return 0
