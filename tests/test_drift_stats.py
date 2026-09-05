"""The statistics a drift report is made of, on their own.

Two of them are written here and one is borrowed. The Kolmogorov-Smirnov
statistic is thirty lines of pure Python and a dependency for it would be a
dependency for thirty lines. The Wilson interval is **not** rewritten: it comes
from project 1's `compare`, because a coverage figure computed by two different
implementations of one formula is a disagreement waiting to happen in the one
place nobody would look.
"""

import pytest

from loghog.drift.stats import (
    RateComparison,
    compare_rates,
    ks_statistic,
    wilson_interval,
)
from loghog.errors import DriftError


def test_two_identical_samples_have_a_ks_statistic_of_zero():
    assert ks_statistic([1, 2, 3, 4], [1, 2, 3, 4]) == 0.0


def test_two_disjoint_samples_have_a_ks_statistic_of_one():
    assert ks_statistic([1, 2, 3], [10, 11, 12]) == 1.0


def test_the_ks_statistic_is_symmetric():
    left, right = [1, 2, 3, 9], [2, 3, 4, 5]
    assert ks_statistic(left, right) == ks_statistic(right, left)


def test_the_ks_statistic_is_the_largest_gap_between_the_two_curves():
    # A hand-checkable case: half of B sits above everything in A.
    assert ks_statistic([1, 2], [1, 2, 30, 40]) == pytest.approx(0.5)


def test_the_ks_statistic_ignores_the_order_of_each_sample():
    assert ks_statistic([3, 1, 2], [2, 1, 3]) == 0.0


def test_the_ks_statistic_is_between_zero_and_one():
    assert 0.0 <= ks_statistic([1, 5, 5, 9], [2, 2, 8]) <= 1.0


def test_a_ks_statistic_over_an_empty_sample_is_refused():
    with pytest.raises(DriftError, match="empty"):
        ks_statistic([], [1, 2, 3])


def test_the_wilson_interval_is_project_ones_and_not_a_second_copy():
    from regression_detect.compare import wilson_interval as theirs

    assert wilson_interval is theirs


def test_comparing_two_rates_gives_both_intervals_and_the_delta():
    comparison = compare_rates(earlier=(2, 100), later=(8, 100))
    assert isinstance(comparison, RateComparison)
    assert comparison.earlier_rate == pytest.approx(0.02)
    assert comparison.later_rate == pytest.approx(0.08)
    assert comparison.delta == pytest.approx(0.06)


def test_the_intervals_bracket_their_own_rates():
    comparison = compare_rates(earlier=(2, 100), later=(8, 100))
    assert comparison.earlier_low <= comparison.earlier_rate <= comparison.earlier_high
    assert comparison.later_low <= comparison.later_rate <= comparison.later_high


def test_intervals_that_do_not_overlap_are_reported_as_separated():
    # Not "significant". Non-overlapping Wilson intervals are a conservative
    # screen, not a test, and calling it one would be a claim this tool has not
    # earned.
    assert compare_rates(earlier=(1, 500), later=(200, 500)).separated is True
    assert compare_rates(earlier=(45, 100), later=(55, 100)).separated is False


def test_a_rate_over_no_samples_is_refused():
    with pytest.raises(DriftError, match="no records"):
        compare_rates(earlier=(0, 0), later=(1, 10))


def test_more_successes_than_samples_is_refused():
    with pytest.raises(DriftError, match="more"):
        compare_rates(earlier=(11, 10), later=(1, 10))
