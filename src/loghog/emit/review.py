"""`review-<window>.md`: the one document in this repository that shows the case.

Every other report here refuses to quote what it reports on, and that rule is
not suspended here — it is *satisfied* here for the first time. A review is
somebody reading the case and deciding whether the criteria drafted from it are
right, and that is impossible without the case. The reason it is allowed is
stage 02: the text in this file has been through the redactor, which is what
makes a mined dataset something that can leave the machine at all.

So the document is arranged for one sitting. One section per candidate, the
input, what the system actually answered, the signals that selected it, the
drafted criteria as unchecked boxes, and one `Accept / Edit / Reject` line. Then
the command that adopts the ones you accepted, with the ids already written out.

Candidates whose draft failed are listed too, with their error type and no
boxes. Leaving them out would make the document quietly disagree with the
shortlist about how many cases there were.
"""

from loghog import __version__
from loghog.emit.cases import EmitCase
from loghog.label.run import Label

SYNTHETIC_BANNER = (
    "SYNTHETIC — the criteria below are fixed placeholders from `loghog label "
    "--dry-run`. No model read any of these records. Do not promote them."
)

MAX_OUTPUT_CHARS = 600
"""How much of an answer the review shows before it is elided. A reviewer is
deciding whether the criteria fit the case, not reading a stack trace — and a
production answer can be a stack trace."""


def render_review(
    *,
    window: str,
    cases: list[EmitCase],
    skipped: list[Label],
    dry_run: bool,
    candidates_name: str,
) -> str:
    """Render the review document for one emitted window."""
    lines: list[str] = []
    if dry_run:
        lines += [SYNTHETIC_BANNER, ""]
    lines += [
        f"# Review: {len(cases)} drafted case(s) from window `{window}`",
        "",
        f"loghog {__version__}. Nothing below has been read by a human yet, and nothing "
        "below is in a goldens file. Tick the criteria you accept, edit the ones that "
        "are close, and reject the cases that are not worth having.",
        "",
        "A criterion is worth keeping when a stranger could read it beside an answer "
        "and say yes or no, and when the best possible answer to this input would pass "
        "it. Everything else is an eval that fails correct work.",
        "",
    ]
    for position, case in enumerate(cases, start=1):
        lines += _section(position, case)
    if skipped:
        lines += [
            "## Candidates with no criteria",
            "",
            "These were selected and their drafts could not be read. They are **not** in "
            f"`{candidates_name}`: a placeholder criterion in a golden case is a sentence "
            "nobody wrote defining what nobody may break. Re-run `loghog label` for them, "
            "or write their criteria by hand.",
            "",
            "| Record | Stratum | Score | Why there is no draft |",
            "|---|---|---:|---|",
        ]
        lines += [
            f"| `{label.record_id}` | {label.stratum} | {label.score} | `{label.draft_error}` |"
            for label in skipped
        ]
        lines.append("")
    lines += _footer(cases, candidates_name)
    return "\n".join(lines) + "\n"


def _section(position: int, case: EmitCase) -> list[str]:
    output = case.output_text or "_(no answer — the request failed and carries an error)_"
    if len(output) > MAX_OUTPUT_CHARS:
        output = output[:MAX_OUTPUT_CHARS] + f"… _(elided, {len(case.output_text)} chars)_"
    signals = ", ".join(f"`{name}`" for name in case.signals) or "_none — ordinary traffic_"
    lines = [
        f"## {position}. `{case.case_id}`",
        "",
        f"Record `{case.record_id}` · stratum **{case.stratum}** · score **{case.score}** "
        f"· signals: {signals}",
        "",
        "**The input, as redacted:**",
        "",
        f"> {_quote(case.input_text)}",
        "",
        "**What the system answered:**",
        "",
        f"> {_quote(output)}",
        "",
        "**Drafted criteria** — tick the ones you accept:",
        "",
    ]
    lines += [f"- [ ] {text}" for text in case.criteria]
    lines.append("")
    # Appended conditionally rather than added-then-filtered. The first version
    # built the list with an empty string where the note would go and then
    # dropped every empty string — which took all the blank lines with it, and
    # markdown is whitespace-sensitive. It read perfectly in a terminal and
    # rendered as one paragraph everywhere else.
    if case.notes:
        lines += [f"_Drafter's note: {case.notes}_", ""]
    lines += ["**Accept / Edit / Reject:**", "", ""]
    return lines


def _quote(text: str) -> str:
    """Text as one blockquote, with every line prefixed so a newline cannot escape it."""
    return "\n> ".join(text.splitlines() or [""])


def _footer(cases: list[EmitCase], candidates_name: str) -> list[str]:
    if not cases:
        return [
            "No case was drafted, so there is nothing to promote and no candidates file "
            "was written.",
            "",
        ]
    ids = ",".join(case.case_id for case in cases)
    return [
        "## Promoting what you accepted",
        "",
        "One id at a time, with your name on it. There is no switch that means "
        "\"all of them\", because that is not a review.",
        "",
        "```bash",
        f"loghog promote --file {candidates_name} \\",
        f"    --ids {ids} \\",
        "    --into path/to/goldens.yaml --reviewed-by 'Your Name'",
        "```",
        "",
        "Cut that list down to the ones you ticked. Promotion refuses an id the target "
        "already holds, and re-loads the result with project 1's own loader before it "
        "replaces anything — so a promotion that would break your goldens file writes "
        "nothing at all.",
        "",
    ]


__all__ = ["MAX_OUTPUT_CHARS", "SYNTHETIC_BANNER", "render_review"]
