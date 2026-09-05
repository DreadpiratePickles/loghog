# Stage: 06_label — BUILT

The one stage that calls a model: draft checkable criteria for each selected
record, one bounded call at a time.

## Objective

For each candidate on a window's shortlist, produce three to five plain-English
criteria that a judge could check — at least one of them negative, none of them
quoting a redaction token — as strict JSON, with **exactly one model call per
candidate** and no agent loop.

The bound is the design. A labelled dataset whose cost is proportional to
anything other than the number of candidates is a dataset nobody rebuilds, and a
stage that cannot say what it will cost before it runs is one nobody points at
production twice.

## Inputs

| Path or source | Layer | Authority | Required | Relevant section |
|---|---:|---|---:|---|
| `selected/<window>/candidates.jsonl` | 4 | Authoritative | Yes | `record_id`, `stratum`, `score`, `reasons`, `input_text`, `output_text` |
| `records/<window>/records.jsonl` | 4 | Authoritative | Yes | `judge_verdicts`, which the shortlist does not carry |
| `loghog.toml` | 3 | Authoritative | Yes | `[label] model_ref`, `min_interval_ms`, `max_calls` |
| `src/loghog/config.py` | 3 | Authoritative | Yes | `LABEL_MODEL_REF` → the id, resolved here and nowhere else |
| `.env` | — | Authoritative | Only for a live run | `GEMINI_API_KEY`, loaded by project 1's provider |

## Process

1. Read the shortlist. An absent one is refused by name, with `loghog select`
   named as the command that makes it; an empty one is refused too, because a
   shortlist of nothing is a `select` that exited 2 and a report somebody has
   not read.
2. **Check the budget before the first call.** More candidates than
   `[label] max_calls` is a refusal, not a truncation.
3. Build the drafter. `--dry-run` uses a fixed `[SYNTHETIC]` placeholder list and
   calls nothing; otherwise
   `gemini_provider_from_env(model_id_for_ref(config.label.model_ref))` through
   project 1's seam.
4. One call per candidate, paced with `regression_detect.pacing.pace` under
   `[label] min_interval_ms`. Provider quotas are per minute and bounded retries
   cannot ride out a window that long. A dry run paces at **zero**: nothing is
   called, so there is no quota to spread a burst across.
5. Parse strictly. Model output is untrusted input: exactly the keys `criteria`
   and `notes`, three to five criteria, at least one starting "Does not", and
   **no criterion quoting a redaction token** — `[EMAIL_1]` in a criterion would
   be an acceptance test asserting that a production system emits loghog's own
   marker.
6. Record every failure with its error type rather than raising. A run that
   aborted on the first rate limit would throw away every draft it had paid for.

The input, the output, the signals and the verdicts travel inside `<input>`,
`<output>`, `<signals>` and `<verdicts>` delimiters in the **user** message. The
instructions live in a module constant. The material being described must not be
able to become the description's instructions, and the material here was written
by a stranger with a grievance.

## Outputs

| Path | Schema or format | Consumer |
|---|---|---|
| `selected/<window>/labels.jsonl` | `{record_id, stratum, score, signals, criteria, notes, draft_error, model_id, dry_run, prompt_sha256, loghog_version}` | Stage 07 |
| `selected/<window>/label.md` | The run's accounting: calls, model, prompt hash, failures by type | A human |

`criteria` is `null` — never `[]` — when a draft failed. Absent and empty are
different facts everywhere else in this package.

The labels live beside the shortlist rather than in the window, which is a change
from the planned contract. A drafted criterion is *about* one case and
paraphrases it — "states that the parcel was left in a bin" is most of the ticket
— so it belongs in the directory that is gitignored for exactly that reason,
next to the candidate that provoked it.

`label.md` carries no case text at all, for the same reason `score.md` and
`selection.md` do not: it is the file somebody pastes into a ticket.

## Verify

- A dry run makes no network call, asserted by handing in a drafter that raises.
- The call count equals the candidate count. Exactly.
- A malformed reply is a typed failure with the record named, and never becomes
  an empty criteria list.
- The dry-run placeholders are parsed through the real validator, so the constant
  cannot drift out of spec without a test noticing.
- A criterion quoting `[EMAIL_1]` is refused.
- A second run writes identical bytes.
- The configured interval is what reaches project 1's `pace`, asserted by
  substituting it.

## Approval

**A drafted criterion is never adopted here, and never by stage 07 either.**
`loghog promote` adopts one, for an id a named human typed, and it refuses any
case still carrying the `[SYNTHETIC]` marker. A criterion written by a model,
from customer text, that nobody read would otherwise define what "correct" means
for every later evaluation of that system.

## Failure Behavior

| Situation | What happens |
|---|---|
| No shortlist, or an empty one | Refused, naming `loghog select`. Exit 3 |
| More candidates than `[label] max_calls` | Refused before the first call, naming the budget. Exit 3 |
| No API key | `ProviderConfigError` from project 1's seam, with a message that never contains a key. Exit 3 |
| A negative `--min-interval-ms` | Refused at the boundary, even under `--dry-run` where it would be ignored |
| The provider returns 429 or 503 | Project 1's bounded retries, then the record is recorded as a labelling failure with its error type |
| Some records fail | Their `criteria` is `null`, they are counted by error type, and stage 07 leaves them out. Exit 1 |
| Every record fails | Exit 2 |
