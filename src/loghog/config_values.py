"""The validators every configuration section shares.

Split out of `config_file` when Phase B added four more sections, because the
alternative was four copies of "must be an integer" that would drift apart in
their wording — and the wording is the product here. An operator reads these
messages more often than they read the documentation.

Every one of them refuses `bool` where a number is expected. `True` is an `int`
in Python, and a weight of `true` would silently become a weight of 1.
"""

from pathlib import Path
from typing import Any

from loghog.errors import ConfigFileError


def require(table: dict[str, Any], key: str) -> Any:
    if key not in table:
        raise ConfigFileError(f"configuration is missing {key}")
    return table[key]


def require_bool(table: dict[str, Any], key: str) -> bool:
    value = require(table, key)
    if not isinstance(value, bool):
        raise ConfigFileError(f"{key} must be true or false, got {type(value).__name__}")
    return value


def require_int(table: dict[str, Any], key: str, *, minimum: int) -> int:
    value = require(table, key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigFileError(f"{key} must be an integer, got {type(value).__name__}")
    if value < minimum:
        raise ConfigFileError(f"{key} must be at least {minimum}, got {value}")
    return value


def require_positive_int(table: dict[str, Any], key: str) -> int:
    return require_int(table, key, minimum=1)


def require_fraction(table: dict[str, Any], key: str) -> float:
    """A float strictly between 0 and 1.

    An `int` is refused rather than promoted: `non_ascii_ratio = 1` reads as
    "one" and would mean "every character", and the difference between that and
    `0.1` is a typo away.
    """
    value = require(table, key)
    if isinstance(value, bool) or not isinstance(value, float):
        raise ConfigFileError(
            f"{key} must be a fraction written with a decimal point, got {value!r}"
        )
    if not 0.0 < value < 1.0:
        raise ConfigFileError(f"{key} must be between 0 and 1 exclusive, got {value}")
    return value


def require_percentile(table: dict[str, Any], key: str) -> int:
    value = require(table, key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigFileError(f"{key} must be an integer percentile, got {value!r}")
    if not 1 <= value <= 99:
        raise ConfigFileError(f"{key} must be a percentile between 1 and 99, got {value}")
    return value


def require_string_list(table: dict[str, Any], key: str) -> tuple[str, ...]:
    value = require(table, key)
    if not isinstance(value, list):
        raise ConfigFileError(f"{key} must be a list, got {type(value).__name__}")
    for entry in value:
        if not isinstance(entry, str) or not entry.strip():
            raise ConfigFileError(
                f"every entry in the {key} must be a non-empty string, "
                f"got {entry!r}"
            )
    return tuple(value)


def require_vocabulary(table: dict[str, Any], key: str) -> frozenset[str]:
    """A non-empty list of words, lowercased for case-insensitive matching."""
    words = require_string_list(table, key)
    if not words:
        raise ConfigFileError(
            f"{key} is empty. A vocabulary with nothing in it makes its signal "
            "permanently silent, which is not the same as turning it off."
        )
    return frozenset(word.strip().lower() for word in words)


def reject_unknown(table: dict[str, Any], *, allowed: frozenset[str], what: str) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        known = ", ".join(sorted(allowed))
        raise ConfigFileError(
            f"unknown {what}: {', '.join(unknown)}. Known: {known}. "
            "A tolerated typo in a privacy setting is a setting nobody actually has."
        )


def require_exactly(table: dict[str, Any], *, names: tuple[str, ...], what: str) -> None:
    """Every name present, and nothing else.

    Stricter than `reject_unknown` because an *absent* weight or quota is not a
    default — it is a silent zero, and a silent zero is a stratum that never
    gets chosen for a reason nobody wrote down.
    """
    reject_unknown(table, allowed=frozenset(names), what=what)
    missing = sorted(set(names) - set(table))
    if missing:
        raise ConfigFileError(
            f"missing {what}: {', '.join(missing)}. An absent one is a silent zero, and a "
            "silent zero is a decision nobody reviewed."
        )


def resolve_path(table: dict[str, Any], key: str, *, root: Path) -> Path:
    value = require(table, key)
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
