"""`score.md`: what fired, what it was worth, and what could not be looked at.

Same two rules as the ingest report, for the same reasons.

**It quotes nothing.** Not a record, not a piece of evidence — evidence names a
pattern or a count, but a report is the artefact people paste into a ticket and
the safest rule is the one with no exceptions in it. So this file carries
counts and thresholds and no text from the window at all.

**It says what could not be evaluated, first among the things that are not
numbers.** A signal that was silenced by the window is the single most
misleading thing a scoring report can leave out, because its absence reads as a
zero.
"""

from collections.abc import Sequence
from typing import Any

from loghog.ingest.report import SYNTHETIC_BANNER, UNREDACTED_BANNER
from loghog.score.context import ScoreContext
from loghog.score.settings import SIGNAL_NAMES


def render_score_report(
    *,
    window: str,
    manifest: Any,
    context: ScoreContext,
    scores: Sequence[Any],
    by_signal: dict[str, int],
    version: str,
) -> str:
    """Render `score.md` for one window."""
    lines: list[str] = []
    if manifest.synthetic:
        lines += [SYNTHETIC_BANNER, ""]
    if not manifest.redaction.get("enabled"):
        lines += [UNREDACTED_BANNER, ""]

    interesting = [entry for entry in scores if entry.score > 0]
    total = sum(entry.score for entry in scores)
    lines += [
        f"# Scores for window `{window}`",
        "",
        f"loghog {version}. {len(scores)} record(s) scored, {len(interesting)} of which "
        f"fired at least one signal. Total score {total}.",
        "",
        "A score is the sum of the weights of the signals listed beside it in "
        "`scores.jsonl`, and nothing else — no normalisation and no decay. That is "
        "deliberate: a ranking somebody can recompute by hand is a ranking somebody "
        "can argue with, and this stage exists to be argued with.",
        "",
        "## Signals that fired",
        "",
    ]
    if by_signal:
        lines += ["| Signal | Weight | Records | Share |", "|---|---:|---:|---:|"]
        for name in SIGNAL_NAMES:
            count = by_signal.get(name, 0)
            if not count:
                continue
            share = count / len(scores) if scores else 0.0
            lines.append(
                f"| `{name}` | {context.settings.weight(name)} | {count} | {share:.1%} |"
            )
    else:
        lines.append("None. Every record in this window looks ordinary.")

    lines += ["", "## Not evaluated", ""]
    if context.not_evaluated:
        lines += ["| Signal | Blocking | Why |", "|---|---|---|"]
        for entry in sorted(context.not_evaluated, key=lambda item: item.signal):
            mark = "**yes**" if entry.blocking else "no"
            lines.append(f"| `{entry.signal}` | {mark} | {entry.reason} |")
        lines += [
            "",
            "A **blocking** entry is a signal the window itself silenced, and the run "
            "exits 1 because of it. A non-blocking one is an absence somebody chose — "
            "no goldens file, or a window too small for a percentile. Both are listed "
            "because a signal that reported a tidy zero here would read as evidence of "
            "absence rather than absence of evidence.",
        ]
    else:
        lines.append("Nothing. Every signal had what it needed.")

    lines += ["", "## Thresholds this window used", "", "| | Value |", "|---|---:|"]
    lines += [
        f"| p{context.settings.outlier_percentile} latency | "
        f"{_or_dash(context.latency_p95, 'ms')} |",
        f"| p{context.settings.outlier_percentile} input length | "
        f"{_or_dash(context.input_len_p95, 'chars')} |",
        f"| p{context.settings.outlier_percentile} output length | "
        f"{_or_dash(context.output_len_p95, 'chars')} |",
        f"| Tiny input, under | {context.settings.tiny_input_chars} chars |",
        f"| Non-ASCII, above | {context.settings.non_ascii_threshold:.0%} |",
        f"| Novel, best overlap under | {context.settings.novelty_max_jaccard:.2f} |",
        "",
        "## Weights",
        "",
        "| Signal | Weight |",
        "|---|---:|",
    ]
    lines += [
        f"| `{name}` | {context.settings.weight(name)} |" for name in SIGNAL_NAMES
    ]
    lines += [
        "",
        "Weights live in `[score.weights]` in the configuration file, because each one "
        "is an argument rather than an implementation detail.",
        "",
    ]
    return "\n".join(lines) + "\n"


def _or_dash(value: int | None, unit: str) -> str:
    return f"{value} {unit}" if value is not None else "—"
