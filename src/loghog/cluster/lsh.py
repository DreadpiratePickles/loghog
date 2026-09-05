"""Banding, and the union-find that turns verified pairs into clusters.

Locality-sensitive hashing is a *blocking* step and nothing more. Splitting a
signature into `b` bands of `r` rows and bucketing by whole bands makes two
records candidates when they agree on every row of at least one band, which
happens with probability `1 - (1 - s^r)^b` for similarity `s` — a curve that is
steep around `(1/b)^(1/r)`. That curve is a *probability*, and a threshold
somebody has to argue with should not be one. So banding only proposes; the
caller verifies each proposed pair against the exact Jaccard and merges only
what clears the configured threshold.

The consequence, which is worth stating rather than discovering: precision comes
out exactly 1 against a brute-force comparison, and recall is where banding
costs something. The suite measures both.

Union-find gives single-linkage clustering, which is transitive: A merges with
B, B with C, and A and C end up together even if their own similarity is below
the threshold. That is a real property of this design, not a bug — a chain of
paraphrases is one complaint — but it is the reason a cluster reports the
*weakest* link that built it rather than an average.
"""

from collections.abc import Iterable, Mapping

from loghog.errors import ClusterError


def band_buckets(
    signatures: Mapping[str, tuple[int, ...]], *, bands: int
) -> dict[tuple[int, tuple[int, ...]], list[str]]:
    """Group record ids by `(band index, that band's rows)`.

    Raises:
        ClusterError: `bands` is below one, does not divide the signature
            width, or the signatures are not all the same width. A remainder
            would leave rows no band ever reads, which is recall thrown away
            silently.
    """
    if isinstance(bands, bool) or not isinstance(bands, int) or bands < 1:
        raise ClusterError(f"there is at least 1 band, got {bands!r}")
    if not signatures:
        return {}
    widths = {len(signature) for signature in signatures.values()}
    if len(widths) != 1:
        raise ClusterError(
            f"signatures of width {sorted(widths)} cannot be banded together; "
            "they came from different permutation families."
        )
    width = widths.pop()
    if width % bands:
        raise ClusterError(
            f"{bands} band(s) do not divide a signature of {width} hash(es). A remainder "
            "leaves rows no band ever reads, which loses recall without saying so."
        )
    rows = width // bands
    buckets: dict[tuple[int, tuple[int, ...]], list[str]] = {}
    for record_id in sorted(signatures):
        signature = signatures[record_id]
        for band in range(bands):
            key = (band, signature[band * rows : (band + 1) * rows])
            buckets.setdefault(key, []).append(record_id)
    return buckets


def candidate_pairs(
    signatures: Mapping[str, tuple[int, ...]], *, bands: int
) -> set[tuple[str, str]]:
    """Every pair sharing at least one band, each as a sorted tuple."""
    pairs: set[tuple[str, str]] = set()
    for members in band_buckets(signatures, bands=bands).values():
        if len(members) < 2:
            continue
        for index, left in enumerate(members):
            for right in members[index + 1 :]:
                pairs.add((left, right) if left < right else (right, left))
    return pairs


class UnionFind:
    """Disjoint sets over a fixed population, with deterministic output."""

    def __init__(self, elements: Iterable[str]) -> None:
        self._parent: dict[str, str] = {}
        for element in elements:
            if element in self._parent:
                raise ClusterError(f"{element!r} was given to union-find twice")
            self._parent[element] = element

    def find(self, element: str) -> str:
        """The representative of `element`'s set, with path compression."""
        if element not in self._parent:
            raise ClusterError(f"unknown element {element!r}")
        root = element
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[element] != root:
            self._parent[element], element = root, self._parent[element]
        return root

    def union(self, left: str, right: str) -> None:
        """Merge the two sets, keeping the lexicographically smaller root.

        Union by *name* rather than by rank or size. Rank would make the result
        depend on the order the pairs arrived in, and the whole point of this
        module is that shuffling a window does not change its partition.
        """
        left_root, right_root = self.find(left), self.find(right)
        if left_root == right_root:
            return
        smaller, larger = sorted((left_root, right_root))
        self._parent[larger] = smaller

    def groups(self) -> list[list[str]]:
        """The sets, each sorted, ordered by their first element."""
        found: dict[str, list[str]] = {}
        for element in sorted(self._parent):
            found.setdefault(self.find(element), []).append(element)
        return [members for _, members in sorted(found.items())]
