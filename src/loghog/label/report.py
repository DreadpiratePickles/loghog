"""`label.md`: what was drafted, what failed, and not one word of any case.

The criteria themselves are in `labels.jsonl` and, once emitted, in the review
document a person actually reads. This file is the run's accounting — how many
calls, to which model, under which prompt, and how many came back unusable —
which is what somebody needs in order to decide whether to run it again.

A drafted criterion paraphrases the case it was drafted from, so it is not here.
That is the same rule `score.md`, `cluster.md` and `selection.md` keep, applied
to the one stage that produces new sentences rather than counts.
"""

from loghog import __version__
from loghog.label.draft import DRAFT_PROMPT_SHA256

SYNTHETIC_BANNER = (
    "SYNTHETIC — every criterion in this run is a fixed placeholder. No model was "
    "called, nothing read these records, and none of it may be promoted."
)


def render_label_report(outcome) -> str:
    """Render `label.md` for one labelling run."""
    lines: list[str] = []
    if outcome.dry_run:
        lines += [SYNTHETIC_BANNER, ""]
    lines += [
        f"# Labels for window `{outcome.window}`",
        "",
        f"loghog {__version__}. {outcome.calls} call(s), one per candidate: "
        f"{outcome.drafted} drafted, {outcome.failed} failed.",
        "",
        "| | |",
        "|---|---|",
        f"| Model | `{outcome.model_id}` |",
        f"| Drafting prompt | `{DRAFT_PROMPT_SHA256[:12]}…` |",
        f"| Dry run | {'yes' if outcome.dry_run else 'no'} |",
        "",
    ]
    if outcome.by_error:
        lines += [
            "## What failed, and how",
            "",
            "A candidate whose draft could not be read is kept out of the emitted "
            "dataset entirely. A placeholder criterion in a golden case would be a "
            "sentence nobody wrote defining what nobody may break.",
            "",
            "| Error | Count |",
            "|---|---:|",
        ]
        lines += [
            f"| `{name}` | {count} |" for name, count in sorted(outcome.by_error.items())
        ]
        lines.append("")
    else:
        lines += ["Every candidate came back with a usable draft.", ""]

    lines += [
        "## Candidates",
        "",
        "| Record | Stratum | Score | Criteria | Draft |",
        "|---|---|---:|---:|---|",
    ]
    for label in outcome.labels:
        count = len(label.criteria) if label.criteria is not None else 0
        state = "drafted" if label.drafted else f"failed ({label.draft_error})"
        lines.append(
            f"| `{label.record_id}` | {label.stratum} | {label.score} | {count} | {state} |"
        )
    lines += [
        "",
        "The criteria themselves are in `labels.jsonl`, and in the review document "
        "`loghog emit` writes. They are not here: a drafted criterion paraphrases the "
        "case it came from, and this file is the one that goes in a ticket.",
        "",
        "Nothing above has been read by a human. `loghog emit` turns these into drafts "
        "and `loghog promote` is the only thing that adopts one.",
        "",
    ]
    return "\n".join(lines) + "\n"
