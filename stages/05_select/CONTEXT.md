# Stage: 05_select — PLANNED

Choose the set — highest signal, one per cluster, and stratified so the dataset
is not all of one failure.

## Objective

Turn a scored, clustered window into a shortlist of a stated size, with the
reason each record was chosen recorded beside it.

## Inputs

| Path or source | Layer | Authority | Required | Relevant section |
|---|---:|---|---:|---|
| `records/<window>/scores.jsonl` | 4 | Authoritative | Yes | `score`, `signals` |
| `records/<window>/clusters.json` | 4 | Authoritative | Yes | `representative_id` |
| An existing goldens file | 3 | Advisory | No | To avoid proposing cases already held |
| `loghog.toml` `[select]` | 3 | Authoritative | Yes | `max_cases`, `[select.strata]` |

## Process (planned)

1. One candidate per cluster: its representative.
2. Suppress anything similar to a case an existing goldens file already holds.
3. **Stratify.** A pure top-N by score produces a dataset made entirely of the
   loudest failure mode, which then measures one thing. Quotas per stratum —
   failures, disagreements, negative feedback, ordinary traffic — are what stop
   an eval set from being a monoculture.
4. Fill each stratum by score, and report any stratum that could not be filled
   rather than quietly borrowing from another.

## Outputs (planned)

| Path | Schema or format | Consumer |
|---|---|---|
| `records/<window>/selection.json` | `{selected: [{record_id, stratum, score, why}], unfilled: [...]}` | Stage 06 |

## Verify (planned)

- A window of one failure mode cannot fill more than its stratum's quota.
- Deterministic: same inputs, same selection, same order.
- An existing goldens file genuinely suppresses: the same case is not proposed
  twice across two runs.

## Approval (planned)

None to select. Selection proposes; stage 07 still requires a named human.

## Failure Behavior (planned)

| Situation | What happens |
|---|---|
| Fewer candidates than `max_cases` | All of them, and the shortfall is reported |
| A stratum that cannot be filled | Named in `unfilled`, never silently topped up from another |
| A configured goldens file that will not load | Refused, not skipped: losing deduplication quietly proposes cases you already have |
