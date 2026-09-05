# Stage: 08_health — PLANNED

Report on the dataset itself: what it covers, what it has stopped covering, and
how far the traffic has moved since it was built.

## Objective

Answer the question nobody asks until it is too late — "is this eval set still
about the system we are running?" — with numbers and an interval rather than a
feeling.

## Inputs

| Path or source | Layer | Authority | Required | Relevant section |
|---|---:|---|---:|---|
| A goldens file | 3 | Authoritative | Yes | Every case, via `load_goldens` |
| `records/<window>/` for a recent window | 4 | Authoritative | Yes | Records and clusters |
| `regression_detect.compare` | 3 | Authoritative | Yes | `wilson_interval` |

## Process (planned)

1. **Coverage.** What fraction of recent traffic clusters has a golden case
   within the configured similarity? With a Wilson interval, because a coverage
   figure computed from four hundred records is not a point.
2. **Staleness.** How old is each case, and how much recent traffic still looks
   like it?
3. **Drift.** Which clusters in recent traffic have no case at all, ranked by
   size — the list of what to mine next.
4. **Redundancy.** Which cases are near-duplicates of each other, ranked by
   similarity — the list of what to retire.

## Outputs (planned)

| Path | Schema or format | Consumer |
|---|---|---|
| `runs/health/<ts>/health.md` | Markdown, with the four sections above | A human |
| `runs/health/<ts>/health.json` | The same numbers, machine-readable | A dashboard, or a CI check |

## Verify (planned)

- A goldens file that covers everything reports coverage 1.0 with an interval
  that includes it.
- An empty goldens file reports 0.0 and does not divide by zero.
- The drift list is deterministic and ordered by cluster size.

## Approval (planned)

None to report. This stage decides nothing, retires nothing, and adds nothing.
It names the command a human would run, which is stage 07's `promote`.

## Failure Behavior (planned)

| Situation | What happens |
|---|---|
| The goldens file will not load | Refused, with project 1's own error. Exit 3 |
| No recent window | Refused: coverage against nothing is not a number. Exit 2 |
| Zero cases | Reported as zero coverage with the interval it deserves, never as a crash |
