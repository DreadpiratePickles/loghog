"""The thirteen signals, each a function from a record and its window to evidence.

A signal returns a sentence or nothing. The sentence is why this record is worth
a human's attention, and it is the whole of the explanation the dataset ever
gets: `scores.jsonl` carries it, `selection.md` carries it, and a reviewer
arguing about a ranking argues about these sentences and the weights beside
them.

Two rules hold for every one of them.

**A score is recomputable by hand.** It is the sum of the weights of the signals
listed beside it, and nothing else — no normalisation, no decay, no
multiplication. A ranking nobody can recompute is a ranking nobody can argue
with, and this stage exists to be argued with.

**Evidence never quotes the record.** It names a pattern, a criterion, a count,
a threshold — never a customer's words. Stage 02 spends its whole effort keeping
production text out of files people paste into tickets, and a scorer that copied
it back out at the other end would undo all of it.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass

from loghog.cluster.shingles import jaccard, shingles
from loghog.record import Record
from loghog.score.context import ScoreContext
from loghog.score.patterns import matched_injection, matched_refusal
from loghog.score.settings import SIGNAL_NAMES


@dataclass(frozen=True)
class Signal:
    """One reason a record is interesting, and what that reason is worth."""

    name: str
    weight: int
    evidence: str

    def to_json_dict(self) -> dict[str, object]:
        return {"evidence": self.evidence, "name": self.name, "weight": self.weight}


def _failed_criteria(record: Record) -> list[str]:
    return [verdict.criterion for verdict in record.judge_verdicts if not verdict.passed]


def _feedback(record: Record, vocabulary: frozenset[str]) -> bool:
    if record.feedback is None:
        return False
    return record.feedback.strip().lower() in vocabulary


# --- the signals ------------------------------------------------------------


def _error(record: Record, context: ScoreContext) -> str | None:
    if not record.failed:
        return None
    return f"the call failed with {record.error}"


def _judge_failure(record: Record, context: ScoreContext) -> str | None:
    failed = _failed_criteria(record)
    if not failed:
        return None
    total = len(record.judge_verdicts)
    return f"{len(failed)} of {total} judged criteria failed: {'; '.join(failed)}"


def _negative_feedback(record: Record, context: ScoreContext) -> str | None:
    if not _feedback(record, context.settings.negative_feedback_words):
        return None
    return f"the customer's feedback was {record.feedback.strip().lower()!r}"


def _feedback_conflict(record: Record, context: ScoreContext) -> str | None:
    if not _feedback(record, context.settings.positive_feedback_words):
        return None
    if not (record.failed or _failed_criteria(record)):
        return None
    # The most interesting record in any log. One of the two judgements is
    # miscalibrated, and the only way to find out which is to look at the case.
    what = "the call failed" if record.failed else "a judged criterion failed"
    return f"{what}, and the customer's feedback was positive anyway"


def _version_disagreement(record: Record, context: ScoreContext) -> str | None:
    return context.disagreements.get(record.input_fingerprint())


def _injection_pattern(record: Record, context: ScoreContext) -> str | None:
    name = matched_injection(record.input_text)
    if name is None:
        return None
    return f"the input matches the {name} injection pattern"


def _refusal_pattern(record: Record, context: ScoreContext) -> str | None:
    name = matched_refusal(record.output_text)
    if name is None:
        return None
    return f"the output matches the {name} refusal pattern"


def _format_violation(record: Record, context: ScoreContext) -> str | None:
    if not context.expect_output_json or record.output_text is None:
        return None
    try:
        json.loads(record.output_text)
    except (json.JSONDecodeError, ValueError):
        return "the mapping expects a JSON output and this one does not parse"
    return None


def _novelty(record: Record, context: ScoreContext) -> str | None:
    if context.golden_shingles is None:
        return None
    mine = shingles(record.input_text, size=context.shingle_words)
    best = max((jaccard(mine, theirs) for theirs in context.golden_shingles), default=0.0)
    if best >= context.settings.novelty_max_jaccard:
        return None
    return (
        f"the best overlap with any of {len(context.golden_shingles)} existing golden "
        f"case(s) is {best:.2f}, below {context.settings.novelty_max_jaccard:.2f}"
    )


def _latency_outlier(record: Record, context: ScoreContext) -> str | None:
    threshold = context.latency_p95
    if threshold is None or record.latency_ms is None or record.latency_ms < threshold:
        return None
    percent = context.settings.outlier_percentile
    return f"{record.latency_ms} ms is at or beyond this window's p{percent} of {threshold} ms"


def _length_outlier(record: Record, context: ScoreContext) -> str | None:
    percent = context.settings.outlier_percentile
    reasons = []
    if context.input_len_p95 is not None and len(record.input_text) >= context.input_len_p95:
        reasons.append(
            f"the input is {len(record.input_text)} characters, at or beyond this window's "
            f"p{percent} of {context.input_len_p95}"
        )
    if (
        context.output_len_p95 is not None
        and record.output_text is not None
        and len(record.output_text) >= context.output_len_p95
    ):
        reasons.append(
            f"the output is {len(record.output_text)} characters, at or beyond this "
            f"window's p{percent} of {context.output_len_p95}"
        )
    return "; ".join(reasons) if reasons else None


def _non_ascii_ratio(record: Record, context: ScoreContext) -> str | None:
    text = record.input_text
    if not text:
        return None
    ratio = sum(1 for character in text if ord(character) > 127) / len(text)
    if ratio <= context.settings.non_ascii_threshold:
        return None
    return (
        f"{ratio:.0%} of the input is non-ASCII, above the "
        f"{context.settings.non_ascii_threshold:.0%} threshold"
    )


def _tiny_input(record: Record, context: ScoreContext) -> str | None:
    length = len(record.input_text.strip())
    if length >= context.settings.tiny_input_chars:
        return None
    return f"the input is {length} characters, under {context.settings.tiny_input_chars}"


SIGNAL_FUNCTIONS: dict[str, Callable[[Record, ScoreContext], str | None]] = {
    "error": _error,
    "judge_failure": _judge_failure,
    "negative_feedback": _negative_feedback,
    "feedback_conflict": _feedback_conflict,
    "version_disagreement": _version_disagreement,
    "injection_pattern": _injection_pattern,
    "refusal_pattern": _refusal_pattern,
    "format_violation": _format_violation,
    "novelty": _novelty,
    "latency_outlier": _latency_outlier,
    "length_outlier": _length_outlier,
    "non_ascii_ratio": _non_ascii_ratio,
    "tiny_input": _tiny_input,
}
"""The registry. A name in `SIGNAL_NAMES` with no function behind it would be a
weight in a reviewed configuration file that changes nothing, so a test asserts
the two agree."""


def signals_for(record: Record, context: ScoreContext) -> tuple[Signal, ...]:
    """Every signal this record fires, in registry order."""
    fired = []
    for name in SIGNAL_NAMES:
        evidence = SIGNAL_FUNCTIONS[name](record, context)
        if evidence is not None:
            fired.append(Signal(name=name, weight=context.settings.weight(name), evidence=evidence))
    return tuple(fired)


def score_of(signals: tuple[Signal, ...]) -> int:
    """The sum of the weights that fired. Nothing else happens to it."""
    return sum(signal.weight for signal in signals)
