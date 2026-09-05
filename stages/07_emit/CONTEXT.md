# Stage: 07_emit — BUILT

Write the dataset in project 1's golden-case schema, as **drafts**, and give a
named human the one command that adopts one.

## Objective

Produce a file `regression_detect.goldens.load_goldens` accepts, a review
document a person can read in one sitting, and no path by which a case reaches a
golden set without a name attached to it.

## Inputs

| Path or source | Layer | Authority | Required | Relevant section |
|---|---:|---|---:|---|
| `selected/<window>/labels.jsonl` | 4 | Authoritative | Yes | `criteria`, `notes`, `draft_error`, `model_id`, `dry_run` |
| `selected/<window>/candidates.jsonl` | 4 | Authoritative | Yes | `input_text`, `output_text` |
| A candidates file | 4 | Authoritative | Only for `promote` | Read with `load_goldens` |
| A target goldens file | 3 | Authoritative | Only for `promote` | Its existing ids, and its comments |

## Process

1. Render each labelled candidate as a golden case. The id is
   `loghog_<window>_<record id>`, both slugged, because project 1's ids match
   `^[a-z][a-z0-9]*(_[a-z0-9]+)*$` and are stable for ever — its baselines key on
   them. The window is in the id so that emitting two windows into one goldens
   file collides only when it genuinely is the same record twice.
2. Tags are `loghog` first, then every signal that fired. `grep -c "- loghog"`
   then answers "how much of this eval set was proposed by a machine".
3. **Round-trip every scalar through a YAML parse and compare it to its source**
   before the file is written. A production input contains colons, quotes,
   leading spaces, emoji, blank lines and occasionally three backticks; a literal
   block that does not survive falls back to a double-quoted scalar. Guessing
   which texts are safe is how a run silently mangles the one case that mattered.
4. Write `review-<window>.md`: each case, the input as redacted, what the system
   answered, the signals that selected it, the criteria as `- [ ]` boxes, and one
   `Accept / Edit / Reject` line. Then the `promote` command with the ids already
   written out.
5. `loghog promote --file <candidates.yaml> --ids a,b --into <goldens.yaml>
   --reviewed-by <name>` appends **as text**, so the comments in a goldens file —
   half its content — survive, and **re-loads the result with `load_goldens`
   before replacing the file**.

A candidate whose draft failed is not emitted. It is listed in the review
document with its error type, so the two files agree about how many candidates
there were.

## Outputs

| Path | Schema or format | Consumer |
|---|---|---|
| `goldens/candidates-<window>.yaml` | Project 1's golden-case schema, unmodified | `load_goldens`, then a human, then `promote` |
| `goldens/review-<window>.md` | Markdown, one section per case | A human |

Both carry the case text, and they are the only two files in the repository
besides `records.jsonl` and `candidates.jsonl` that do. A review of criteria
without the case they came from is a spelling check. The text they carry is the
**redacted** text, and that is the only reason these files may leave the machine
at all — which makes stage 02 the load-bearing stage for this one.

`goldens/` is gitignored for the same reason `records/` is.

## Verify

- The emitted file loads with **project 1's own loader**, called in the tests and
  again in CI — not with a schema restated here, because a restated schema is a
  schema that drifts.
- Fifteen deliberately awkward inputs — a colon, a fence, a leading space, a
  trailing newline, emoji, `null`, `yes` — each survive a round trip exactly.
- Promotion refuses without `--reviewed-by`, refuses an unknown id, refuses an id
  the target already holds, and refuses a case still carrying `[SYNTHETIC]`.
- A promotion that would break the target writes nothing, asserted by comparing
  the target's bytes before and after.
- The comments in a target goldens file survive an append.

## Approval

**This is the human gate for the whole tool.** `--reviewed-by <name>`, ids typed
on the command line, and no switch that means "all of them".

`promote` also refuses any case whose criteria still carry the `[SYNTHETIC]`
marker. The candidates file says "do not promote them" in its first three lines,
and a tool that prints that and then does it anyway has taught its operator that
its warnings are decorative.

## Failure Behavior

| Situation | What happens |
|---|---|
| The window has no labels | Refused, naming `loghog label`. Exit 3 |
| A label names a record the shortlist does not hold | Refused, naming it. Exit 3 |
| A rendered scalar does not survive a YAML round trip | Falls back to a quoted scalar; if the file still does not verify, nothing is written |
| Some candidates had no criteria | They are left out and listed in the review document. Exit 1 |
| No candidate had criteria | No candidates file is written; the review document says what failed. Exit 2 |
| `--reviewed-by` absent | Refused by argparse. Exit 2 |
| An unknown id, a duplicate id, or a `[SYNTHETIC]` placeholder | Refused, naming it. Exit 3. Nothing is written |
| The target will not re-load after the append | The original file is left exactly as it was |
