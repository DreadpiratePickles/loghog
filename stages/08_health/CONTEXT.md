# Stage: 08_health — BUILT

Report on the dataset itself: what it covers, what it has stopped covering, and
what to mine or retire next.

## Objective

Answer the question nobody asks until it is too late — "is this eval set still
about the system we are running?" — with numbers and an interval rather than a
feeling.

The neighbouring question, "has the *traffic* moved?", belongs to `09_drift`,
which needs no goldens file to answer it. The two are kept apart on purpose: you
must be able to ask whether anything changed *before* you have a dataset to
compare against.

## Inputs

| Path or source | Layer | Authority | Required | Relevant section |
|---|---:|---|---:|---|
| A goldens file | 3 | Authoritative | Yes | Every case, via `load_goldens` |
| `records/<window>/records.jsonl` | 4 | Authoritative | Yes | `input_text` |
| `records/<window>/clusters.json` | 4 | Authoritative | Yes | Built by stage 04 |
| `records/<window>/scores.jsonl` | 4 | Authoritative | Yes | Which signals fired, and the score inside each cluster |
| `records/<window>/manifest.json` | 4 | Authoritative | Yes | Whether the window is synthetic |
| `loghog.toml` | 3 | Authoritative | Yes | `[health] neighbour_jaccard`, `max_recommendations` |
| `regression_detect.compare` | 3 | Authoritative | Yes | `wilson_interval` and `fisher_exact_one_sided` |

## Process

1. **Coverage.** What fraction of the window's clusters has a golden case within
   `neighbour_jaccard`? With a Wilson interval from project 1, because a coverage
   figure computed from eighty clusters is not a point. A cluster counts as
   covered when **any** member has a case near it, not when its representative
   does: single-linkage merging is transitive, so a representative can be several
   links from the member a case actually matches.
2. **The comparison that matters.** Coverage of clusters where a signal fired
   against clusters where none did, with `fisher_exact_one_sided`. A dataset that
   covers the dull traffic and misses the interesting traffic passes every
   release and catches nothing. **`novelty` does not count as a signal here**, and
   only here: it is a property of the dataset rather than of the traffic, and
   counting it would make the comparison read "clusters the dataset does not
   cover are covered less often than the ones it does".
3. **Gaps.** Which clusters have no case at all, ranked by size, then by the
   loudest score inside them, then by id — the list of what to mine next, capped
   at `max_recommendations`.
4. **Signal coverage.** For each of the thirteen signals, how many records fired
   it and how many of those are in a covered cluster. Every signal has a row,
   including the ones that never fired, because a missing row reads as "we did
   not look".
5. **Staleness.** Which cases have no traffic within `neighbour_jaccard` — the
   same relation as coverage, read from the other end, and sharing the same
   threshold so the report cannot contradict itself.
6. **Redundancy.** Which cases are near-duplicates of each other, ranked by
   similarity — the list of what to retire.

## Outputs

| Path | Schema or format | Consumer |
|---|---|---|
| `health/<window>.md` | Markdown, six sections in the order somebody acts in | A human |
| `health/<window>.json` | The same numbers, machine-readable, schema version 1 | A dashboard, or a CI check |

Neither holds a word from the traffic or from the dataset. Cluster ids, case ids,
counts, shares and thresholds are what a person needs to decide what to mine
next, and none of it is anything they have to be careful with. Both carry a
`SYNTHETIC` banner when the window was built from an invented log.

## Verify

- A dataset that covers everything reports 1.0 with an interval that includes it,
  and that interval **is** `wilson_interval(covered, total)` — asserted against
  project 1's function rather than recomputed.
- An empty match reports 0.0 and does not divide by zero.
- The gap list is deterministic and ordered by cluster size.
- Every signal has a row, asserted against `SIGNAL_NAMES` in order.
- Re-scoring the window with `--existing` — which makes `novelty` fire almost
  everywhere — does not change the signalled/ordinary split. That test is the one
  that fails if the circularity creeps back in.
- Neither output quotes the traffic or the dataset.
- A second run writes identical bytes.

## Approval

None to report. This stage decides nothing, retires nothing and adds nothing. It
names the command a human would run, which is `loghog promote`.

**It has no unhealthy exit code**, deliberately. The threshold at which a dataset
becomes unhealthy is a decision this stage does not make, and encoding one in an
exit code would make it — quietly, in a constant, for everybody who runs it.

## Failure Behavior

| Situation | What happens |
|---|---|
| The goldens file is absent | Refused: coverage against nothing is not a number. Exit 3 |
| The goldens file will not load | Refused, carrying **project 1's own error message**. Exit 3 |
| No window, or an empty one | Refused, naming `loghog ingest`. Exit 3 |
| The window has not been scored or clustered | Refused, naming the command that fixes it. Exit 3 |
| Zero clusters covered | Reported as zero with the interval it deserves, never as a crash. Exit 0 |
