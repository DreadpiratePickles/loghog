SYNTHETIC — built from an invented sample log, not from production traffic. No customer wrote any of the text this window holds.

# Dataset health: `goldens.handwritten.yaml` against window `2026-08-31`

loghog 0.1.0. 4 case(s) checked against 82 cluster(s) of traffic, at a neighbour threshold of 0.6.

Dataset SHA-256 `d2eed00abdce…`. Coverage and staleness share that one threshold on purpose: they are the same relation read from both ends, and two numbers would let this report contradict itself.

## Coverage

**6 of 82 clusters** (7%) have a case within 0.6. Wilson interval 3% to 15% — a coverage figure computed from a handful of clusters is not a point, and this one uses project 1's interval rather than a second implementation of the same formula.

A cluster counts as covered when **any** record in it has a case near it, not when its representative does. Merging is transitive, so a representative can be several links from the member a case actually matches.

## Is it covering the traffic that matters?

| Clusters | Covered | Of | Share |
|---|---:|---:|---:|
| Something fired | 5 | 50 | 10% |
| Nothing fired | 1 | 32 | 3% |

One-sided Fisher exact p = 0.955: the chance of the signalled half being covered this badly if both halves were covered at one and the same rate. Small means the dataset is covering the dull traffic and missing the interesting traffic, which is the failure that passes every release and catches nothing.

It is a p-value and is called one, because both counts are here and the arithmetic is exact. It is still a comparison between two groups somebody's clustering produced, not a designed experiment.

`novelty` does not count as something firing, here and only here. It is a property of the dataset rather than of the traffic — a record is novel when no case looks like it — so counting it would make this read "clusters the dataset does not cover are covered less often than the ones it does", which is true of every dataset ever built.

## What to mine next

76 cluster(s) have no case at all. The biggest are the ones where the most people wrote in about something this dataset cannot measure.

| Cluster | Records | Best overlap | Top score | Signals |
|---|---:|---:|---:|---|
| `c-0001` | 4 | 0.00 | 11 | `error`, `negative_feedback`, `novelty` |
| `c-0002` | 4 | 0.00 | 9 | `error`, `negative_feedback`, `novelty`, `latency_outlier` |
| `c-0004` | 3 | 0.00 | 7 | `negative_feedback`, `novelty` |
| `c-0007` | 3 | 0.00 | 7 | `error`, `novelty` |
| `c-0008` | 3 | 0.00 | 7 | `negative_feedback`, `refusal_pattern`, `novelty` |
| `c-0010` | 3 | 0.00 | 5 | `novelty`, `latency_outlier` |
| `c-0005` | 3 | 0.00 | 3 | `novelty` |
| `c-0006` | 3 | 0.53 | 0 | — |
| `c-0024` | 2 | 0.00 | 13 | `error`, `negative_feedback`, `novelty`, `length_outlier` |
| `c-0015` | 2 | 0.00 | 9 | `error`, `novelty`, `length_outlier` |

Ranked by size, then by the loudest score inside the cluster, then by id — so two runs over one window produce the same list.

## Signal coverage

Every signal has a row, including the ones that never fired. A missing row reads as "we did not look".

| Signal | Records | Covered | Share |
|---|---:|---:|---:|
| `error` | 16 | 1 | 6% |
| `judge_failure` | 0 | 0 | — |
| `negative_feedback` | 36 | 2 | 6% |
| `feedback_conflict` | 3 | 1 | 33% |
| `version_disagreement` | 0 | 0 | — |
| `injection_pattern` | 4 | 0 | 0% |
| `refusal_pattern` | 3 | 0 | 0% |
| `format_violation` | 0 | 0 | — |
| `novelty` | 92 | 0 | 0% |
| `latency_outlier` | 11 | 0 | 0% |
| `length_outlier` | 13 | 2 | 15% |
| `non_ascii_ratio` | 2 | 0 | 0% |
| `tiny_input` | 2 | 0 | 0% |

A signal with records and zero covered is a kind of failure this dataset has no case about at all.

## Staleness

**0 of 4 cases** (0%) have nothing in this window that looks like them.

Every case still has traffic near it.

## Redundancy

No two cases in this dataset are near-duplicates of each other at 0.6.

## What this decides

Nothing. It retires no case, adds no case and changes no file. The command that adds one is `loghog promote`, and it needs a name.

