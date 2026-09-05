"""Comparing two windows: four questions, four numbers, and no text at all.

The question nobody asks until it is too late is whether the eval set is still
about the system being run. This stage answers the half of it that needs no
goldens file: has the *traffic* moved?

- **Signal rates.** Which signals fire more often now than they did.
- **Cluster novelty.** What share of the newer window's subjects the older one
  had never seen — the list of what to mine next, ranked by how many people
  wrote in about it.
- **Input length.** A two-sample KS statistic, because "inputs got longer" is a
  distribution claim and a mean would hide it.
- **Error and negative-feedback rates**, each with a Wilson interval from
  project 1, because a rate computed from four hundred records is not a point.

Nothing it writes holds a word from either window. Cluster ids, counts, rates
and a statistic are all a person needs in order to decide whether to mine again,
and none of it is anything a person would have to be careful with.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loghog import __version__
from loghog.cluster.shingles import jaccard, shingles
from loghog.config_file import LoghogConfig
from loghog.drift.report import render_drift_report
from loghog.drift.stats import RateComparison, compare_rates, ks_statistic, median
from loghog.errors import AnalysisError, DriftError
from loghog.record import Record
from loghog.score.settings import SIGNAL_NAMES
from loghog.window.artifacts import read_clusters, read_jsonl, write_json, write_text
from loghog.window.store import WindowStore

DRIFT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class NovelCluster:
    """One subject in the newer window that the older one had not seen."""

    cluster_id: str
    size: int
    best_overlap: float

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "best_overlap": self.best_overlap,
            "cluster_id": self.cluster_id,
            "size": self.size,
        }


@dataclass(frozen=True)
class ClusterNovelty:
    """How much of the newer window is about something new."""

    total_clusters: int
    new_clusters: int
    threshold: float
    entries: tuple[NovelCluster, ...]

    @property
    def share(self) -> float:
        return self.new_clusters / self.total_clusters if self.total_clusters else 0.0

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "new_clusters": self.new_clusters,
            "new_clusters_ranked": [entry.to_json_dict() for entry in self.entries],
            "share": self.share,
            "threshold": self.threshold,
            "total_clusters": self.total_clusters,
        }


@dataclass(frozen=True)
class LengthShift:
    """Whether inputs got longer, as a statistic rather than as an impression."""

    ks_statistic: float
    earlier_median: float
    later_median: float
    earlier_n: int
    later_n: int

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "earlier_median": self.earlier_median,
            "earlier_n": self.earlier_n,
            "ks_statistic": self.ks_statistic,
            "later_median": self.later_median,
            "later_n": self.later_n,
        }


@dataclass(frozen=True)
class DriftOutcome:
    """One comparison of two windows."""

    earlier: str
    later: str
    signal_rates: dict[str, RateComparison]
    novelty: ClusterNovelty
    input_length: LengthShift
    rates: dict[str, RateComparison]
    markdown_path: Path
    json_path: Path

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "cluster_novelty": self.novelty.to_json_dict(),
            "earlier": self.earlier,
            "input_length": self.input_length.to_json_dict(),
            "later": self.later,
            "loghog_version": __version__,
            "rates": {
                name: comparison.to_json_dict() for name, comparison in sorted(self.rates.items())
            },
            "schema_version": DRIFT_SCHEMA_VERSION,
            "signal_rates": {
                name: comparison.to_json_dict()
                for name, comparison in sorted(self.signal_rates.items())
            },
        }


def drift_report(
    config: LoghogConfig, *, earlier: str, later: str, out_dir: Path | None = None
) -> DriftOutcome:
    """Compare two scored, clustered windows and write both reports.

    Raises:
        DriftError: the same window twice, a window that does not exist, or one
            that has not been scored or clustered. Every message names the
            command that fixes it.
    """
    if earlier == later:
        raise DriftError(
            f"comparing window {earlier!r} with itself measures nothing. Name two windows."
        )
    old_records, old_signals = _window(config, earlier)
    new_records, new_signals = _window(config, later)

    signal_rates = {
        name: compare_rates(
            earlier=(sum(1 for names in old_signals.values() if name in names), len(old_records)),
            later=(sum(1 for names in new_signals.values() if name in names), len(new_records)),
            name=name,
        )
        for name in SIGNAL_NAMES
    }
    rates = {
        "error": compare_rates(
            earlier=(sum(1 for r in old_records if r.failed), len(old_records)),
            later=(sum(1 for r in new_records if r.failed), len(new_records)),
            name="error",
        ),
        "negative_feedback": compare_rates(
            earlier=(_negative(old_records, config), len(old_records)),
            later=(_negative(new_records, config), len(new_records)),
            name="negative_feedback",
        ),
    }
    novelty = _novelty(config, old_records, later=later, new_records=new_records)
    lengths = LengthShift(
        ks_statistic=ks_statistic(
            [len(r.input_text) for r in old_records], [len(r.input_text) for r in new_records]
        ),
        earlier_median=median([len(r.input_text) for r in old_records]),
        later_median=median([len(r.input_text) for r in new_records]),
        earlier_n=len(old_records),
        later_n=len(new_records),
    )

    directory = Path(out_dir) if out_dir is not None else config.drift_dir
    outcome = DriftOutcome(
        earlier=earlier,
        later=later,
        signal_rates=signal_rates,
        novelty=novelty,
        input_length=lengths,
        rates=rates,
        markdown_path=directory / f"{earlier}-vs-{later}.md",
        json_path=directory / f"{earlier}-vs-{later}.json",
    )
    write_json(outcome.json_path, outcome.to_json_dict())
    write_text(outcome.markdown_path, render_drift_report(outcome))
    return outcome


def _window(config: LoghogConfig, window: str) -> tuple[list[Record], dict[str, tuple[str, ...]]]:
    """One window's records and per-record signal names, or a named refusal."""
    store = WindowStore(config.records_dir / window)
    if not store.records_path.is_file():
        raise DriftError(
            f"no window named {window!r} at {store.directory}. "
            f"Run `loghog ingest --window {window} ...` first."
        )
    records = store.read_records()
    if not records:
        raise DriftError(f"window {window!r} holds no records to compare")
    if not store.scores_path.is_file():
        raise DriftError(
            f"window {window!r} has not been scored. Run `loghog score --window {window}` first."
        )
    if not store.clusters_path.is_file():
        raise DriftError(
            f"window {window!r} has not been clustered. "
            f"Run `loghog cluster --window {window}` first."
        )
    signals = {}
    for payload in read_jsonl(store.scores_path, what="scores file"):
        signals[payload["record_id"]] = tuple(
            entry["name"] for entry in payload.get("signals", [])
        )
    return records, signals


def _negative(records: list[Record], config: LoghogConfig) -> int:
    vocabulary = config.score.negative_feedback_words
    return sum(
        1
        for record in records
        if record.feedback is not None and record.feedback.strip().lower() in vocabulary
    )


def _novelty(
    config: LoghogConfig, old_records: list[Record], *, later: str, new_records: list[Record]
) -> ClusterNovelty:
    """Which of the newer window's clusters the older window had never seen.

    Compared representative-against-every-record rather than
    cluster-against-cluster, because the older window's partition is a fact
    about the older window's traffic and this question is about its *content*.
    """
    store = WindowStore(config.records_dir / later)
    try:
        payload = read_clusters(store)
    except AnalysisError as exc:
        raise DriftError(str(exc)) from exc
    size = config.cluster.shingle_words
    theirs = [shingles(record.input_text, size=size) for record in old_records]
    by_id = {record.record_id: record for record in new_records}
    entries = []
    for cluster in payload["clusters"]:
        representative = by_id.get(cluster["representative_id"])
        if representative is None:
            raise DriftError(
                f"window {later!r} names a representative it does not hold "
                f"({cluster['representative_id']!r}). Re-run `loghog cluster --window {later}`."
            )
        mine = shingles(representative.input_text, size=size)
        best = max((jaccard(mine, other) for other in theirs), default=0.0)
        if best < config.drift.novel_cluster_jaccard:
            entries.append(
                NovelCluster(
                    cluster_id=cluster["cluster_id"],
                    size=len(cluster["member_ids"]),
                    best_overlap=best,
                )
            )
    entries.sort(key=lambda entry: (-entry.size, entry.cluster_id))
    return ClusterNovelty(
        total_clusters=len(payload["clusters"]),
        new_clusters=len(entries),
        threshold=config.drift.novel_cluster_jaccard,
        entries=tuple(entries),
    )
