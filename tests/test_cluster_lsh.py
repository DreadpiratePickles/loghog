"""Banding and union-find: how candidate pairs are found without comparing everything.

LSH is a *blocking* step. It decides which pairs are worth an exact comparison,
and the exact comparison decides which pairs are near-duplicates. Getting that
division right is the difference between a threshold somebody can argue with and
a threshold buried in a probability.
"""

import pytest

from loghog.cluster.lsh import UnionFind, band_buckets, candidate_pairs
from loghog.errors import ClusterError


def test_bands_must_divide_the_signature_width():
    # 64 hashes in 7 bands leaves a remainder, and a remainder means some rows
    # are never used — a silent loss of recall.
    with pytest.raises(ClusterError, match="divide"):
        band_buckets({"a": tuple(range(64))}, bands=7)


def test_bands_must_be_at_least_one():
    with pytest.raises(ClusterError, match="at least 1"):
        band_buckets({"a": tuple(range(64))}, bands=0)


def test_signatures_of_differing_widths_are_refused():
    with pytest.raises(ClusterError, match="width"):
        band_buckets({"a": (1, 2, 3, 4), "b": (1, 2)}, bands=2)


def test_identical_signatures_share_every_bucket():
    signature = tuple(range(8))
    buckets = band_buckets({"a": signature, "b": signature}, bands=4)
    assert all(sorted(members) == ["a", "b"] for members in buckets.values())
    assert len(buckets) == 4


def test_signatures_agreeing_in_one_band_share_that_bucket_only():
    left = (1, 2, 3, 4, 5, 6, 7, 8)
    right = (1, 2, 99, 99, 99, 99, 99, 99)
    buckets = band_buckets({"a": left, "b": right}, bands=4)
    shared = [key for key, members in buckets.items() if len(members) > 1]
    assert len(shared) == 1


def test_candidate_pairs_are_sorted_and_unique():
    signature = (1, 2, 3, 4)
    pairs = candidate_pairs({"b": signature, "a": signature, "c": signature}, bands=2)
    assert pairs == {("a", "b"), ("a", "c"), ("b", "c")}


def test_candidate_pairs_of_one_record_are_empty():
    assert candidate_pairs({"only": (1, 2, 3, 4)}, bands=2) == set()


def test_candidate_pairs_do_not_depend_on_insertion_order():
    left, right = (1, 2, 3, 4), (1, 2, 9, 9)
    forward = candidate_pairs({"a": left, "b": right}, bands=2)
    backward = candidate_pairs({"b": right, "a": left}, bands=2)
    assert forward == backward == {("a", "b")}


# --- union-find -------------------------------------------------------------


def test_union_find_starts_with_every_element_alone():
    finder = UnionFind(["a", "b", "c"])
    assert finder.groups() == [["a"], ["b"], ["c"]]


def test_union_find_merges_transitively():
    finder = UnionFind(["a", "b", "c", "d"])
    finder.union("a", "b")
    finder.union("b", "c")
    assert finder.groups() == [["a", "b", "c"], ["d"]]


def test_union_find_groups_are_sorted_within_and_between():
    # Determinism is the whole point: the same corpus must produce the same
    # clusters in the same order however the pairs arrived.
    finder = UnionFind(["z", "m", "a"])
    finder.union("z", "a")
    assert finder.groups() == [["a", "z"], ["m"]]


def test_union_find_is_order_independent():
    first = UnionFind(["a", "b", "c"])
    for left, right in (("a", "b"), ("b", "c")):
        first.union(left, right)
    second = UnionFind(["a", "b", "c"])
    for left, right in (("b", "c"), ("a", "b")):
        second.union(left, right)
    assert first.groups() == second.groups()


def test_union_find_refuses_an_unknown_element():
    finder = UnionFind(["a"])
    with pytest.raises(ClusterError, match="unknown"):
        finder.union("a", "b")


def test_union_find_refuses_a_duplicate_element():
    with pytest.raises(ClusterError, match="twice"):
        UnionFind(["a", "a"])
