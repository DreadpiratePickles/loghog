"""Shared command-line plumbing: the config option, and how failures are shown.

Errors go to stderr and are never a traceback. A traceback is a fact about this
program's call stack; the operator needs a fact about their file, and the typed
error hierarchy already carries one.
"""

import sys
from argparse import ArgumentParser
from pathlib import Path

from loghog.config_file import DEFAULT_CONFIG_NAME, LoghogConfig, load_config
from loghog.errors import ConfigError

EXIT_CANNOT_RUN = 3
"""The run could not start, or could not finish for a reason that is not about
the data: a missing file, a mapping that contradicts the format, a window that
already exists. Distinct from 2, which means the run worked and produced
nothing."""


def add_config_option(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(DEFAULT_CONFIG_NAME),
        help=f"path to the configuration file (default: ./{DEFAULT_CONFIG_NAME})",
    )


def config_from(args) -> LoghogConfig:
    return load_config(args.config)


def fail(message: str) -> int:
    """Print an actionable message to stderr and return the cannot-run code."""
    print(message, file=sys.stderr)
    return EXIT_CANNOT_RUN


def render_class_counts(by_class: dict[str, int]) -> list[str]:
    """Redaction counts as aligned lines. Counts only — never a value."""
    if not by_class:
        return ["  (nothing)"]
    width = max(len(name) for name in by_class)
    return [f"  {name.ljust(width)}  {count}" for name, count in sorted(by_class.items())]


def load_existing_inputs(path: Path | None) -> list[str] | None:
    """The inputs of an existing goldens file, read with *project 1's* loader.

    `--existing` names a golden dataset in project 1's schema, and this reads it
    with `regression_detect.goldens.load_goldens` rather than with a restatement
    of that schema here. Checking a file by loading it with the code that owns
    it is the only check that cannot drift.

    A file that will not load is a refusal rather than a skip. Losing the
    comparison quietly would propose cases the dataset already holds and call
    them novel, which is the failure this flag exists to prevent.

    Raises:
        ConfigError: the file is absent or project 1's loader rejects it.
    """
    if path is None:
        return None
    if not Path(path).is_file():
        raise ConfigError(f"no goldens file at {path}")
    from regression_detect.goldens import GoldenDatasetError, load_goldens

    try:
        cases = load_goldens(Path(path))
    except GoldenDatasetError as exc:
        raise ConfigError(f"{path} is not a golden dataset this build can read: {exc}") from exc
    return [case.input for case in cases]
