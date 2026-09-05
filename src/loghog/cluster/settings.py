"""`[cluster]`: the five numbers that decide what counts as the same complaint.

All five are in a reviewed file rather than in code, because every one of them
is an argument somebody could reasonably lose. `jaccard_threshold` in
particular: at 0.4 two different bugs in one feature merge, at 0.8 a paraphrase
becomes its own case, and the right answer depends on how the people writing to
you write.
"""

from dataclasses import dataclass
from typing import Any

from loghog.config_values import (
    reject_unknown,
    require_fraction,
    require_int,
    require_positive_int,
)
from loghog.errors import ConfigFileError

CLUSTER_KEYS = frozenset({"shingle_words", "permutations", "bands", "seed", "jaccard_threshold"})


@dataclass(frozen=True)
class ClusterParams:
    """Everything near-duplicate detection needs, already validated."""

    shingle_words: int
    permutations: int
    bands: int
    seed: int
    threshold: float

    @property
    def rows_per_band(self) -> int:
        return self.permutations // self.bands

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "bands": self.bands,
            "jaccard_threshold": self.threshold,
            "permutations": self.permutations,
            "rows_per_band": self.rows_per_band,
            "seed": self.seed,
            "shingle_words": self.shingle_words,
        }


def load_cluster_settings(table: dict[str, Any]) -> ClusterParams:
    """Validate the `[cluster]` section.

    Raises:
        ConfigFileError: an unknown key, a number out of range, or a band count
            that does not divide the signature width.
    """
    reject_unknown(table, allowed=CLUSTER_KEYS, what="key in [cluster]")
    permutations = require_positive_int(table, "permutations")
    bands = require_positive_int(table, "bands")
    if permutations % bands:
        raise ConfigFileError(
            f"bands ({bands}) must divide permutations ({permutations}). A remainder leaves "
            "rows no band ever reads, which loses recall without saying so."
        )
    return ClusterParams(
        shingle_words=require_positive_int(table, "shingle_words"),
        permutations=permutations,
        bands=bands,
        seed=require_int(table, "seed", minimum=0),
        threshold=require_fraction(table, "jaccard_threshold"),
    )
