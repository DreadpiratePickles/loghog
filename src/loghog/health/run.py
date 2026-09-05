"""Stage 08: coverage, staleness, gaps and redundancy, for one dataset and one window.

The question nobody asks until it is too late is whether the eval set is still
about the system being run. Stage 09 answers the half that needs no dataset —
has the traffic moved? — and this answers the other half.

**One threshold does coverage and staleness.** A cluster is covered when some
record in it has a golden case within `[health] neighbour_jaccard`; a case is
stale when no record in the window is that close to it. Same relation, read from
both ends. Two thresholds would let a report say a cluster is covered by a case
that is itself stale against that cluster, which is not a finding.

**Coverage is per cluster, and a cluster counts as covered when *any* member
does.** Not the representative alone: single-linkage merging is transitive, so a
cluster's representative can be several links away from the member a golden
actually matches, and asking only the representative would call a covered
subject uncovered. The cost is one Jaccard per record per case, which is nothing
at the sizes an eval set has.

**The one comparison is between the interesting traffic and the ordinary
traffic**, with project 1's `fisher_exact_one_sided`. A dataset that covers the
boring clusters and misses the ones where something fired is a dataset that will
pass every release and catch nothing, and that is the single most useful thing
this report can tell you. It is a p-value about two counts a person can see,
computed exactly, and it is called a p-value because that is what it is.

Nothing this stage writes holds a word from the traffic or from the dataset.
Cluster ids, case ids, counts and thresholds are what a person needs to decide
what to mine next, and none of it is anything they have to be careful with.
"""

from pathlib import Path
from typing import Any

from regression_detect.compare import fisher_exact_one_sided, wilson_interval
from regression_detect.goldens import GoldenCase, GoldenDatasetError, goldens_sha256, load_goldens

from loghog.cluster.shingles import jaccard, shingles
from loghog.config_file import LoghogConfig
from loghog.errors import AnalysisError, HealthError, ManifestError
from loghog.health.model import (
    Coverage,
    CoverageComparison,
    Gap,
    HealthOutcome,
    RedundantPair,
    SignalCoverage,
    StaleCase,
    Staleness,
)
from loghog.health.report import render_health_report
from loghog.score.settings import SIGNAL_NAMES
from loghog.window.artifacts import read_clusters, read_signals, write_json, write_text
from loghog.window.store import WindowStore

NOVELTY = "novelty"
"""The one signal excluded from the interesting-versus-ordinary split below.

Every other signal is a property of the traffic: an error happened, a customer
said the answer was bad, a latency was in the top five per cent. `novelty` is a
property of the *dataset* — a record is novel when no case in the goldens file
looks like it — and a window scored with `--existing` fires it on almost exactly
the set of clusters this report is about to call uncovered.

Counting it would make the comparison read "clusters the dataset does not cover
are covered less often than the clusters it does", which is true of every
dataset ever assembled and tells you nothing about any of them.
"""


def markdown_path_for(config: LoghogConfig, window: str) -> Path:
    return config.health_dir / f"{window}.md"


def json_path_for(config: LoghogConfig, window: str) -> Path:
    return config.health_dir / f"{window}.json"


def health_report(
    config: LoghogConfig, *, window: str, goldens_path: Path, out_dir: Path | None = None
) -> HealthOutcome:
    """Check one goldens file against one scored, clustered window.

    Raises:
        HealthError: the goldens file is absent or project 1's loader refuses
            it, or the window has not been ingested, scored or clustered.
    """
    cases = _load_goldens(Path(goldens_path))
    store = WindowStore(
        Path(out_dir) if out_dir is not None else config.records_dir / window
    )
    if not store.records_path.is_file():
        raise HealthError(
            f"no window at {store.directory}. Run `loghog ingest --window {window} ...` "
            "first, or check the window name."
        )
    records = store.read_records()
    if not records:
        raise HealthError(f"window {window!r} holds no records to check a dataset against")
    try:
        clusters = read_clusters(store)["clusters"]
        signals = read_signals(store)
    except AnalysisError as exc:
        raise HealthError(str(exc)) from exc

    width = config.cluster.shingle_words
    threshold = config.health.neighbour_jaccard
    record_shingles = {
        record.record_id: shingles(record.input_text, size=width) for record in records
    }
    case_shingles = {case.id: shingles(case.input, size=width) for case in cases}
    scores = {row["record_id"]: int(row["score"]) for row in _score_rows(store)}

    best_for_record = {
        record_id: max(
            (jaccard(mine, theirs) for theirs in case_shingles.values()), default=0.0
        )
        for record_id, mine in record_shingles.items()
    }
    covered_records = {
        record_id for record_id, best in best_for_record.items() if best >= threshold
    }

    gaps, covered_clusters = _clusters(
        clusters,
        covered_records,
        scores=scores,
        signals=signals,
        best_for_record=best_for_record,
    )
    coverage = Coverage(
        covered=covered_clusters,
        total=len(clusters),
        interval=wilson_interval(covered_clusters, len(clusters)),
    )
    outcome = HealthOutcome(
        window=window,
        synthetic=_synthetic(store),
        goldens_path=Path(goldens_path),
        goldens_sha256=goldens_sha256(Path(goldens_path)),
        threshold=threshold,
        coverage=coverage,
        staleness=_staleness(cases, case_shingles, record_shingles, threshold),
        signal_coverage=_signal_coverage(signals, covered_records),
        recommendations=tuple(gaps[: config.health.max_recommendations]),
        uncovered_clusters=len(gaps),
        redundant=_redundant(cases, case_shingles, threshold),
        comparison=_comparison(clusters, covered_records, signals),
        markdown_path=markdown_path_for(config, window),
        json_path=json_path_for(config, window),
    )
    write_json(outcome.json_path, outcome.to_json_dict())
    write_text(outcome.markdown_path, render_health_report(outcome))
    return outcome


def _synthetic(store: WindowStore) -> bool:
    """Whether the window this dataset was checked against was invented.

    A window whose manifest cannot be read is not called real, for the reason
    stage 05 gives: a report that dropped its banner because a file was
    unreadable is the report somebody quotes as a measurement.
    """
    try:
        return store.read_manifest().synthetic
    except ManifestError:
        return True


def _load_goldens(path: Path) -> list[GoldenCase]:
    if not path.is_file():
        raise HealthError(
            f"no goldens file at {path}. Coverage against nothing is not a number."
        )
    try:
        return load_goldens(path)
    except GoldenDatasetError as exc:
        # Project 1's own message, not a restatement: the schema belongs to the
        # code that owns it, and so does the complaint about it.
        raise HealthError(f"{path} is not a golden dataset this build can read: {exc}") from exc


def _score_rows(store: WindowStore) -> list[dict[str, Any]]:
    from loghog.window.artifacts import read_jsonl

    return read_jsonl(store.scores_path, what="scores file")


def _clusters(
    clusters: list[dict[str, Any]],
    covered_records: set[str],
    *,
    scores: dict[str, int],
    signals: dict[str, tuple[str, ...]],
    best_for_record: dict[str, float],
) -> tuple[list[Gap], int]:
    """Split the partition into covered and uncovered, and rank the uncovered."""
    gaps: list[Gap] = []
    covered = 0
    for cluster in clusters:
        members = list(cluster["member_ids"])
        if any(member in covered_records for member in members):
            covered += 1
            continue
        fired: list[str] = []
        for member in members:
            for name in signals.get(member, ()):
                if name not in fired:
                    fired.append(name)
        gaps.append(
            Gap(
                cluster_id=cluster["cluster_id"],
                size=len(members),
                best_overlap=max((best_for_record.get(m, 0.0) for m in members), default=0.0),
                top_score=max((scores.get(member, 0) for member in members), default=0),
                signals=tuple(name for name in SIGNAL_NAMES if name in fired),
            )
        )
    # Biggest first, then loudest, then by id — so two runs over one window
    # produce the same list and a reader can act on the top of it.
    gaps.sort(key=lambda gap: (-gap.size, -gap.top_score, gap.cluster_id))
    return gaps, covered


def _staleness(
    cases: list[GoldenCase],
    case_shingles: dict[str, frozenset[str]],
    record_shingles: dict[str, frozenset[str]],
    threshold: float,
) -> Staleness:
    entries = []
    for case in cases:
        best = max(
            (jaccard(case_shingles[case.id], mine) for mine in record_shingles.values()),
            default=0.0,
        )
        if best < threshold:
            entries.append(StaleCase(case_id=case.id, best_overlap=best))
    entries.sort(key=lambda entry: (entry.best_overlap, entry.case_id))
    return Staleness(stale=len(entries), total=len(cases), entries=tuple(entries))


def _signal_coverage(
    signals: dict[str, tuple[str, ...]], covered_records: set[str]
) -> tuple[SignalCoverage, ...]:
    """One row per signal, including the ones that never fired.

    A missing row reads as "we did not look", which is the failure `score.md`
    already refuses to commit.
    """
    rows = []
    for name in SIGNAL_NAMES:
        firing = [rid for rid, fired in signals.items() if name in fired]
        rows.append(
            SignalCoverage(
                signal=name,
                records=len(firing),
                covered_records=sum(1 for rid in firing if rid in covered_records),
            )
        )
    return tuple(rows)


def _redundant(
    cases: list[GoldenCase], case_shingles: dict[str, frozenset[str]], threshold: float
) -> tuple[RedundantPair, ...]:
    pairs = []
    ordered = [case.id for case in cases]
    for index, left in enumerate(ordered):
        for right in ordered[index + 1 :]:
            similarity = jaccard(case_shingles[left], case_shingles[right])
            if similarity >= threshold:
                pairs.append(RedundantPair(left=left, right=right, jaccard=similarity))
    pairs.sort(key=lambda pair: (-pair.jaccard, pair.left, pair.right))
    return tuple(pairs)


def _traffic_signals(
    signals: dict[str, tuple[str, ...]], record_id: str
) -> tuple[str, ...]:
    """One record's signals, minus the one that is about the dataset."""
    return tuple(name for name in signals.get(record_id, ()) if name != NOVELTY)


def _comparison(
    clusters: list[dict[str, Any]],
    covered_records: set[str],
    signals: dict[str, tuple[str, ...]],
) -> CoverageComparison:
    """Coverage of clusters where something fired, against clusters where nothing did.

    Baseline is the ordinary traffic and candidate is the signalled traffic, so
    the p-value is the chance of seeing the interesting half covered this badly
    when both halves are covered at one and the same rate. That is the question
    worth asking: an eval set that covers the dull traffic and misses the
    interesting traffic passes every release and catches nothing.
    """
    signalled = [0, 0]
    ordinary = [0, 0]
    for cluster in clusters:
        members = list(cluster["member_ids"])
        bucket = signalled if any(_traffic_signals(signals, m) for m in members) else ordinary
        bucket[1] += 1
        if any(member in covered_records for member in members):
            bucket[0] += 1
    return CoverageComparison(
        signalled_covered=signalled[0],
        signalled_total=signalled[1],
        ordinary_covered=ordinary[0],
        ordinary_total=ordinary[1],
        p_value=fisher_exact_one_sided(ordinary[0], ordinary[1], signalled[0], signalled[1]),
    )


__all__ = ["health_report", "json_path_for", "markdown_path_for"]
