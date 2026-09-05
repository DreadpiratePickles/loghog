"""`loghog.toml`: the paths, the privacy switch, and the limits.

Strict on purpose. An unknown section or an unknown key is refused rather than
ignored, because the failure mode of a tolerant loader is the one that matters
here: `redakt = false` would be silently ignored and the operator would believe
redaction was off when it was on, or — far worse — the reverse.

The six analysis sections validate themselves. `[score]` knows the vocabulary of
signals, `[cluster]` knows that bands must divide permutations, `[select]` knows
the strata, `[label]` knows which model references `config.py` defines: each is
the section's own business and none of it belongs in a generic loader that would
have to import all six to know any of it.
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loghog.cluster.settings import CLUSTER_KEYS, ClusterParams, load_cluster_settings
from loghog.config_values import (
    reject_unknown,
    require_bool,
    require_positive_int,
    require_string_list,
    resolve_path,
)
from loghog.drift.settings import DRIFT_KEYS, DriftSettings, load_drift_settings
from loghog.errors import ConfigFileError
from loghog.health.settings import HEALTH_KEYS, HealthSettings, load_health_settings
from loghog.label.settings import LABEL_KEYS, LabelSettings, load_label_settings
from loghog.score.settings import SCORE_KEYS, ScoreSettings, load_score_settings
from loghog.select.settings import SELECT_KEYS, SelectSettings, load_select_settings

DEFAULT_CONFIG_NAME = "loghog.toml"

SCHEMA: dict[str, frozenset[str]] = {
    "paths": frozenset(
        {
            "records_dir",
            "mappings_dir",
            "selected_dir",
            "drift_dir",
            "goldens_dir",
            "health_dir",
        }
    ),
    "privacy": frozenset({"redact", "name_allowlist"}),
    "ingest": frozenset({"max_text_chars"}),
    "dedupe": frozenset({"dedupe"}),
    "score": SCORE_KEYS,
    "cluster": CLUSTER_KEYS,
    "select": SELECT_KEYS,
    "label": LABEL_KEYS,
    "health": HEALTH_KEYS,
    "drift": DRIFT_KEYS,
}

_NESTED_TABLES = {"score": ("weights",), "select": ("quotas",)}
"""Sections whose own loader validates a nested table, so the generic
unknown-key check must not reject the table itself."""


@dataclass(frozen=True)
class LoghogConfig:
    """Everything a run reads from the configuration file, already validated."""

    path: Path
    root: Path
    records_dir: Path
    mappings_dir: Path
    selected_dir: Path
    drift_dir: Path
    goldens_dir: Path
    health_dir: Path
    redact: bool
    name_allowlist: tuple[str, ...]
    max_text_chars: int
    dedupe: bool
    score: ScoreSettings
    cluster: ClusterParams
    select: SelectSettings
    label: LabelSettings
    health: HealthSettings
    drift: DriftSettings


def load_config(path: Path) -> LoghogConfig:
    """Read and validate `loghog.toml`.

    Raises:
        ConfigFileError: the file is absent, unparseable, or says something
            impossible. Every message names the key at fault.
    """
    path = Path(path)
    if not path.is_file():
        raise ConfigFileError(
            f"no configuration file at {path}. Copy the repository's {DEFAULT_CONFIG_NAME} "
            "or pass --config."
        )
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigFileError(f"{path} is not readable TOML: {exc}") from exc

    reject_unknown(raw, allowed=frozenset(SCHEMA), what="section")
    for section, allowed in SCHEMA.items():
        table = _section(raw, section, path)
        nested = _NESTED_TABLES.get(section, ())
        reject_unknown(
            {key: value for key, value in table.items() if key not in nested},
            allowed=allowed,
            what=f"key in [{section}]",
        )

    root = path.parent.resolve()
    paths = _section(raw, "paths", path)
    privacy = _section(raw, "privacy", path)
    ingest = _section(raw, "ingest", path)
    dedupe = _section(raw, "dedupe", path)

    return LoghogConfig(
        path=path,
        root=root,
        records_dir=resolve_path(paths, "records_dir", root=root),
        mappings_dir=resolve_path(paths, "mappings_dir", root=root),
        selected_dir=resolve_path(paths, "selected_dir", root=root),
        drift_dir=resolve_path(paths, "drift_dir", root=root),
        goldens_dir=resolve_path(paths, "goldens_dir", root=root),
        health_dir=resolve_path(paths, "health_dir", root=root),
        redact=require_bool(privacy, "redact"),
        name_allowlist=require_string_list(privacy, "name_allowlist"),
        max_text_chars=require_positive_int(ingest, "max_text_chars"),
        dedupe=require_bool(dedupe, "dedupe"),
        score=load_score_settings(_section(raw, "score", path)),
        cluster=load_cluster_settings(_section(raw, "cluster", path)),
        select=load_select_settings(_section(raw, "select", path)),
        label=load_label_settings(_section(raw, "label", path)),
        health=load_health_settings(_section(raw, "health", path)),
        drift=load_drift_settings(_section(raw, "drift", path)),
    )


def _section(raw: dict[str, Any], name: str, path: Path) -> dict[str, Any]:
    value = raw.get(name)
    if value is None:
        raise ConfigFileError(f"{path} has no [{name}] section")
    if not isinstance(value, dict):
        raise ConfigFileError(f"[{name}] must be a table, got {type(value).__name__}")
    return value


