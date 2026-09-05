"""`[drift]`: the one threshold comparing two windows needs.

A cluster in the newer window is *new* when nothing in the older window is
similar to it. "Similar" needs a number, and it is deliberately a different
number from `[cluster] jaccard_threshold`: merging two records into one case is
a stricter claim than noticing that a subject has been seen before, and using
one threshold for both would tie two unrelated arguments together.
"""

from dataclasses import dataclass
from typing import Any

from loghog.config_values import reject_unknown, require_fraction

DRIFT_KEYS = frozenset({"novel_cluster_jaccard"})


@dataclass(frozen=True)
class DriftSettings:
    """What counts as a subject the older window had never seen."""

    novel_cluster_jaccard: float

    def to_json_dict(self) -> dict[str, Any]:
        return {"novel_cluster_jaccard": self.novel_cluster_jaccard}


def load_drift_settings(table: dict[str, Any]) -> DriftSettings:
    """Validate the `[drift]` section.

    Raises:
        ConfigFileError: an unknown key, or a threshold outside 0 to 1.
    """
    reject_unknown(table, allowed=DRIFT_KEYS, what="key in [drift]")
    return DriftSettings(novel_cluster_jaccard=require_fraction(table, "novel_cluster_jaccard"))
