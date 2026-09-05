"""Stage 03, end to end: read a window, score every record, write both files.

Two files, two audiences. `scores.jsonl` is one object per record for stages 04
and 05. `score.md` is for a person, and its most important section is the one
listing the signals that could **not** be evaluated and why — because a report
that printed a tidy zero for a signal the window cannot support would be worse
than not having the signal.

The exit code carries that same distinction. An absence the operator chose is a
0; an impediment the window imposes is a 1, exactly like a partial ingest,
because nobody reads the report of a command that succeeded.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loghog import __version__
from loghog.config_file import LoghogConfig
from loghog.errors import ManifestError, ScoreError
from loghog.score.context import ScoreContext, build_context
from loghog.score.report import render_score_report
from loghog.score.signals import Signal, score_of, signals_for
from loghog.window.artifacts import write_jsonl, write_text
from loghog.window.store import WindowStore

EXIT_OK = 0
EXIT_PARTIAL = 1


@dataclass(frozen=True)
class RecordScore:
    """One record's score and the evidence behind it."""

    record_id: str
    score: int
    signals: tuple[Signal, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "score": self.score,
            "signals": [signal.to_json_dict() for signal in self.signals],
        }


@dataclass(frozen=True)
class ScoreOutcome:
    """What one `loghog score` did."""

    window: str
    directory: Path
    scored: int
    scores: tuple[RecordScore, ...]
    context: ScoreContext
    by_signal: dict[str, int]
    exit_code: int


def score_window(
    config: LoghogConfig,
    *,
    window: str,
    out_dir: Path | None = None,
    golden_inputs: Sequence[str] | None = None,
) -> ScoreOutcome:
    """Score every record in one window.

    Raises:
        ScoreError: the window does not exist, holds no records, or was written
            by a manifest schema this build does not read.
    """
    directory = Path(out_dir) if out_dir is not None else config.records_dir / window
    store = WindowStore(directory)
    if not store.records_path.is_file():
        raise ScoreError(
            f"no window at {directory}. Run `loghog ingest --window {window} ...` first, "
            "or check the window name."
        )
    records = store.read_records()
    if not records:
        raise ScoreError(f"window {window!r} holds no records to score")
    try:
        manifest = store.read_manifest()
    except ManifestError as exc:
        raise ScoreError(
            f"{store.manifest_path} cannot be read by this build: {exc}"
        ) from exc

    context = build_context(
        records,
        settings=config.score,
        shingle_words=config.cluster.shingle_words,
        dedupe_enabled=manifest.dedupe_enabled,
        output_json_expectation=json_expectation(manifest.sources),
        golden_inputs=golden_inputs,
    )

    scores = tuple(
        RecordScore(
            record_id=record.record_id,
            score=score_of(signals),
            signals=signals,
        )
        for record, signals in ((r, signals_for(r, context)) for r in records)
    )
    by_signal: dict[str, int] = {}
    for entry in scores:
        for signal in entry.signals:
            by_signal[signal.name] = by_signal.get(signal.name, 0) + 1

    write_jsonl(store.scores_path, [entry.to_json_dict() for entry in scores])
    write_text(
        store.score_report_path,
        render_score_report(
            window=window,
            manifest=manifest,
            context=context,
            scores=scores,
            by_signal=by_signal,
            version=__version__,
        ),
    )
    return ScoreOutcome(
        window=window,
        directory=directory,
        scored=len(scores),
        scores=scores,
        context=context,
        by_signal=by_signal,
        exit_code=EXIT_PARTIAL if context.blocked else EXIT_OK,
    )


def json_expectation(sources) -> str:
    """Whether every source in this window declares `[expect] output_json`.

    Three answers rather than two. A window whose sources *disagree* has no
    per-record answer at all — a record does not carry which source it came
    from — and inventing one would apply one producer's contract to another
    producer's output.
    """
    declared = {bool(source.expect_output_json) for source in sources}
    if declared == {True}:
        return "all"
    if declared == {False}:
        return "none"
    return "mixed"
