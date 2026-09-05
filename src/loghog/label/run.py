"""Stage 06 end to end: read the shortlist, draft once per case, write both files.

Three properties, and the tests assert all three.

**Exactly one call per candidate.** Not one per criterion, not a loop that
refines. A labelled dataset whose cost is proportional to anything other than
the number of candidates is a dataset nobody will rebuild, and a stage that
could not say what it cost before it ran is a stage nobody will point at
production.

**The budget refuses rather than truncating.** `[label] max_calls` is checked
before the first call. Labelling the first hundred of a hundred and forty
candidates would produce a dataset whose contents depend on a number nobody was
shown, and would spend real money doing it.

**A failure is a row, not an exception.** A run that aborted on the first rate
limit would throw away every draft it had already paid for. Failures are
recorded with their error type, counted, and kept out of what stage 07 emits.

The labels live beside the candidates in `selected/<window>/` rather than in the
window, and that is a change from the planned contract. A drafted criterion is
*about* one case and can paraphrase it — "states that the parcel was left in a
bin" is most of the ticket — so it belongs in the directory that is gitignored
for exactly that reason, next to the shortlist that provoked it, rather than in
the window of records it was never part of.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from regression_detect.pacing import pace, validate_interval

from loghog import __version__
from loghog.config_file import LoghogConfig
from loghog.errors import LabelError
from loghog.label.draft import DRAFT_PROMPT_SHA256, Draft, Drafter, DraftTask
from loghog.label.report import render_label_report
from loghog.record import Record
from loghog.select.run import CANDIDATES_NAME
from loghog.window.artifacts import read_jsonl, write_jsonl, write_text
from loghog.window.store import WindowStore

EXIT_OK = 0
EXIT_PARTIAL = 1
EXIT_NOTHING = 2

LABELS_NAME = "labels.jsonl"
LABEL_REPORT_NAME = "label.md"


@dataclass(frozen=True)
class Label:
    """One candidate's drafted criteria, or the recorded reason there are none."""

    record_id: str
    stratum: str
    score: int
    signals: tuple[str, ...]
    criteria: tuple[str, ...] | None
    notes: str | None
    draft_error: str | None
    model_id: str
    dry_run: bool

    @property
    def drafted(self) -> bool:
        return self.criteria is not None

    def to_json_dict(self) -> dict[str, Any]:
        # `criteria` is null rather than `[]` when a draft failed, because absent
        # and empty are different facts everywhere else in this package and a
        # reader of one row should not have to know which convention this file
        # chose.
        return {
            "criteria": list(self.criteria) if self.criteria is not None else None,
            "draft_error": self.draft_error,
            "dry_run": self.dry_run,
            "loghog_version": __version__,
            "model_id": self.model_id,
            "notes": self.notes,
            "prompt_sha256": DRAFT_PROMPT_SHA256,
            "record_id": self.record_id,
            "score": self.score,
            "signals": list(self.signals),
            "stratum": self.stratum,
        }


@dataclass(frozen=True)
class LabelOutcome:
    """What one `loghog label` did."""

    window: str
    directory: Path
    labels: tuple[Label, ...]
    model_id: str
    dry_run: bool
    calls: int
    by_error: dict[str, int]
    exit_code: int

    @property
    def considered(self) -> int:
        return len(self.labels)

    @property
    def drafted(self) -> int:
        return sum(1 for label in self.labels if label.drafted)

    @property
    def failed(self) -> int:
        return self.considered - self.drafted


def label_window(
    config: LoghogConfig,
    *,
    window: str,
    drafter: Drafter,
    dry_run: bool,
    min_interval_ms: int | None = None,
    out_dir: Path | None = None,
) -> LabelOutcome:
    """Draft criteria for every candidate in one window's shortlist.

    Args:
        drafter: Built by the caller, so this function never learns what a
            provider is. `--dry-run` hands in the synthetic one.
        min_interval_ms: Overrides `[label] min_interval_ms`. Ignored entirely
            under `dry_run`, which always paces at zero: there is no quota to
            respect when nothing is called, and a forty-candidate dry run that
            took four minutes is a dry run nobody would run twice.

    Raises:
        LabelError: the window has no shortlist, the shortlist is empty, it is
            longer than the call budget, or it names a record the window does
            not hold.
    """
    directory = Path(out_dir) if out_dir is not None else config.selected_dir / window
    path = directory / CANDIDATES_NAME
    if not path.is_file():
        raise LabelError(
            f"window {window!r} has no shortlist at {path}. Run "
            f"`loghog select --window {window}` first."
        )
    candidates = read_jsonl(path, what="candidates file")
    if not candidates:
        raise LabelError(
            f"the shortlist for {window!r} is empty, so there is nothing to label. "
            f"`loghog select --window {window}` exits 2 when it chooses nothing; read "
            "its report before spending calls on this."
        )
    if len(candidates) > config.label.max_calls:
        raise LabelError(
            f"the shortlist for {window!r} holds {len(candidates)} candidate(s) and "
            f"[label] max_calls is {config.label.max_calls}. This refuses rather than "
            "labelling a prefix: a dataset whose contents depend on where a budget ran "
            "out is not one anybody can reason about. Lower [select] max_candidates or "
            "raise the budget, on purpose."
        )

    records = _records_for(config, window=window, candidates=candidates)
    # Validated where it was given, not where it is used. A dry run ignores the
    # interval, but `--min-interval-ms -5 --dry-run` is still a typo, and a typo
    # swallowed because of an unrelated flag is one that reappears on the live
    # run somebody was rehearsing for.
    if min_interval_ms is not None:
        validate_interval(min_interval_ms)
    interval = validate_interval(_interval(config, min_interval_ms, dry_run=dry_run))
    labels: list[Label] = []
    by_error: dict[str, int] = {}
    model_ids: list[str] = []
    started: float | None = None
    for row in candidates:
        record = records[row["record_id"]]
        started = pace(started, interval)
        outcome = drafter(_task(row, record))
        model_ids.append(outcome.model_id)
        if outcome.error_type is not None:
            by_error[outcome.error_type] = by_error.get(outcome.error_type, 0) + 1
        labels.append(_label(row, outcome.draft, outcome.error_type, outcome.model_id, dry_run))

    outcome = LabelOutcome(
        window=window,
        directory=directory,
        labels=tuple(labels),
        model_id=_one_model_id(model_ids),
        dry_run=dry_run,
        calls=len(labels),
        by_error=by_error,
        exit_code=_exit_code(labels),
    )
    write_jsonl(directory / LABELS_NAME, [label.to_json_dict() for label in outcome.labels])
    write_text(directory / LABEL_REPORT_NAME, render_label_report(outcome))
    return outcome


def _interval(
    config: LoghogConfig, min_interval_ms: int | None, *, dry_run: bool
) -> int:
    """The gap to leave between calls, in milliseconds.

    Zero for a dry run whatever else was asked for. Pacing exists to keep a
    burst of calls inside a per-minute provider quota, and a run that makes no
    calls consumes no quota — so honouring the interval there would buy nothing
    and cost four minutes on a shortlist of forty.
    """
    if dry_run:
        return 0
    return config.label.min_interval_ms if min_interval_ms is None else min_interval_ms


def read_labels(directory: Path) -> list[Label]:
    """Read `labels.jsonl` back.

    Raises:
        LabelError: the file is absent, or a row is not a label.
    """
    path = Path(directory) / LABELS_NAME
    if not path.is_file():
        raise LabelError(
            f"no labels at {path}. Run `loghog label --window {Path(directory).name}` first."
        )
    labels = []
    for row in read_jsonl(path, what="labels file"):
        try:
            criteria = row["criteria"]
            labels.append(
                Label(
                    record_id=row["record_id"],
                    stratum=row["stratum"],
                    score=int(row["score"]),
                    signals=tuple(row["signals"]),
                    criteria=tuple(criteria) if criteria is not None else None,
                    notes=row["notes"],
                    draft_error=row["draft_error"],
                    model_id=row["model_id"],
                    dry_run=bool(row["dry_run"]),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise LabelError(f"{path} holds a row that is not a label: {exc}") from exc
    return labels


def _records_for(
    config: LoghogConfig, *, window: str, candidates: list[dict[str, Any]]
) -> dict[str, Record]:
    store = WindowStore(config.records_dir / window)
    records = {record.record_id: record for record in store.read_records()}
    missing = sorted({row["record_id"] for row in candidates} - set(records))
    if missing:
        raise LabelError(
            f"the shortlist names {len(missing)} record(s) this window does not hold, "
            f"starting with {missing[0]!r}. Re-run `loghog select --window {window}`."
        )
    return records


def _task(row: dict[str, Any], record: Record) -> DraftTask:
    return DraftTask(
        record_id=row["record_id"],
        input_text=row["input_text"],
        output_text=row.get("output_text"),
        signals=tuple(row.get("reasons", ())),
        verdicts=tuple(
            (verdict.criterion, verdict.passed) for verdict in record.judge_verdicts
        ),
    )


def _label(
    row: dict[str, Any],
    draft: Draft | None,
    error_type: str | None,
    model_id: str,
    dry_run: bool,
) -> Label:
    return Label(
        record_id=row["record_id"],
        stratum=row["stratum"],
        score=int(row["score"]),
        signals=tuple(row.get("reasons", ())),
        criteria=draft.criteria if draft is not None else None,
        notes=draft.notes if draft is not None else None,
        draft_error=error_type,
        model_id=model_id,
        dry_run=dry_run,
    )


def _one_model_id(model_ids: list[str]) -> str:
    """The model that answered, or a statement that more than one did.

    A run that changed model halfway is not a run whose labels share a
    provenance line, and saying so is cheaper than picking the first.
    """
    distinct = sorted(set(model_ids))
    if len(distinct) == 1:
        return distinct[0]
    return f"mixed ({', '.join(distinct)})" if distinct else "none"


def _exit_code(labels: list[Label]) -> int:
    drafted = sum(1 for label in labels if label.drafted)
    if drafted == 0:
        return EXIT_NOTHING
    return EXIT_PARTIAL if drafted < len(labels) else EXIT_OK
