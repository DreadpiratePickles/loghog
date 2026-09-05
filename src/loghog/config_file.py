"""`loghog.toml`: the paths, the privacy switch, and the limits.

Strict on purpose. An unknown section or an unknown key is refused rather than
ignored, because the failure mode of a tolerant loader is the one that matters
here: `redakt = false` would be silently ignored and the operator would believe
redaction was off when it was on, or — far worse — the reverse.
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loghog.errors import ConfigFileError

DEFAULT_CONFIG_NAME = "loghog.toml"

SCHEMA: dict[str, frozenset[str]] = {
    "paths": frozenset({"records_dir", "mappings_dir"}),
    "privacy": frozenset({"redact", "name_allowlist"}),
    "ingest": frozenset({"max_text_chars"}),
    "dedupe": frozenset({"dedupe"}),
}


@dataclass(frozen=True)
class LoghogConfig:
    """Everything a run reads from the configuration file, already validated."""

    path: Path
    root: Path
    records_dir: Path
    mappings_dir: Path
    redact: bool
    name_allowlist: tuple[str, ...]
    max_text_chars: int
    dedupe: bool


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

    _reject_unknown(raw, allowed=frozenset(SCHEMA), what="section")
    for section, allowed in SCHEMA.items():
        _reject_unknown(_section(raw, section, path), allowed=allowed, what=f"key in [{section}]")

    root = path.parent.resolve()
    paths = _section(raw, "paths", path)
    privacy = _section(raw, "privacy", path)
    ingest = _section(raw, "ingest", path)
    dedupe = _section(raw, "dedupe", path)

    return LoghogConfig(
        path=path,
        root=root,
        records_dir=_resolve_path(paths, "records_dir", root=root),
        mappings_dir=_resolve_path(paths, "mappings_dir", root=root),
        redact=_require_bool(privacy, "redact"),
        name_allowlist=_require_string_list(privacy, "name_allowlist"),
        max_text_chars=_require_positive_int(ingest, "max_text_chars"),
        dedupe=_require_bool(dedupe, "dedupe"),
    )


def _section(raw: dict[str, Any], name: str, path: Path) -> dict[str, Any]:
    value = raw.get(name)
    if value is None:
        raise ConfigFileError(f"{path} has no [{name}] section")
    if not isinstance(value, dict):
        raise ConfigFileError(f"[{name}] must be a table, got {type(value).__name__}")
    return value


def _reject_unknown(table: dict[str, Any], *, allowed: frozenset[str], what: str) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        known = ", ".join(sorted(allowed))
        raise ConfigFileError(
            f"unknown {what}: {', '.join(unknown)}. Known: {known}. "
            "A tolerated typo in a privacy setting is a setting nobody actually has."
        )


def _require(table: dict[str, Any], key: str) -> Any:
    if key not in table:
        raise ConfigFileError(f"configuration is missing {key}")
    return table[key]


def _require_bool(table: dict[str, Any], key: str) -> bool:
    value = _require(table, key)
    if not isinstance(value, bool):
        raise ConfigFileError(f"{key} must be true or false, got {type(value).__name__}")
    return value


def _require_positive_int(table: dict[str, Any], key: str) -> int:
    value = _require(table, key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigFileError(f"{key} must be an integer, got {type(value).__name__}")
    if value < 1:
        raise ConfigFileError(f"{key} must be at least 1, got {value}")
    return value


def _require_string_list(table: dict[str, Any], key: str) -> tuple[str, ...]:
    value = _require(table, key)
    if not isinstance(value, list):
        raise ConfigFileError(f"{key} must be a list, got {type(value).__name__}")
    for entry in value:
        if not isinstance(entry, str) or not entry.strip():
            raise ConfigFileError(
                f"every entry in the {key} must be a non-empty string, "
                f"got {entry!r}"
            )
    return tuple(value)


def _resolve_path(table: dict[str, Any], key: str, *, root: Path) -> Path:
    value = _require(table, key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigFileError(f"{key} must be a non-empty string, got {value!r}")
    candidate = Path(value)
    if candidate.is_absolute():
        raise ConfigFileError(
            f"{key} is absolute ({value}). Paths are relative to the configuration file; "
            "a committed absolute path works on exactly one machine."
        )
    resolved = (root / candidate).resolve()
    if root not in resolved.parents and resolved != root:
        raise ConfigFileError(
            f"{key} resolves to {resolved}, which is outside {root}. "
            "A configuration file may not point a run at somebody else's directory."
        )
    return resolved
