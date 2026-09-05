# Stage: 09_drift — BUILT

Compare two windows: what the traffic is doing now that it was not doing then.

## Objective

Answer "has anything changed?" with numbers rather than with a feeling, before
anybody spends a model call deciding what to do about it.

This stage is **out of the pipeline on purpose**. It is numbered last because it
is not a step between 08 and anything; it is a question a person asks about two
windows, and it needs no goldens file, no shortlist and no model. Stage 08
(`08_health`, BUILT) asks the neighbouring question — is the *dataset* still
about the system? — and needs the goldens that this one does not.

## Inputs

| Path or source | Layer | Authority | Required | Relevant section |
|---|---:|---|---:|---|
| `records/<earlier>/records.jsonl` | 4 | Authoritative | Yes | `input_text`, `error`, `feedback` |
| `records/<earlier>/scores.jsonl` | 4 | Authoritative | Yes | `signals[].name` |
| `records/<later>/records.jsonl` | 4 | Authoritative | Yes | Same |
| `records/<later>/scores.jsonl` | 4 | Authoritative | Yes | Same |
| `records/<later>/clusters.json` | 4 | Authoritative | Yes | `representative_id`, `member_ids` |
| `loghog.toml` `[drift]` | 3 | Authoritative | Yes | `novel_cluster_jaccard` |
| `regression_detect.compare` | 3 | Authoritative | Yes | `wilson_interval` |

## Process

Four questions, four answers, none of them a word from either window.

1. **Signal rates.** For each of the thirteen signals, its rate in each window
   and the difference. Every signal is listed, including the ones that never
   fired: a signal missing from a table reads as "we did not look", and looking
   and finding nothing is both the commoner and the more useful answer.
2. **Cluster novelty.** For each cluster in the later window, the best
   shingle-Jaccard between its representative and *every record* in the earlier
   one. Below `novel_cluster_jaccard`, the subject is new. The new clusters are
   ranked by how many people wrote in about each, which is the order somebody
   would work down. The threshold is deliberately **not** `[cluster]
   jaccard_threshold`: merging two records into one case is a stricter claim
   than noticing that a subject has been seen before.
3. **Input length.** A two-sample Kolmogorov-Smirnov statistic, computed in pure
   Python over the two sorted lists of input lengths, plus both medians. It is
   reported as a statistic and **not** as a p-value: two windows a person picked
   are not a sampling design under which a p-value means anything.
4. **Error and negative-feedback rates**, each with a Wilson interval from
   project 1's `compare` — not a second implementation here, because a rate
   computed by two copies of one formula is a disagreement waiting to happen in
   the one place nobody would look. Non-overlapping intervals are reported as
   `separated`, which is a conservative screen and is deliberately not called
   "significant".

## Outputs

| Path | Schema or format | Consumer |
|---|---|---|
| `drift/<earlier>-vs-<later>.md` | Markdown, with the four sections above | A human |
| `drift/<earlier>-vs-<later>.json` | The same numbers, machine-readable | A dashboard, or a CI check |

Neither holds a word from either window: cluster ids, counts, rates and one
statistic. `drift/` is gitignored anyway — a comparison committed without the
windows it compares is evidence of nothing.

## Verify

- Two identical windows report zero new clusters and a KS statistic of 0.
- Two disjoint samples report a KS statistic of 1; the statistic is symmetric
  and ignores the order of each sample.
- `wilson_interval` is asserted to be *project 1's function object*, not a
  reimplementation with the same name.
- Every interval brackets its own rate; a small sample gives a wide one.
- Running it twice writes the same bytes.
- The markdown quotes nothing from either window.

## Approval

None to report. This stage decides nothing, retires nothing and adds nothing. It
names what changed; mining is a command a person runs.

## Failure Behavior

| Situation | What happens |
|---|---|
| The same window named twice | Refused: comparing a window with itself measures nothing. Exit 3 |
| A window that does not exist | Refused by name, with `loghog ingest`. Exit 3 |
| A window that has not been scored or clustered | Refused, naming `loghog score` or `loghog cluster`. Exit 3 |
| A window with no records | Refused: a rate over nothing is not a number. Exit 3 |
| A clusters document naming a representative the window does not hold | Refused, naming the id and `loghog cluster`. Exit 3 |
| More occurrences than records in a window | Refused rather than reported as a rate above 1 |
