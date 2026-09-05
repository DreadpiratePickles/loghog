"""`health/<window>.md`: four questions, four answers, and no text from either side.

The order is the order somebody acts in. Coverage first, because it is the
number that decides whether to keep reading. Then the comparison, because a
dataset that covers the dull traffic and misses the interesting traffic is
broken in a way a single coverage figure hides. Then what to mine next, which is
the only actionable list here. Staleness and redundancy last, because retiring a
case is never urgent and is always somebody's judgement.

Cluster ids, case ids, counts and thresholds — nothing else. A health report is
the artefact that goes in a weekly summary, and a weekly summary that quotes
production text is a second copy of it in the place nobody was thinking about
privacy.
"""

from loghog import __version__
from loghog.ingest.report import SYNTHETIC_BANNER


def render_health_report(outcome) -> str:
    """Render the health report for one dataset against one window."""
    coverage = outcome.coverage
    low, high = coverage.interval
    lines: list[str] = []
    if outcome.synthetic:
        lines += [SYNTHETIC_BANNER, ""]
    lines += [
        f"# Dataset health: `{outcome.goldens_path.name}` against window `{outcome.window}`",
        "",
        f"loghog {__version__}. {outcome.staleness.total} case(s) checked against "
        f"{coverage.total} cluster(s) of traffic, at a neighbour threshold of "
        f"{outcome.threshold}.",
        "",
        f"Dataset SHA-256 `{outcome.goldens_sha256[:12]}…`. Coverage and staleness share "
        "that one threshold on purpose: they are the same relation read from both ends, "
        "and two numbers would let this report contradict itself.",
        "",
        "## Coverage",
        "",
        f"**{coverage.covered} of {coverage.total} clusters** ({coverage.share:.0%}) have a "
        f"case within {outcome.threshold}. Wilson interval {low:.0%} to {high:.0%} — a "
        "coverage figure computed from a handful of clusters is not a point, and this one "
        "uses project 1's interval rather than a second implementation of the same formula.",
        "",
        "A cluster counts as covered when **any** record in it has a case near it, not "
        "when its representative does. Merging is transitive, so a representative can be "
        "several links from the member a case actually matches.",
        "",
    ]
    lines += _comparison(outcome)
    lines += _gaps(outcome)
    lines += _signals(outcome)
    lines += _staleness(outcome)
    lines += _redundancy(outcome)
    lines += [
        "## What this decides",
        "",
        "Nothing. It retires no case, adds no case and changes no file. The command that "
        "adds one is `loghog promote`, and it needs a name.",
        "",
    ]
    return "\n".join(lines) + "\n"


def _comparison(outcome) -> list[str]:
    comparison = outcome.comparison
    lines = [
        "## Is it covering the traffic that matters?",
        "",
        "| Clusters | Covered | Of | Share |",
        "|---|---:|---:|---:|",
        f"| Something fired | {comparison.signalled_covered} | {comparison.signalled_total} "
        f"| {_share(comparison.signalled_covered, comparison.signalled_total)} |",
        f"| Nothing fired | {comparison.ordinary_covered} | {comparison.ordinary_total} "
        f"| {_share(comparison.ordinary_covered, comparison.ordinary_total)} |",
        "",
        f"One-sided Fisher exact p = {comparison.p_value:.3f}: the chance of the signalled "
        "half being covered this badly if both halves were covered at one and the same "
        "rate. Small means the dataset is covering the dull traffic and missing the "
        "interesting traffic, which is the failure that passes every release and catches "
        "nothing.",
        "",
        "It is a p-value and is called one, because both counts are here and the "
        "arithmetic is exact. It is still a comparison between two groups somebody's "
        "clustering produced, not a designed experiment.",
        "",
        "`novelty` does not count as something firing, here and only here. It is a "
        "property of the dataset rather than of the traffic — a record is novel when no "
        "case looks like it — so counting it would make this read \"clusters the dataset "
        "does not cover are covered less often than the ones it does\", which is true of "
        "every dataset ever built.",
        "",
    ]
    return lines


def _gaps(outcome) -> list[str]:
    lines = [
        "## What to mine next",
        "",
        f"{outcome.uncovered_clusters} cluster(s) have no case at all. The biggest are "
        "the ones where the most people wrote in about something this dataset cannot "
        "measure.",
        "",
    ]
    if not outcome.recommendations:
        return lines + ["Every cluster in this window has a case near it.", ""]
    lines += [
        "| Cluster | Records | Best overlap | Top score | Signals |",
        "|---|---:|---:|---:|---|",
    ]
    for gap in outcome.recommendations:
        signals = ", ".join(f"`{name}`" for name in gap.signals) or "—"
        lines.append(
            f"| `{gap.cluster_id}` | {gap.size} | {gap.best_overlap:.2f} | {gap.top_score} "
            f"| {signals} |"
        )
    lines += [
        "",
        "Ranked by size, then by the loudest score inside the cluster, then by id — so "
        "two runs over one window produce the same list.",
        "",
    ]
    return lines


def _signals(outcome) -> list[str]:
    lines = [
        "## Signal coverage",
        "",
        "Every signal has a row, including the ones that never fired. A missing row "
        "reads as \"we did not look\".",
        "",
        "| Signal | Records | Covered | Share |",
        "|---|---:|---:|---:|",
    ]
    for entry in outcome.signal_coverage:
        lines.append(
            f"| `{entry.signal}` | {entry.records} | {entry.covered_records} "
            f"| {_share(entry.covered_records, entry.records)} |"
        )
    lines += [
        "",
        "A signal with records and zero covered is a kind of failure this dataset has no "
        "case about at all.",
        "",
    ]
    return lines


def _staleness(outcome) -> list[str]:
    staleness = outcome.staleness
    lines = [
        "## Staleness",
        "",
        f"**{staleness.stale} of {staleness.total} cases** ({staleness.share:.0%}) have "
        "nothing in this window that looks like them.",
        "",
    ]
    if not staleness.entries:
        return lines + ["Every case still has traffic near it.", ""]
    lines += ["| Case | Best overlap with this window |", "|---|---:|"]
    lines += [
        f"| `{entry.case_id}` | {entry.best_overlap:.2f} |" for entry in staleness.entries
    ]
    lines += [
        "",
        "Stale is not wrong. A case about a bug you fixed is exactly the case you want to "
        "keep, and one window is not a trend — this is a list to read, not a list to act "
        "on.",
        "",
    ]
    return lines


def _redundancy(outcome) -> list[str]:
    lines = ["## Redundancy", ""]
    if not outcome.redundant:
        return lines + [
            "No two cases in this dataset are near-duplicates of each other at "
            f"{outcome.threshold}.",
            "",
        ]
    lines += [
        f"{len(outcome.redundant)} pair(s) of cases overlap by {outcome.threshold} or more. "
        "Two cases measuring one thing spend the dataset's budget twice.",
        "",
        "| Case | Case | Jaccard |",
        "|---|---|---:|",
    ]
    lines += [
        f"| `{pair.left}` | `{pair.right}` | {pair.jaccard:.2f} |" for pair in outcome.redundant
    ]
    lines.append("")
    return lines


def _share(part: int, whole: int) -> str:
    return f"{part / whole:.0%}" if whole else "—"


__all__ = ["render_health_report"]
