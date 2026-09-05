# Stage: 07_emit — PLANNED

Write the dataset in project 1's golden-case schema, as **drafts**, for a named
human to promote.

## Objective

Produce a file that `regression_detect.goldens.load_goldens` accepts, a review
document a person can read in one sitting, and no path by which a case reaches a
golden set without a name attached.

## Inputs

| Path or source | Layer | Authority | Required | Relevant section |
|---|---:|---|---:|---|
| `selected/<window>/candidates.jsonl` | 4 | Authoritative | Yes | One object per chosen case: `record_id`, `stratum`, `score`, `reasons`, `input_text`, `output_text` |
| `records/<window>/labels.jsonl` | 4 | Authoritative | Yes | `criteria` |
| `records/<window>/records.jsonl` | 4 | Authoritative | Yes | `input_text`, `output_text` |
| A target goldens file | 3 | Authoritative | Only for `promote` | Its existing ids |

## Process (planned)

1. Render each selected record as a golden case in project 1's schema.
2. **Round-trip every scalar through a YAML parse and compare it to its source**
   before the file is written. A case project 1 cannot parse is not a case.
3. Write `candidates.yaml`, plus a `review.md` with the input, the output, the
   signals that selected it, the drafted criteria as `- [ ]` boxes, and one
   `Accept / Edit / Reject` line each.
4. `loghog emit promote --file <candidates.yaml> --ids a,b --into <goldens.yaml>
   --reviewed-by <name>` appends **as text**, so that the comments in a goldens
   file — half its content — survive, and re-loads the result with
   `load_goldens` before replacing the file.

## Outputs (planned)

| Path | Schema or format | Consumer |
|---|---|---|
| `records/<window>/candidates.yaml` | Project 1's golden-case schema | A human, then `emit promote` |
| `records/<window>/review.md` | Markdown, one section per candidate | A human |

## Verify (planned)

- The emitted file loads with **project 1's own loader**, called in the tests —
  not with a schema restated here, because a restated schema is a schema that
  drifts.
- Promotion refuses without `--reviewed-by`, refuses an unknown id, and refuses
  an id the target already holds — a golden id is stable for ever and project 1's
  baselines key on it.
- A promotion that would break the target writes nothing.

## Approval (planned)

**This is the human gate for the whole tool.** `--reviewed-by <name>`, one id at
a time, and no switch that means "all of them".

## Failure Behavior (planned)

| Situation | What happens |
|---|---|
| A rendered scalar does not survive a YAML round trip | Fall back to a quoted scalar; if the file still does not verify, nothing is written |
| `--reviewed-by` absent | Refused. Exit 3 |
| An id already in the target | Refused, naming it. Exit 3 |
| The target will not re-load after the append | The original file is left exactly as it was |
