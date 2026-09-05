"""`selection.md`: the shortlist's shape, and every record it left behind.

The division of labour between the two files this stage writes is deliberate.
`candidates.jsonl` holds the redacted case itself, because stage 06 needs the
text to draft criteria against. `selection.md` is the file people paste into a
ticket and attach to a mail, and it holds **no text from the window at all** —
counts, quotas, cluster ids and stratum names, and nothing a customer wrote.
"""

from typing import Any

from loghog import __version__


def render_selection_report(outcome: Any) -> str:
    """Render the human summary of one selection."""
    dropped_total = sum(outcome.dropped.values())
    lines = [
        f"# Selection for window `{outcome.window}`",
        "",
        f"loghog {__version__}. {outcome.selected_count} candidate(s) chosen from "
        f"{outcome.considered} scored record(s); {dropped_total} refused by a named cap.",
        "",
        "Every record that is not on the shortlist was refused by exactly one cap, and "
        "every cap has a count below. A shortlist whose omissions are unexplained is a "
        "shortlist nobody can trust to be representative, which is the only property it "
        "is supposed to have.",
        "",
        "## Caps",
        "",
        "| | Value |",
        "|---|---:|",
        f"| Candidates, at most | {outcome.max_candidates} |",
        f"| Per cluster, at most | {outcome.max_per_cluster} |",
        "",
        "## What was dropped, and by which cap",
        "",
    ]
    if outcome.dropped:
        lines += ["| Cap | Records | What it means |", "|---|---:|---|"]
        for name, count in sorted(outcome.dropped.items()):
            lines.append(f"| `{name}` | {count} | {_explain(name)} |")
    else:
        lines.append("Nothing. Every scored record in this window is on the shortlist.")

    lines += [
        "",
        "## Strata",
        "",
        "A record's stratum is the highest-weighted signal it fired, or `ordinary` if it "
        "fired none. Quotas are what stop a top-N by score from producing a dataset made "
        "entirely of one week's loudest failure.",
        "",
        "| Stratum | Quota | Chosen | Unfilled |",
        "|---|---:|---:|---:|",
    ]
    for stratum in outcome.strata:
        lines.append(
            f"| `{stratum.name}` | {stratum.quota} | {stratum.selected} | {stratum.unfilled} |"
        )

    unfilled = outcome.unfilled
    lines += ["", "## Unfilled", ""]
    if unfilled:
        named = ", ".join(f"`{name}` ({short} short)" for name, short in unfilled)
        lines += [
            f"{len(unfilled)} stratum/strata could not be filled: {named}.",
            "",
            "A shortfall is **never** topped up from another stratum. An unfilled quota "
            "is a fact about the traffic — most windows contain no injection attempts — "
            "and borrowing against it would quietly turn the dataset back into the "
            "monoculture the quotas exist to prevent.",
        ]
    else:
        lines.append("None. Every stratum's quota was met.")

    lines += [
        "",
        "## The shortlist",
        "",
        "| Rank | Record | Score | Stratum | Cluster | Cluster size |",
        "|---:|---|---:|---|---|---:|",
    ]
    for candidate in outcome.selected:
        lines.append(
            f"| {candidate.rank} | `{candidate.record_id}` | {candidate.score} "
            f"| `{candidate.stratum}` | `{candidate.cluster_id}` | {candidate.cluster_size} |"
        )
    lines += [
        "",
        "The cases themselves are in `candidates.jsonl`, which holds the redacted text "
        "because the next stage needs it. This file holds none, because this is the one "
        "somebody will paste into a ticket.",
        "",
    ]
    return "\n".join(lines) + "\n"


_EXPLANATIONS = {
    "already_in_goldens": "a golden case already covers it, so it is not a case to mine",
    "cluster_cap": "its cluster was already full; the higher-scoring member speaks for it",
    "max_candidates": "the global cap was reached and this would otherwise have been taken",
}


def _explain(name: str) -> str:
    if name.startswith("quota:"):
        return f"the `{name.split(':', 1)[1]}` quota was already met"
    return _EXPLANATIONS.get(name, "refused by a cap")
