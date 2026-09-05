"""The shapes a health report is made of, and how each one becomes JSON.

Split out of `run` because the computation and the vocabulary are two different
things to read. Every one of them is a count, a share, an id or a threshold —
there is not a field here that could hold a word somebody wrote, which is what
lets the JSON document be pasted into a dashboard without anybody thinking about
it twice.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loghog import __version__

HEALTH_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Coverage:
    """What share of the traffic's subjects the dataset has a case about."""

    covered: int
    total: int
    interval: tuple[float, float]

    @property
    def share(self) -> float:
        return self.covered / self.total if self.total else 0.0

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "covered_clusters": self.covered,
            "interval": list(self.interval),
            "share": self.share,
            "total_clusters": self.total,
        }


@dataclass(frozen=True)
class StaleCase:
    """One case with nothing in recent traffic that looks like it."""

    case_id: str
    best_overlap: float

    def to_json_dict(self) -> dict[str, Any]:
        return {"best_overlap": self.best_overlap, "case_id": self.case_id}


@dataclass(frozen=True)
class Staleness:
    """How much of the dataset is about traffic that has stopped arriving."""

    stale: int
    total: int
    entries: tuple[StaleCase, ...]

    @property
    def share(self) -> float:
        return self.stale / self.total if self.total else 0.0

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "share": self.share,
            "stale_cases": self.stale,
            "stale_ranked": [entry.to_json_dict() for entry in self.entries],
            "total_cases": self.total,
        }


@dataclass(frozen=True)
class SignalCoverage:
    """One signal: how much traffic fired it, and how much of that is covered."""

    signal: str
    records: int
    covered_records: int

    @property
    def share(self) -> float:
        return self.covered_records / self.records if self.records else 0.0

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "covered_records": self.covered_records,
            "records": self.records,
            "share": self.share,
            "signal": self.signal,
        }


@dataclass(frozen=True)
class Gap:
    """One cluster the dataset has no case about — the list of what to mine next."""

    cluster_id: str
    size: int
    best_overlap: float
    top_score: int
    signals: tuple[str, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "best_overlap": self.best_overlap,
            "cluster_id": self.cluster_id,
            "signals": list(self.signals),
            "size": self.size,
            "top_score": self.top_score,
        }


@dataclass(frozen=True)
class RedundantPair:
    """Two cases that are near-duplicates of each other — what to retire."""

    left: str
    right: str
    jaccard: float

    def to_json_dict(self) -> dict[str, Any]:
        return {"jaccard": self.jaccard, "left": self.left, "right": self.right}


@dataclass(frozen=True)
class CoverageComparison:
    """Does the dataset cover the interesting traffic as well as the dull traffic?"""

    signalled_covered: int
    signalled_total: int
    ordinary_covered: int
    ordinary_total: int
    p_value: float

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "ordinary_covered": self.ordinary_covered,
            "ordinary_total": self.ordinary_total,
            "p_value": self.p_value,
            "signalled_covered": self.signalled_covered,
            "signalled_total": self.signalled_total,
        }


@dataclass(frozen=True)
class HealthOutcome:
    """One dataset, one window, and the four questions."""

    window: str
    synthetic: bool
    goldens_path: Path
    goldens_sha256: str
    threshold: float
    coverage: Coverage
    staleness: Staleness
    signal_coverage: tuple[SignalCoverage, ...]
    recommendations: tuple[Gap, ...]
    uncovered_clusters: int
    redundant: tuple[RedundantPair, ...]
    comparison: CoverageComparison
    markdown_path: Path
    json_path: Path

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "comparison": self.comparison.to_json_dict(),
            "coverage": self.coverage.to_json_dict(),
            "goldens": str(self.goldens_path.name),
            "goldens_sha256": self.goldens_sha256,
            "loghog_version": __version__,
            "neighbour_jaccard": self.threshold,
            "recommendations": [entry.to_json_dict() for entry in self.recommendations],
            "redundant_pairs": [pair.to_json_dict() for pair in self.redundant],
            "schema_version": HEALTH_SCHEMA_VERSION,
            "signal_coverage": [entry.to_json_dict() for entry in self.signal_coverage],
            "staleness": self.staleness.to_json_dict(),
            "synthetic": self.synthetic,
            "uncovered_clusters": self.uncovered_clusters,
            "window": self.window,
        }


__all__ = [
    "HEALTH_SCHEMA_VERSION",
    "Coverage",
    "CoverageComparison",
    "Gap",
    "HealthOutcome",
    "RedundantPair",
    "SignalCoverage",
    "StaleCase",
    "Staleness",
]
