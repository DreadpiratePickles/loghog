"""`drift/<a>-vs-<b>.md`: four questions, four tables, and no text from either window.

Two things this report deliberately does not say.

It does not say **"significant"**. Two Wilson intervals that do not overlap are
a conservative screen and not a hypothesis test; the report says `separated` and
means exactly that. Likewise the KS number is a statistic and not a p-value,
because two windows chosen by a person are not a sampling design under which a
p-value means anything.

It does not say **what to do**. The list of new clusters is ranked by how many
people wrote in about each, which is the list somebody would mine next — but
mining is a command a person runs, and a report that recommended it would be a
report deciding something.
"""

from typing import Any

from loghog import __version__
from loghog.ingest.report import SYNTHETIC_BANNER
from loghog.score.settings import SIGNAL_NAMES


def render_drift_report(outcome: Any) -> str:
    """Render the human comparison of two windows."""
    novelty = outcome.novelty
    lengths = outcome.input_length
    lines: list[str] = []
    if outcome.synthetic:
        lines += [SYNTHETIC_BANNER, ""]
    lines += [
        f"# Drift: `{outcome.earlier}` to `{outcome.later}`",
        "",
        f"loghog {__version__}. {lengths.earlier_n} record(s) in the earlier window, "
        f"{lengths.later_n} in the later one.",
        "",
        "Nothing below quotes either window. Cluster ids, counts, rates and one "
        "statistic are what a person needs in order to decide whether to mine again, "
        "and none of it is anything a person would have to be careful with.",
        "",
        "## Rates, with intervals",
        "",
        "| | Earlier | Later | Delta | Separated |",
        "|---|---|---|---:|---|",
    ]
    for name, comparison in sorted(outcome.rates.items()):
        lines.append(
            f"| `{name}` | {_rate(comparison, 'earlier')} | {_rate(comparison, 'later')} "
            f"| {comparison.delta:+.1%} | {'yes' if comparison.separated else 'no'} |"
        )
    lines += [
        "",
        "Intervals are Wilson score intervals, from project 1's `compare` rather than "
        "from a second implementation here. **Separated** means the two intervals do not "
        "overlap. It is a conservative screen and not a test, and calling it significant "
        "would be a claim this tool has not earned.",
        "",
        "## Signals",
        "",
        "| Signal | Earlier | Later | Delta |",
        "|---|---:|---:|---:|",
    ]
    for name in SIGNAL_NAMES:
        comparison = outcome.signal_rates[name]
        lines.append(
            f"| `{name}` | {comparison.earlier_rate:.1%} | {comparison.later_rate:.1%} "
            f"| {comparison.delta:+.1%} |"
        )
    lines += [
        "",
        "Every signal is listed, including the ones that never fired: a signal missing "
        "from a table reads as \"we did not look\", and looking and finding nothing is "
        "both the commoner and the more useful answer.",
        "",
        "## What is new",
        "",
        f"{novelty.new_clusters} of {novelty.total_clusters} cluster(s) in "
        f"`{outcome.later}` ({novelty.share:.1%}) have no counterpart in "
        f"`{outcome.earlier}` at an overlap of {novelty.threshold:.2f}.",
        "",
    ]
    if novelty.entries:
        lines += [
            "| Cluster | Size | Best overlap with the earlier window |",
            "|---|---:|---:|",
        ]
        lines += [
            f"| `{entry.cluster_id}` | {entry.size} | {entry.best_overlap:.2f} |"
            for entry in novelty.entries
        ]
        lines += [
            "",
            "Ranked by how many people wrote in about each, which is the order somebody "
            "would work down. What to do about it is a command a person runs.",
        ]
    else:
        lines.append("Nothing. Every subject in the later window was already present.")

    lines += [
        "",
        "## Input length",
        "",
        "| | Value |",
        "|---|---:|",
        f"| KS statistic | {lengths.ks_statistic:.3f} |",
        f"| Median, earlier | {lengths.earlier_median:.0f} chars |",
        f"| Median, later | {lengths.later_median:.0f} chars |",
        "",
        "The Kolmogorov-Smirnov statistic is the largest gap between the two windows' "
        "input-length distributions: 0 means identical, 1 means they do not overlap at "
        "all. It is reported as a statistic and not as a p-value, because two windows "
        "somebody picked are not a sampling design.",
        "",
    ]
    return "\n".join(lines) + "\n"


def _rate(comparison: Any, side: str) -> str:
    rate = getattr(comparison, f"{side}_rate")
    low = getattr(comparison, f"{side}_low")
    high = getattr(comparison, f"{side}_high")
    return f"{rate:.1%} ({low:.1%}-{high:.1%})"
