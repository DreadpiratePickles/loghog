# Stage: 06_label — PLANNED

The one stage that calls a model: draft checkable criteria for each selected
record.

## Objective

For each selected record, produce three to five plain-English criteria that a
judge could check — at least one of them negative — as strict JSON, with exactly
one bounded model call per record.

## Inputs

| Path or source | Layer | Authority | Required | Relevant section |
|---|---:|---|---:|---|
| `selected/<window>/candidates.jsonl` | 4 | Authoritative | Yes | One object per chosen case: `record_id`, `stratum`, `score`, `reasons`, `input_text`, `output_text` |
| `records/<window>/records.jsonl` | 4 | Authoritative | Yes | `input_text`, `output_text` |
| `src/loghog/config.py` | 3 | Authoritative | Yes | `LABEL_MODEL_REF` |
| `.env` | — | Authoritative | Yes, for a live run | `GEMINI_API_KEY`, loaded by the runtime |

## Process (planned)

1. Build the provider through project 1's seam:
   `providers.gemini.gemini_provider_from_env(model_id_for_ref(LABEL_MODEL_REF))`.
   `--dry-run` substitutes `FakeProvider` and a fixed `[SYNTHETIC]` placeholder
   list instead, and says so on its first line of output.
2. One call per selected record, paced with `regression_detect.pacing.pace` under
   `--min-interval-ms`, because provider quotas are per minute and bounded
   retries cannot ride out a window that long.
3. Parse strictly. Model output is untrusted input: a reply that is not the
   expected JSON is a typed error and the record is labelled a failure, never
   given an empty criteria list.

**One bounded call per record, and no agent loop.** The bound is the whole
design: a labelled dataset whose cost is proportional to something other than
the number of records is a dataset nobody will rebuild.

## Outputs (planned)

| Path | Schema or format | Consumer |
|---|---|---|
| `records/<window>/labels.jsonl` | `{record_id, criteria: [str], model_id, dry_run}` | Stage 07 |

## Verify (planned)

- A dry run makes no network call at all, asserted by handing in a provider that
  raises if called.
- A malformed reply is a typed failure with the record named, and does not
  become an empty criteria list.
- The call count equals the record count. Exactly.

## Approval (planned)

**A drafted criterion is never adopted here.** Stage 07 emits drafts and a named
human promotes them. Adopting a criterion written by a model, from customer text,
unread, would let the system quietly define what "correct" means for every later
evaluation.

## Failure Behavior (planned)

| Situation | What happens |
|---|---|
| No API key | `ProviderConfigError` from project 1's seam, with an actionable message that never contains a key. Exit 3 |
| The provider returns 429 or 503 | Bounded retries with backoff, then the record is recorded as a labelling failure with its error type |
| Every record fails to label | Nothing written. Exit 2 |
| Some records fail | Those records are absent from `labels.jsonl` and listed with their error type. Exit 1 |
