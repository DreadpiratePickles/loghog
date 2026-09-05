"""`[select]` and `[select.quotas]`: how big the shortlist is, and what it is made of.

A quota is the only defence against the failure mode this stage exists to
prevent. Sorting by score and taking the top forty produces a dataset made
entirely of the loudest failure mode of that week, which then measures one
thing — and measures it forty times.

Every stratum must be named, including `ordinary`, and an absent one is refused
rather than defaulted to zero. A silent zero is a cap nobody argued about, and
the whole point of `selection.md` is that no cap is silent.
"""

from dataclasses import dataclass
from typing import Any

from loghog.config_values import reject_unknown, require_exactly, require_int, require_positive_int
from loghog.errors import ConfigFileError
from loghog.score.settings import SIGNAL_NAMES

ORDINARY = "ordinary"
"""The stratum for a record that fired no signal at all.

It has a quota like every other stratum, and the quota is usually small and
never zero by accident: an eval set made only of failures cannot tell you that
you broke the ordinary case."""

STRATA: tuple[str, ...] = (*SIGNAL_NAMES, ORDINARY)

SELECT_KEYS = frozenset({"max_candidates", "max_per_cluster", "quotas"})


@dataclass(frozen=True)
class SelectSettings:
    """The caps a shortlist is built under."""

    max_candidates: int
    max_per_cluster: int
    quotas: dict[str, int]

    def quota(self, stratum: str) -> int:
        """The cap for one stratum.

        Raises:
            ConfigFileError: an unknown stratum, which means the signal
                registry and the configuration have drifted apart.
        """
        if stratum not in self.quotas:
            raise ConfigFileError(f"no quota configured for stratum {stratum!r}")
        return self.quotas[stratum]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "max_candidates": self.max_candidates,
            "max_per_cluster": self.max_per_cluster,
            "quotas": dict(sorted(self.quotas.items())),
        }


def load_select_settings(table: dict[str, Any]) -> SelectSettings:
    """Validate `[select]` and its nested `[select.quotas]`.

    Raises:
        ConfigFileError: an unknown key, a missing stratum, or a cap below one.
    """
    reject_unknown(table, allowed=SELECT_KEYS, what="key in [select]")
    quotas_table = table.get("quotas")
    if not isinstance(quotas_table, dict):
        raise ConfigFileError("[select.quotas] is missing, and every stratum needs a quota")
    require_exactly(quotas_table, names=STRATA, what="quota in [select.quotas]")
    # Zero is allowed here and refused for weights, and the asymmetry is the
    # point: a zero quota says "never take this kind", which is a decision. A
    # zero weight says "this evidence is worth nothing", which is a signal that
    # should have been deleted instead.
    quotas = {name: require_int(quotas_table, name, minimum=0) for name in STRATA}
    return SelectSettings(
        max_candidates=require_positive_int(table, "max_candidates"),
        max_per_cluster=require_positive_int(table, "max_per_cluster"),
        quotas=quotas,
    )
