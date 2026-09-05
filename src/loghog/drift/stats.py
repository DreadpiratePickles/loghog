"""Two statistics for comparing windows: one written here, one borrowed.

**The Kolmogorov-Smirnov statistic** is written here. It is the largest vertical
gap between two empirical distribution functions — thirty lines of pure Python
over two sorted lists — and a dependency for thirty lines is a dependency for
thirty lines. It is reported as a *statistic*, not a p-value: this tool compares
two windows chosen by a person, which is not a sampling design a p-value means
anything under, and 0.62 with "inputs got longer" beside it is the honest thing
to publish.

**The Wilson interval** is not written here. It is imported from project 1's
`compare`, which already has it, already tests it, and already uses it for
exactly this purpose. A coverage figure computed by two implementations of one
formula is a disagreement waiting to happen in the one place nobody would think
to look.
"""

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from regression_detect.compare import wilson_interval

from loghog.errors import DriftError

__all__ = ["RateComparison", "compare_rates", "ks_statistic", "median", "wilson_interval"]


def ks_statistic(earlier: Sequence[int], later: Sequence[int]) -> float:
    """The two-sample KS statistic: the largest gap between the two curves.

    Raises:
        DriftError: either sample is empty. A distribution shift against nothing
            is not a number.
    """
    if not earlier or not later:
        raise DriftError("a distribution shift needs two non-empty samples; one is empty")
    left, right = sorted(earlier), sorted(later)
    largest = 0.0
    for value in sorted(set(left) | set(right)):
        gap = abs(bisect_right(left, value) / len(left) - bisect_right(right, value) / len(right))
        largest = max(largest, gap)
    return largest


def median(values: Sequence[int]) -> float:
    """The middle observation, averaging the two middles for an even count.

    Raises:
        DriftError: no values.
    """
    if not values:
        raise DriftError("a median over no values is not a number")
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2


@dataclass(frozen=True)
class RateComparison:
    """One rate in two windows, each with its interval, and the difference."""

    name: str
    earlier_count: int
    earlier_total: int
    later_count: int
    later_total: int
    earlier_low: float
    earlier_high: float
    later_low: float
    later_high: float

    @property
    def earlier_rate(self) -> float:
        return self.earlier_count / self.earlier_total

    @property
    def later_rate(self) -> float:
        return self.later_count / self.later_total

    @property
    def delta(self) -> float:
        return self.later_rate - self.earlier_rate

    @property
    def separated(self) -> bool:
        """Whether the two intervals do not overlap.

        Deliberately not called "significant". Non-overlapping Wilson intervals
        are a conservative screen and not a hypothesis test, and naming it one
        would be a claim this tool has not earned.
        """
        return self.later_low > self.earlier_high or self.earlier_low > self.later_high

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "delta": self.delta,
            "earlier": {
                "count": self.earlier_count,
                "high": self.earlier_high,
                "low": self.earlier_low,
                "rate": self.earlier_rate,
                "total": self.earlier_total,
            },
            "later": {
                "count": self.later_count,
                "high": self.later_high,
                "low": self.later_low,
                "rate": self.later_rate,
                "total": self.later_total,
            },
            "name": self.name,
            "separated": self.separated,
        }


def compare_rates(
    *, earlier: tuple[int, int], later: tuple[int, int], name: str = "rate"
) -> RateComparison:
    """Two counts out of two totals, each with a Wilson interval.

    Raises:
        DriftError: a window with no records, or more occurrences than records.
    """
    for label, (count, total) in (("earlier", earlier), ("later", later)):
        if total < 1:
            raise DriftError(f"the {label} window holds no records, so it has no rate")
        if count > total:
            raise DriftError(
                f"the {label} window reports more occurrences ({count}) than records ({total})"
            )
    earlier_low, earlier_high = wilson_interval(earlier[0], earlier[1])
    later_low, later_high = wilson_interval(later[0], later[1])
    return RateComparison(
        name=name,
        earlier_count=earlier[0],
        earlier_total=earlier[1],
        later_count=later[0],
        later_total=later[1],
        earlier_low=earlier_low,
        earlier_high=earlier_high,
        later_low=later_low,
        later_high=later_high,
    )
