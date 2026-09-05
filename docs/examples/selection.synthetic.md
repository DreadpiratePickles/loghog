SYNTHETIC — built from an invented sample log, not from production traffic. No customer wrote any of the text this window holds.

# Selection for window `2026-08-24`

loghog 0.1.0. 18 candidate(s) chosen from 120 scored record(s); 102 refused by a named cap.

Every record that is not on the shortlist was refused by exactly one cap, and every cap has a count below. A shortlist whose omissions are unexplained is a shortlist nobody can trust to be representative, which is the only property it is supposed to have.

## Caps

| | Value |
|---|---:|
| Candidates, at most | 40 |
| Per cluster, at most | 1 |

## What was dropped, and by which cap

| Cap | Records | What it means |
|---|---:|---|
| `already_in_goldens` | 30 | a golden case already covers it, so it is not a case to mine |
| `cluster_cap` | 10 | its cluster was already full; the higher-scoring member speaks for it |
| `quota:injection_pattern` | 1 | the `injection_pattern` quota was already met |
| `quota:negative_feedback` | 7 | the `negative_feedback` quota was already met |
| `quota:novelty` | 54 | the `novelty` quota was already met |

## Strata

A record's stratum is the highest-weighted signal it fired, or `ordinary` if it fired none. Quotas are what stop a top-N by score from producing a dataset made entirely of one week's loudest failure.

| Stratum | Quota | Chosen | Unfilled |
|---|---:|---:|---:|
| `error` | 6 | 1 | 5 |
| `judge_failure` | 8 | 0 | 8 |
| `negative_feedback` | 6 | 6 | 0 |
| `feedback_conflict` | 4 | 1 | 3 |
| `version_disagreement` | 4 | 0 | 4 |
| `injection_pattern` | 3 | 3 | 0 |
| `refusal_pattern` | 3 | 3 | 0 |
| `format_violation` | 3 | 0 | 3 |
| `novelty` | 4 | 4 | 0 |
| `latency_outlier` | 2 | 0 | 2 |
| `length_outlier` | 2 | 0 | 2 |
| `non_ascii_ratio` | 2 | 0 | 2 |
| `tiny_input` | 1 | 0 | 1 |
| `ordinary` | 6 | 0 | 6 |

## Unfilled

10 stratum/strata could not be filled: `error` (5 short), `judge_failure` (8 short), `feedback_conflict` (3 short), `version_disagreement` (4 short), `format_violation` (3 short), `latency_outlier` (2 short), `length_outlier` (2 short), `non_ascii_ratio` (2 short), `tiny_input` (1 short), `ordinary` (6 short).

A shortfall is **never** topped up from another stratum. An unfilled quota is a fact about the traffic — most windows contain no injection attempts — and borrowing against it would quietly turn the dataset back into the monoculture the quotas exist to prevent.

## The shortlist

| Rank | Record | Score | Stratum | Cluster | Cluster size |
|---:|---|---:|---|---|---:|
| 1 | `a-072` | 13 | `feedback_conflict` | `c-0018` | 2 |
| 2 | `a-027` | 9 | `negative_feedback` | `c-0036` | 1 |
| 3 | `a-044` | 9 | `negative_feedback` | `c-0045` | 1 |
| 4 | `a-084` | 9 | `negative_feedback` | `c-0001` | 5 |
| 5 | `a-118` | 9 | `negative_feedback` | `c-0084` | 1 |
| 6 | `a-006` | 7 | `negative_feedback` | `c-0025` | 1 |
| 7 | `a-017` | 7 | `injection_pattern` | `c-0030` | 1 |
| 8 | `a-024` | 7 | `negative_feedback` | `c-0035` | 1 |
| 9 | `a-052` | 7 | `error` | `c-0008` | 3 |
| 10 | `a-061` | 7 | `injection_pattern` | `c-0054` | 1 |
| 11 | `a-093` | 7 | `injection_pattern` | `c-0073` | 1 |
| 12 | `a-023` | 6 | `refusal_pattern` | `c-0034` | 1 |
| 13 | `a-089` | 6 | `refusal_pattern` | `c-0021` | 2 |
| 14 | `a-105` | 6 | `refusal_pattern` | `c-0077` | 1 |
| 15 | `a-007` | 5 | `novelty` | `c-0005` | 3 |
| 16 | `a-051` | 5 | `novelty` | `c-0048` | 1 |
| 17 | `a-059` | 5 | `novelty` | `c-0053` | 1 |
| 18 | `a-075` | 5 | `novelty` | `c-0062` | 1 |

The cases themselves are in `candidates.jsonl`, which holds the redacted text because the next stage needs it. This file holds none, because this is the one somebody will paste into a ticket.

