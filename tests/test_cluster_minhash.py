"""MinHash: a fixed-width signature whose collision rate estimates Jaccard.

The property worth testing is not "the numbers are these numbers" — it is that
the same corpus gives the same signatures on any machine, in any process, and
that the estimate tracks the exact answer. Python's built-in `hash()` is salted
per process and would fail the first of those silently, which is why the base
hash here is BLAKE2b.
"""

import os
import subprocess
import sys

import pytest

from loghog.cluster.minhash import MinHasher, estimated_jaccard
from loghog.cluster.shingles import jaccard, shingles
from loghog.errors import ClusterError


def hasher(permutations: int = 64, seed: int = 1729) -> MinHasher:
    return MinHasher.create(permutations=permutations, seed=seed)


def test_a_signature_has_one_entry_per_permutation():
    signature = hasher(permutations=64).signature(shingles("a b c d e f g", size=5))
    assert len(signature) == 64


def test_the_same_set_gives_the_same_signature():
    left = hasher().signature(shingles("the lamp flickers above half", size=3))
    right = hasher().signature(shingles("the lamp flickers above half", size=3))
    assert left == right


def test_the_signature_does_not_depend_on_insertion_order():
    # A frozenset has no order, but the implementation iterates it — and an
    # implementation that accumulated rather than minimised would drift.
    forward = hasher().signature(frozenset({"a b", "c d", "e f"}))
    backward = hasher().signature(frozenset({"e f", "c d", "a b"}))
    assert forward == backward


def test_two_seeds_give_different_permutations():
    text = shingles("the lamp flickers whenever the brightness is high", size=5)
    assert hasher(seed=1).signature(text) != hasher(seed=2).signature(text)


def test_identical_sets_estimate_a_jaccard_of_one():
    signature = hasher().signature(shingles("a b c d e f g h", size=5))
    assert estimated_jaccard(signature, signature) == 1.0


def test_disjoint_sets_estimate_close_to_zero():
    left = hasher().signature(frozenset({"a a a", "b b b"}))
    right = hasher().signature(frozenset({"y y y", "z z z"}))
    assert estimated_jaccard(left, right) < 0.2


def test_the_estimate_tracks_the_exact_jaccard_within_the_error_of_64_hashes():
    # The standard error of a k-hash MinHash is 1/sqrt(k); with 64 hashes that
    # is 0.125, so 0.2 is a floor the estimator should clear comfortably.
    left = shingles(
        "the desk lamp flickers whenever the brightness goes above about half", size=3
    )
    right = shingles(
        "the desk lamp flickers whenever the brightness goes above roughly half", size=3
    )
    exact = jaccard(left, right)
    estimate = estimated_jaccard(hasher().signature(left), hasher().signature(right))
    assert abs(estimate - exact) < 0.2


def test_an_empty_set_has_no_signature():
    # An empty shingle set is evidence of nothing. Giving it a signature would
    # let two absences land in one LSH bucket and cluster.
    with pytest.raises(ClusterError, match="empty"):
        hasher().signature(frozenset())


def test_permutations_must_be_positive():
    with pytest.raises(ClusterError, match="at least 1"):
        MinHasher.create(permutations=0, seed=1)


def test_comparing_signatures_of_different_widths_is_refused():
    with pytest.raises(ClusterError, match="width"):
        estimated_jaccard((1, 2, 3), (1, 2))


def test_the_signature_is_stable_across_processes():
    # The real property. `hash()` is salted per interpreter, so an
    # implementation built on it passes every test above and silently
    # reclusters a corpus on the next run.
    program = (
        "from loghog.cluster.minhash import MinHasher;"
        "from loghog.cluster.shingles import shingles;"
        "print(MinHasher.create(permutations=8, seed=7)"
        ".signature(shingles('the lamp flickers above half brightness', size=3)))"
    )
    first = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PYTHONHASHSEED": "0"},
    )
    second = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PYTHONHASHSEED": "12345"},
    )
    assert first.stdout == second.stdout
    assert first.stdout.strip()
