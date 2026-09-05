"""Normalisation, word shingles and Jaccard — the three functions clustering is made of.

Every one of them is checkable by hand, which is the whole argument for not
using embeddings here: a reviewer can read a shingle set and say whether two
tickets should have matched.
"""

import pytest

from loghog.cluster.shingles import jaccard, normalise_for_shingles, shingles
from loghog.errors import ClusterError


def test_normalisation_lowercases_and_collapses_whitespace():
    assert normalise_for_shingles("The  Lamp\n FLICKERS") == "the lamp flickers"


def test_normalisation_strips_digits_because_an_order_number_is_not_the_complaint():
    # Two tickets about one bug differ by their order reference. Keeping the
    # digits would make every ticket its own cluster.
    assert normalise_for_shingles("order 1234 is late") == "order is late"


def test_normalisation_strips_redaction_tokens_because_a_token_is_not_a_word():
    # `[EMAIL_1]` and `[EMAIL_2]` are the same fact — "an address was here" —
    # and leaving the number in would split one cluster by which customer wrote.
    collapsed = normalise_for_shingles("write to [EMAIL_1] or [EMAIL_2]")
    assert collapsed == "write to [email] or [email]"


def test_normalisation_of_punctuation_leaves_words_joined_by_single_spaces():
    assert normalise_for_shingles("  a   b  ") == "a b"


def test_a_text_of_exactly_the_shingle_length_yields_one_shingle():
    assert shingles("a b c d e", size=5) == frozenset({"a b c d e"})


def test_shingles_slide_by_one_word():
    assert shingles("a b c d e f", size=5) == frozenset({"a b c d e", "b c d e f"})


def test_a_text_shorter_than_the_window_becomes_one_shingle_of_the_whole_text():
    # The fallback the stage contract promises: too short to shingle means
    # compared by exact equality, and this is how that falls out of one rule
    # rather than out of a second code path.
    assert shingles("lamp flickers", size=5) == frozenset({"lamp flickers"})


def test_two_short_texts_match_only_when_identical():
    left = shingles("lamp flickers", size=5)
    right = shingles("lamp buzzes", size=5)
    assert jaccard(left, left) == 1.0
    assert jaccard(left, right) == 0.0


def test_a_text_with_no_words_after_normalisation_has_no_shingles():
    # "12345" is digits and nothing else. An empty shingle set is evidence of
    # nothing, and §33 is about why that must not cluster with another absence.
    assert shingles("12345", size=5) == frozenset()
    assert shingles("   ", size=5) == frozenset()


def test_jaccard_of_two_empty_sets_is_zero_not_one():
    assert jaccard(frozenset(), frozenset()) == 0.0


def test_jaccard_with_one_empty_set_is_zero():
    assert jaccard(frozenset({"a b c d e"}), frozenset()) == 0.0


def test_jaccard_is_intersection_over_union():
    left = frozenset({"a", "b", "c"})
    right = frozenset({"b", "c", "d"})
    assert jaccard(left, right) == pytest.approx(2 / 4)


def test_jaccard_is_symmetric():
    left = shingles("the lamp flickers above half brightness", size=5)
    right = shingles("the lamp flickers when the brightness is high", size=5)
    assert jaccard(left, right) == jaccard(right, left)


def test_a_paraphrase_scores_above_two_unrelated_complaints():
    base = shingles("the desk lamp flickers whenever the brightness is above half", size=5)
    near = shingles("the desk lamp flickers whenever the brightness is over half", size=5)
    far = shingles("the courier never rang the bell and left with the parcel", size=5)
    assert jaccard(base, near) > jaccard(base, far)


def test_a_shingle_size_below_one_is_refused():
    with pytest.raises(ClusterError, match="at least 1"):
        shingles("a b c", size=0)


def test_normalisation_refuses_a_non_string():
    with pytest.raises(ClusterError, match="string"):
        normalise_for_shingles(None)


def test_shingling_is_deterministic_across_calls():
    text = "the lamp flickers whenever the brightness is above about half"
    assert shingles(text, size=5) == shingles(text, size=5)
