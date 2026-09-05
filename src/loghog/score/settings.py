"""`[score]` and `[score.weights]`: what counts as interesting, and how much.

The list of signals is code, because each one is a function. The *weight* on
each is configuration, because each one is an argument — and an argument about
whether a refusal matters more than a slow answer is exactly the kind of thing
that should be a diff somebody reviews rather than a constant somebody changed
while fixing something else.

A weight is an integer. Not because arithmetic demands it, but because a score
built out of integers can be recomputed in your head from the signal list beside
it, and a ranking nobody can recompute is a ranking nobody can argue with.
"""

from dataclasses import dataclass
from typing import Any

from loghog.config_values import (
    reject_unknown,
    require_exactly,
    require_fraction,
    require_int,
    require_percentile,
    require_positive_int,
    require_vocabulary,
)
from loghog.errors import ConfigFileError

SIGNAL_NAMES: tuple[str, ...] = (
    "error",
    "judge_failure",
    "negative_feedback",
    "feedback_conflict",
    "version_disagreement",
    "injection_pattern",
    "refusal_pattern",
    "format_violation",
    "novelty",
    "latency_outlier",
    "length_outlier",
    "non_ascii_ratio",
    "tiny_input",
)
"""Every signal, in the order a report lists them: loudest evidence first.

The order is not a priority for scoring — a score is a sum and does not care —
but it is the order a stratum is chosen in when a record fires several signals,
and a stable order there is what makes selection reproducible.
"""

SCORE_KEYS = frozenset(
    {
        "tiny_input_chars",
        "non_ascii_threshold",
        "novelty_max_jaccard",
        "outlier_percentile",
        "min_outlier_sample",
        "negative_feedback_words",
        "positive_feedback_words",
        "weights",
    }
)


@dataclass(frozen=True)
class ScoreSettings:
    """Everything scoring reads from configuration, already validated."""

    weights: dict[str, int]
    tiny_input_chars: int
    non_ascii_threshold: float
    novelty_max_jaccard: float
    outlier_percentile: int
    min_outlier_sample: int
    negative_feedback_words: frozenset[str]
    positive_feedback_words: frozenset[str]

    def weight(self, signal: str) -> int:
        """The weight for one signal.

        Raises:
            ConfigFileError: an unknown signal name, which can only mean the
                registry and the configuration have drifted apart.
        """
        if signal not in self.weights:
            raise ConfigFileError(f"no weight configured for signal {signal!r}")
        return self.weights[signal]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "min_outlier_sample": self.min_outlier_sample,
            "non_ascii_threshold": self.non_ascii_threshold,
            "novelty_max_jaccard": self.novelty_max_jaccard,
            "outlier_percentile": self.outlier_percentile,
            "tiny_input_chars": self.tiny_input_chars,
            "weights": dict(sorted(self.weights.items())),
        }


def load_score_settings(table: dict[str, Any]) -> ScoreSettings:
    """Validate `[score]` and its nested `[score.weights]`.

    Raises:
        ConfigFileError: an unknown key, a missing weight, a weight that is not
            a non-negative integer, weights that are all zero, or a word that
            means both positive and negative feedback at once.
    """
    reject_unknown(table, allowed=SCORE_KEYS, what="key in [score]")
    weights_table = table.get("weights")
    if not isinstance(weights_table, dict):
        raise ConfigFileError("[score.weights] is missing, and every signal needs a weight")
    require_exactly(weights_table, names=SIGNAL_NAMES, what="weight in [score.weights]")
    weights = {
        name: require_int(weights_table, name, minimum=0) for name in SIGNAL_NAMES
    }
    if not any(weights.values()):
        raise ConfigFileError(
            "every weight is zero, so every record scores zero and selection would be "
            "alphabetical. Turn a signal off by giving its stratum a quota of 0 instead."
        )

    negative = require_vocabulary(table, "negative_feedback_words")
    positive = require_vocabulary(table, "positive_feedback_words")
    both = sorted(negative & positive)
    if both:
        raise ConfigFileError(
            f"{', '.join(both)} appear(s) in both positive_feedback_words and "
            "negative_feedback_words. "
            "A word that means both would make feedback_conflict fire on every record that "
            "had any feedback at all."
        )
    return ScoreSettings(
        weights=weights,
        tiny_input_chars=require_positive_int(table, "tiny_input_chars"),
        non_ascii_threshold=require_fraction(table, "non_ascii_threshold"),
        novelty_max_jaccard=require_fraction(table, "novelty_max_jaccard"),
        outlier_percentile=require_percentile(table, "outlier_percentile"),
        min_outlier_sample=require_positive_int(table, "min_outlier_sample"),
        negative_feedback_words=negative,
        positive_feedback_words=positive,
    )
