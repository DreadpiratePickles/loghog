SYNTHETIC — every criterion in this run is a fixed placeholder. No model was called, nothing read these records, and none of it may be promoted.

# Labels for window `2026-08-24`

loghog 0.1.0. 18 call(s), one per candidate: 18 drafted, 0 failed.

| | |
|---|---|
| Model | `fake-criteria-drafter (dry run)` |
| Drafting prompt | `02a87d6635c7…` |
| Dry run | yes |

Every candidate came back with a usable draft.

## Candidates

| Record | Stratum | Score | Criteria | Draft |
|---|---|---:|---:|---|
| `a-072` | feedback_conflict | 13 | 4 | drafted |
| `a-027` | negative_feedback | 9 | 4 | drafted |
| `a-044` | negative_feedback | 9 | 4 | drafted |
| `a-084` | negative_feedback | 9 | 4 | drafted |
| `a-118` | negative_feedback | 9 | 4 | drafted |
| `a-006` | negative_feedback | 7 | 4 | drafted |
| `a-017` | injection_pattern | 7 | 4 | drafted |
| `a-024` | negative_feedback | 7 | 4 | drafted |
| `a-052` | error | 7 | 4 | drafted |
| `a-061` | injection_pattern | 7 | 4 | drafted |
| `a-093` | injection_pattern | 7 | 4 | drafted |
| `a-023` | refusal_pattern | 6 | 4 | drafted |
| `a-089` | refusal_pattern | 6 | 4 | drafted |
| `a-105` | refusal_pattern | 6 | 4 | drafted |
| `a-007` | novelty | 5 | 4 | drafted |
| `a-051` | novelty | 5 | 4 | drafted |
| `a-059` | novelty | 5 | 4 | drafted |
| `a-075` | novelty | 5 | 4 | drafted |

The criteria themselves are in `labels.jsonl`, and in the review document `loghog emit` writes. They are not here: a drafted criterion paraphrases the case it came from, and this file is the one that goes in a ticket.

Nothing above has been read by a human. `loghog emit` turns these into drafts and `loghog promote` is the only thing that adopts one.

