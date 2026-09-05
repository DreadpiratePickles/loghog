"""`loghog score` and `loghog cluster` — stages 03 and 04 from a shell.

`score` is the one command in this package whose exit code says something new.
It is 1 when a signal could not be evaluated **because of how the window was
built** — deduplicated on the input, so no version disagreement can be seen; two
sources disagreeing about whether outputs should be JSON. It is 0 when the only
absences are ones somebody chose, like not passing a goldens file. The
distinction matters because a code that was 1 on every run would stop being read.
"""

from argparse import Namespace
from pathlib import Path

from loghog.cli_common import add_config_option, config_from, fail, load_existing_inputs
from loghog.cluster.window import cluster_window
from loghog.errors import LoghogError
from loghog.ingest.report import SYNTHETIC_BANNER, UNREDACTED_BANNER
from loghog.score.run import score_window
from loghog.score.settings import SIGNAL_NAMES
from loghog.window.store import (
    CLUSTER_REPORT_NAME,
    CLUSTERS_NAME,
    SCORE_REPORT_NAME,
    SCORES_NAME,
    WindowStore,
)


def add_parsers(subparsers) -> None:
    score = subparsers.add_parser(
        "score",
        help="score every record in a window for how much it would teach",
        description=(
            "Attach an explainable score to every record: judge failures, negative "
            "feedback, disagreements, refusals, injection attempts, outliers. Writes "
            f"{SCORES_NAME} and {SCORE_REPORT_NAME} into the window. Exits 1 if a signal "
            "could not be evaluated because of how the window was built."
        ),
    )
    score.add_argument("--window", required=True, help="the window to score")
    score.add_argument(
        "--existing",
        type=Path,
        default=None,
        help="a goldens file to measure novelty against, read with project 1's loader",
    )
    add_config_option(score)
    score.set_defaults(handler=run_score)

    cluster = subparsers.add_parser(
        "cluster",
        help="group near-duplicates so one outage is one case",
        description=(
            "Five-word shingles, MinHash sketches, LSH banding, then an exact Jaccard "
            f"check on every candidate pair. Writes {CLUSTERS_NAME} and "
            f"{CLUSTER_REPORT_NAME}. Needs the window to have been scored: the score is "
            "what decides which member of a cluster speaks for it."
        ),
    )
    cluster.add_argument("--window", required=True, help="the window to cluster")
    add_config_option(cluster)
    cluster.set_defaults(handler=run_cluster)


def run_score(args: Namespace) -> int:
    try:
        config = config_from(args)
        golden_inputs = load_existing_inputs(args.existing)
        outcome = score_window(config, window=args.window, golden_inputs=golden_inputs)
    except LoghogError as exc:
        return fail(str(exc))

    manifest = WindowStore(outcome.directory).read_manifest()
    lines: list[str] = []
    if manifest.synthetic:
        lines.append(SYNTHETIC_BANNER)
    if not manifest.redaction.get("enabled"):
        lines.append(UNREDACTED_BANNER)
    fired = sum(1 for entry in outcome.scores if entry.score > 0)
    lines += [
        f"Window {outcome.window!r}: {outcome.scored} record(s) scored, "
        f"{fired} of which fired at least one signal.",
    ]
    for name in SIGNAL_NAMES:
        count = outcome.by_signal.get(name)
        if count:
            lines.append(f"  {name}  {count}")
    blocking = [entry for entry in outcome.context.not_evaluated if entry.blocking]
    quiet = [entry for entry in outcome.context.not_evaluated if not entry.blocking]
    for entry in blocking:
        lines.append(f"  NOT EVALUATED: {entry.signal} — {entry.reason}")
    for entry in quiet:
        lines.append(f"  not evaluated: {entry.signal} — {entry.reason}")
    lines.append(f"  the full report is in {SCORE_REPORT_NAME}")
    print("\n".join(lines))
    return outcome.exit_code


def run_cluster(args: Namespace) -> int:
    try:
        config = config_from(args)
        outcome = cluster_window(config, window=args.window)
    except LoghogError as exc:
        return fail(str(exc))

    singletons = sum(1 for cluster in outcome.clusters if cluster.size == 1)
    print(
        f"Window {args.window!r}: {len(outcome.clusters)} cluster(s), "
        f"{singletons} singleton(s), largest {outcome.largest}.\n"
        f"  {outcome.comparisons} pair(s) compared exactly, "
        f"{len(outcome.merged_pairs)} merged at a Jaccard of "
        f"{config.cluster.threshold} or more\n"
        f"  the full report is in {CLUSTER_REPORT_NAME}"
    )
    return 0
