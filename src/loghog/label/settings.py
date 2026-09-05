"""`[label]`: which model, how fast, and how many calls at most.

Three keys, and the first one carries the rule this repository has kept since
before it had a call site. `model_ref` names a **reference** — the name of an
environment variable that `loghog.config` defines — and never a model id. That
is checked here, when the file is read, rather than when the first call is
priced: a typo that resolved to a default would route a run to the wrong model
quietly, and a typo that resolved to nothing would do it at the worst moment.

`max_calls` is the budget, and it refuses rather than truncates. A stage that
silently labelled the first hundred of a hundred and forty candidates would
produce a dataset whose contents depend on a number nobody was shown.
"""

from dataclasses import dataclass
from typing import Any

from loghog.config import MODEL_ID_DEFAULTS
from loghog.config_values import (
    reject_unknown,
    require,
    require_int,
    require_positive_int,
)
from loghog.errors import ConfigFileError

LABEL_KEYS = frozenset({"model_ref", "min_interval_ms", "max_calls"})


@dataclass(frozen=True)
class LabelSettings:
    """Everything stage 06 reads from configuration, already validated."""

    model_ref: str
    min_interval_ms: int
    max_calls: int

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "max_calls": self.max_calls,
            "min_interval_ms": self.min_interval_ms,
            "model_ref": self.model_ref,
        }


def load_label_settings(table: dict[str, Any]) -> LabelSettings:
    """Validate `[label]`.

    Raises:
        ConfigFileError: an unknown key, a missing key, a `model_ref` that is
            not a reference `loghog.config` defines, a negative interval, or a
            call budget below one.
    """
    reject_unknown(table, allowed=LABEL_KEYS, what="key in [label]")
    model_ref = require(table, "model_ref")
    if not isinstance(model_ref, str) or model_ref not in MODEL_ID_DEFAULTS:
        known = ", ".join(sorted(MODEL_ID_DEFAULTS))
        raise ConfigFileError(
            f"model_ref {model_ref!r} is not a model reference this build defines. "
            f"Known references: {known}. Configuration names a reference and "
            "src/loghog/config.py resolves it; a vendor string here is the thing that "
            "module exists to prevent."
        )
    return LabelSettings(
        model_ref=model_ref,
        min_interval_ms=require_int(table, "min_interval_ms", minimum=0),
        max_calls=require_positive_int(table, "max_calls"),
    )
