"""Partitioning a window into near-duplicates: shingle, sketch, band, verify, merge.

Five steps, and the fourth is the one people leave out. LSH proposes pairs cheaply
and *approximately*; this module then computes the exact Jaccard of every proposed
pair and merges only what clears the configured threshold. That costs one set
intersection per candidate — a rounding error next to comparing every pair — and
it buys a partition whose every merge can be justified with a number a reviewer
can recompute by hand.

Nothing is thrown away. A suppressed near-duplicate is a *member* of a cluster,
recorded by id, and stage 05 chooses among representatives rather than among the
records that survived a filter.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from loghog import __version__
from loghog.cluster.lsh import UnionFind, candidate_pairs
from loghog.cluster.minhash import MinHasher
from loghog.cluster.settings import ClusterParams
from loghog.cluster.shingles import jaccard, shingles
from loghog.errors import ClusterError
from loghog.record import Record

CLUSTERS_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Cluster:
    """One group of records that are about the same thing."""

    cluster_id: str
    representative_id: str
    member_ids: tuple[str, ...]
    min_link_jaccard: float | None

    @property
    def size(self) -> int:
        return len(self.member_ids)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "member_ids": list(self.member_ids),
            "min_link_jaccard": self.min_link_jaccard,
            "representative_id": self.representative_id,
            "size": self.size,
        }


@dataclass(frozen=True)
class ClusterOutcome:
    """The partition, and what it cost to find."""

    params: ClusterParams
    clusters: tuple[Cluster, ...]
    merged_pairs: frozenset[tuple[str, str]]
    comparisons: int
    wordless_ids: tuple[str, ...]

    @property
    def largest(self) -> int:
        return max((cluster.size for cluster in self.clusters), default=0)

    def cluster_of(self) -> dict[str, str]:
        """Record id -> cluster id, for the stages that only need the label."""
        return {
            member: cluster.cluster_id
            for cluster in self.clusters
            for member in cluster.member_ids
        }

    def to_json_dict(self, *, window: str) -> dict[str, Any]:
        return {
            "clusters": [cluster.to_json_dict() for cluster in self.clusters],
            "exact_comparisons": self.comparisons,
            "largest_cluster": self.largest,
            "loghog_version": __version__,
            "merged_pairs": len(self.merged_pairs),
            "params": self.params.to_json_dict(),
            "schema_version": CLUSTERS_SCHEMA_VERSION,
            "window": window,
            "wordless_record_ids": list(self.wordless_ids),
        }


def cluster_records(
    records: Sequence[Record],
    *,
    scores: Mapping[str, int],
    params: ClusterParams,
) -> ClusterOutcome:
    """Partition `records` into near-duplicate clusters.

    `scores` picks representatives and may be empty; a record with no score is
    scored zero rather than being treated as absent, because "not interesting"
    and "not scored" both mean "do not prefer this one".

    Raises:
        ClusterError: no records, or two records sharing an id.
    """
    if not records:
        raise ClusterError(
            "there are no records to cluster. Run `loghog ingest` first, or check "
            "the window name."
        )
    shingle_sets: dict[str, frozenset[str]] = {}
    for record in records:
        if record.record_id in shingle_sets:
            raise ClusterError(
                f"record id {record.record_id!r} appears twice in this window. Clustering "
                "would put one record in two clusters."
            )
        shingle_sets[record.record_id] = shingles(
            record.input_text, size=params.shingle_words
        )

    wordless = tuple(sorted(rid for rid, shingle in shingle_sets.items() if not shingle))
    hasher = MinHasher.create(permutations=params.permutations, seed=params.seed)
    signatures = {
        record_id: hasher.signature(shingle_set)
        for record_id, shingle_set in sorted(shingle_sets.items())
        if shingle_set
    }

    candidates = candidate_pairs(signatures, bands=params.bands)
    merged: set[tuple[str, str]] = set()
    links: dict[tuple[str, str], float] = {}
    for left, right in sorted(candidates):
        similarity = jaccard(shingle_sets[left], shingle_sets[right])
        if similarity >= params.threshold:
            merged.add((left, right))
            links[(left, right)] = similarity

    finder = UnionFind(sorted(shingle_sets))
    for left, right in sorted(merged):
        finder.union(left, right)

    clusters = _label(finder.groups(), scores=scores, links=links)
    return ClusterOutcome(
        params=params,
        clusters=clusters,
        merged_pairs=frozenset(merged),
        comparisons=len(candidates),
        wordless_ids=wordless,
    )


def _label(
    groups: list[list[str]],
    *,
    scores: Mapping[str, int],
    links: Mapping[tuple[str, str], float],
) -> tuple[Cluster, ...]:
    """Order the groups, name them, and pick each one's representative.

    Ordered by descending size and then by representative id, so a report reads
    biggest-first and two runs over one window agree on every label.
    """
    described = []
    for members in groups:
        representative = min(members, key=lambda rid: (-scores.get(rid, 0), rid))
        inside = [
            similarity
            for (left, right), similarity in links.items()
            if left in members and right in members
        ]
        described.append((members, representative, min(inside) if inside else None))
    described.sort(key=lambda entry: (-len(entry[0]), entry[1]))
    return tuple(
        Cluster(
            cluster_id=f"c-{index:04d}",
            representative_id=representative,
            member_ids=tuple(members),
            min_link_jaccard=weakest,
        )
        for index, (members, representative, weakest) in enumerate(described, start=1)
    )
