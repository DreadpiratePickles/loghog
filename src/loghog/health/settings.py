"""`[health]`: what counts as a near-neighbour, and how long the to-mine list is.

**One threshold, not two.** Coverage asks whether a cluster in the traffic has a
golden case near it; staleness asks whether a golden case has traffic near it.
They are the same relation read from both ends, so they share the number — two
would let a report say a cluster is covered by a case that is itself stale
against that cluster, which is not a finding, it is a contradiction.

Deliberately separate from `[cluster] jaccard_threshold` all the same. Merging
two records into one case is a stricter claim than noticing a case is about the
same subject as some traffic, and one number for both would tie two unrelated
arguments together.
"""

from dataclasses import dataclass
from typing import Any

from loghog.config_values import reject_unknown, require_fraction, require_positive_int

HEALTH_KEYS = frozenset({"neighbour_jaccard", "max_recommendations"})


@dataclass(frozen=True)
class HealthSettings:
    """Everything stage 08 reads from configuration, already validated."""

    neighbour_jaccard: float
    max_recommendations: int

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "max_recommendations": self.max_recommendations,
            "neighbour_jaccard": self.neighbour_jaccard,
        }


def load_health_settings(table: dict[str, Any]) -> HealthSettings:
    """Validate `[health]`.

    Raises:
        ConfigFileError: an unknown key, a missing key, a threshold that is not
            a fraction, or a recommendation list of length zero.
    """
    reject_unknown(table, allowed=HEALTH_KEYS, what="key in [health]")
    return HealthSettings(
        neighbour_jaccard=require_fraction(table, "neighbour_jaccard"),
        max_recommendations=require_positive_int(table, "max_recommendations"),
    )
