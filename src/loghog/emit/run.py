"""Stage 07 end to end: a labelled shortlist in, drafts and a review document out.

Two files, two audiences, and one of them is the only file in this repository
that is *supposed* to be read alongside the case it describes.

`goldens/candidates-<window>.yaml` is for project 1's loader, and the tests
prove it by calling that loader rather than by restating its schema.
`goldens/review-<window>.md` is for the person who has to decide whether these
criteria are right, and it shows them the input, because a review of criteria
without the case they came from is a spelling check.

A candidate whose draft failed is **not** emitted. It is listed in the review
document with its error type, so the two files agree about how many candidates
there were, and so that "we could not draft for this one" is a fact somebody
reads rather than a row that quietly disappeared.
"""

from dataclasses import dataclass
from pathlib import Path

from loghog.config_file import LoghogConfig
from loghog.emit.cases import EmitCase, case_id_for, render_cases_yaml
from loghog.emit.review import render_review
from loghog.errors import EmitError
from loghog.label.run import Label, read_labels
from loghog.select.run import CANDIDATES_NAME
from loghog.window.artifacts import read_jsonl, write_text

EXIT_OK = 0
EXIT_PARTIAL = 1
EXIT_NOTHING = 2


@dataclass(frozen=True)
class EmitOutcome:
    """What one `loghog emit` did."""

    window: str
    cases: tuple[EmitCase, ...]
    skipped: tuple[Label, ...]
    candidates_path: Path
    review_path: Path
    dry_run: bool
    exit_code: int

    @property
    def emitted(self) -> int:
        return len(self.cases)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)


def candidates_path_for(config: LoghogConfig, window: str) -> Path:
    """Where the drafted cases for one window are written."""
    return config.goldens_dir / f"candidates-{window}.yaml"


def review_path_for(config: LoghogConfig, window: str) -> Path:
    """Where the review document for one window is written."""
    return config.goldens_dir / f"review-{window}.md"


def emit_window(
    config: LoghogConfig, *, window: str, selected_dir: Path | None = None
) -> EmitOutcome:
    """Render one window's labelled shortlist as drafted golden cases.

    Raises:
        EmitError: the window has not been labelled, a label names a record the
            shortlist does not hold, or a rendered case does not survive a YAML
            round trip.
    """
    directory = Path(selected_dir) if selected_dir is not None else config.selected_dir / window
    labels = read_labels(directory)
    candidates = {
        row["record_id"]: row
        for row in read_jsonl(directory / CANDIDATES_NAME, what="candidates file")
    }
    missing = sorted({label.record_id for label in labels} - set(candidates))
    if missing:
        raise EmitError(
            f"the labels for {window!r} name {len(missing)} record(s) the shortlist does "
            f"not hold, starting with {missing[0]!r}. Re-run `loghog select --window "
            f"{window}` and `loghog label --window {window}`."
        )

    dry_run = any(label.dry_run for label in labels)
    cases = [
        _case(window, candidates[label.record_id], label)
        for label in labels
        if label.drafted
    ]
    skipped = tuple(label for label in labels if not label.drafted)

    candidates_path = candidates_path_for(config, window)
    review_path = review_path_for(config, window)
    if cases:
        write_text(
            candidates_path, render_cases_yaml(cases, window=window, dry_run=dry_run)
        )
    write_text(
        review_path,
        render_review(
            window=window,
            cases=cases,
            skipped=list(skipped),
            dry_run=dry_run,
            candidates_name=candidates_path.name,
        ),
    )
    return EmitOutcome(
        window=window,
        cases=tuple(cases),
        skipped=skipped,
        candidates_path=candidates_path,
        review_path=review_path,
        dry_run=dry_run,
        exit_code=_exit_code(cases, skipped),
    )


def _case(window: str, candidate: dict, label: Label) -> EmitCase:
    assert label.criteria is not None  # the caller filtered on `drafted`
    return EmitCase(
        case_id=case_id_for(window=window, record_id=label.record_id),
        record_id=label.record_id,
        window=window,
        input_text=candidate["input_text"],
        output_text=candidate.get("output_text"),
        stratum=label.stratum,
        score=label.score,
        signals=label.signals,
        criteria=label.criteria,
        notes=label.notes or "",
        model_id=label.model_id,
        dry_run=label.dry_run,
    )


def _exit_code(cases: list[EmitCase], skipped: tuple[Label, ...]) -> int:
    """0 everything emitted, 1 some candidate had no draft, 2 nothing emitted.

    A skipped candidate makes this 1 for the same reason a rejected line makes
    `ingest` exit 1: the run worked and the result is smaller than the input,
    and nobody reads the report of a command that succeeded.
    """
    if not cases:
        return EXIT_NOTHING
    return EXIT_PARTIAL if skipped else EXIT_OK


__all__ = [
    "EXIT_NOTHING",
    "EXIT_OK",
    "EXIT_PARTIAL",
    "EmitOutcome",
    "candidates_path_for",
    "emit_window",
    "review_path_for",
]
