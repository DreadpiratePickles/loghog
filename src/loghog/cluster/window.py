"""Stage 04 as a command: read a scored window, partition it, write the result.

Clustering needs the scores, and only for one thing — deciding which member of
a cluster speaks for it. That is a real dependency and it is declared rather
than worked around: an unscored window is refused by name, with the command that
fixes it, instead of quietly picking a representative alphabetically.
"""

from pathlib import Path

from loghog import __version__
from loghog.cluster.run import ClusterOutcome, cluster_records
from loghog.config_file import LoghogConfig
from loghog.errors import ClusterError, ManifestError
from loghog.ingest.report import SYNTHETIC_BANNER
from loghog.window.artifacts import read_scores, write_json, write_text
from loghog.window.store import WindowStore


def cluster_window(
    config: LoghogConfig, *, window: str, out_dir: Path | None = None
) -> ClusterOutcome:
    """Partition one window and write `clusters.json` and `cluster.md`.

    Raises:
        ClusterError: the window does not exist or holds no records.
        ScoreError: the window has not been scored.
    """
    directory = Path(out_dir) if out_dir is not None else config.records_dir / window
    store = WindowStore(directory)
    if not store.records_path.is_file():
        raise ClusterError(
            f"no window at {directory}. Run `loghog ingest --window {window} ...` first, "
            "or check the window name."
        )
    records = store.read_records()
    if not records:
        raise ClusterError(f"window {window!r} holds no records to cluster")
    scores = read_scores(store)
    outcome = cluster_records(records, scores=scores, params=config.cluster)
    write_json(store.clusters_path, outcome.to_json_dict(window=window))
    write_text(
        store.cluster_report_path,
        render_cluster_report(window, outcome, synthetic=_synthetic(store)),
    )
    return outcome


def _synthetic(store: WindowStore) -> bool:
    """Whether this window was built from an invented log.

    An unreadable manifest is treated as synthetic rather than as real: a
    report that dropped its banner because a file could not be parsed is the
    one somebody would quote as a measurement.
    """
    try:
        return store.read_manifest().synthetic
    except ManifestError:
        return True


def render_cluster_report(
    window: str, outcome: ClusterOutcome, *, synthetic: bool = False
) -> str:
    """`cluster.md`: the shape of the partition, and nothing from inside it.

    Two findings get their own sentence rather than being left for a reader to
    infer from a table. A window that came out as all singletons found no
    near-duplicates, which is a result. A window that came out as **one**
    cluster means the threshold is wrong, and a stage that quietly selected one
    case out of it would hide the fact that it had thrown the rest away.
    """
    params = outcome.params
    sizes = [cluster.size for cluster in outcome.clusters]
    singletons = sum(1 for size in sizes if size == 1)
    total = sum(sizes)
    lines: list[str] = []
    if synthetic:
        lines += [SYNTHETIC_BANNER, ""]
    lines += [
        f"# Clusters in window `{window}`",
        "",
        f"loghog {__version__}. {total} record(s) in {len(sizes)} cluster(s); "
        f"{singletons} singleton(s); largest {outcome.largest}.",
        "",
        f"{outcome.comparisons} pair(s) survived banding and were compared exactly; "
        f"{len(outcome.merged_pairs)} cleared the threshold and were merged. Banding "
        "proposes and the exact Jaccard disposes, so every merge below is a number a "
        "reviewer can recompute by hand.",
        "",
    ]
    if len(sizes) == 1 and total > 1:
        lines += [
            "**Every record landed in one cluster.** That is almost always a threshold "
            f"that is too low, not a window in which everybody wrote the same thing. "
            f"Raise `[cluster] jaccard_threshold` above {params.threshold} and run it "
            "again before selecting anything out of this.",
            "",
        ]
    elif singletons == len(sizes):
        lines += [
            "Every cluster is a **singleton**: nothing in this window is a near-duplicate "
            "of anything else in it at this threshold. That is a result rather than a "
            "failure — it means selection has no near-duplicates to spend its budget on.",
            "",
        ]
    lines += [
        "## Parameters",
        "",
        "| | Value |",
        "|---|---:|",
        f"| Shingle width | {params.shingle_words} words |",
        f"| Permutations | {params.permutations} |",
        f"| Bands x rows | {params.bands} x {params.rows_per_band} |",
        f"| Seed | {params.seed} |",
        f"| Jaccard threshold | {params.threshold} |",
        "",
        "## Clusters",
        "",
        "| Cluster | Size | Representative | Weakest link |",
        "|---|---:|---|---:|",
    ]
    for cluster in outcome.clusters:
        weakest = (
            f"{cluster.min_link_jaccard:.2f}" if cluster.min_link_jaccard is not None else "—"
        )
        lines.append(
            f"| `{cluster.cluster_id}` | {cluster.size} | `{cluster.representative_id}` "
            f"| {weakest} |"
        )
    lines += [
        "",
        "The weakest link is the lowest exact Jaccard among the pairs that built the "
        "cluster, not an average. Merging is transitive — A with B and B with C puts A "
        "and C together — so the weakest link is the honest number to publish.",
        "",
    ]
    if outcome.wordless_ids:
        lines += [
            f"{len(outcome.wordless_ids)} record(s) had no words left after "
            "normalisation — an input that was all digits, or all redaction tokens — "
            "and each is a singleton by construction. Two absences are not a match.",
            "",
        ]
    return "\n".join(lines) + "\n"
