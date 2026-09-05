SYNTHETIC — built from an invented sample log, not from production traffic. No customer wrote any of the text this window holds.

# Drift: `2026-08-24` to `2026-08-31`

loghog 0.1.0. 120 record(s) in the earlier window, 120 in the later one.

Nothing below quotes either window. Cluster ids, counts, rates and one statistic are what a person needs in order to decide whether to mine again, and none of it is anything a person would have to be careful with.

## Rates, with intervals

| | Earlier | Later | Delta | Separated |
|---|---|---|---:|---|
| `error` | 3.3% (1.3%-8.3%) | 13.3% (8.4%-20.6%) | +10.0% | yes |
| `negative_feedback` | 15.0% (9.7%-22.5%) | 30.0% (22.5%-38.7%) | +15.0% | yes |

Intervals are Wilson score intervals, from project 1's `compare` rather than from a second implementation here. **Separated** means the two intervals do not overlap. It is a conservative screen and not a test, and calling it significant would be a claim this tool has not earned.

## Signals

| Signal | Earlier | Later | Delta |
|---|---:|---:|---:|
| `error` | 3.3% | 13.3% | +10.0% |
| `judge_failure` | 0.0% | 0.0% | +0.0% |
| `negative_feedback` | 15.0% | 30.0% | +15.0% |
| `feedback_conflict` | 0.8% | 2.5% | +1.7% |
| `version_disagreement` | 0.0% | 0.0% | +0.0% |
| `injection_pattern` | 3.3% | 3.3% | +0.0% |
| `refusal_pattern` | 2.5% | 2.5% | +0.0% |
| `format_violation` | 0.0% | 0.0% | +0.0% |
| `novelty` | 75.0% | 76.7% | +1.7% |
| `latency_outlier` | 8.3% | 9.2% | +0.8% |
| `length_outlier` | 11.7% | 10.8% | -0.8% |
| `non_ascii_ratio` | 0.8% | 1.7% | +0.8% |
| `tiny_input` | 0.8% | 1.7% | +0.8% |

Every signal is listed, including the ones that never fired: a signal missing from a table reads as "we did not look", and looking and finding nothing is both the commoner and the more useful answer.

## What is new

25 of 82 cluster(s) in `2026-08-31` (30.5%) have no counterpart in `2026-08-24` at an overlap of 0.40.

| Cluster | Size | Best overlap with the earlier window |
|---|---:|---:|
| `c-0002` | 4 | 0.04 |
| `c-0008` | 3 | 0.04 |
| `c-0010` | 3 | 0.10 |
| `c-0013` | 2 | 0.00 |
| `c-0015` | 2 | 0.33 |
| `c-0022` | 2 | 0.21 |
| `c-0023` | 2 | 0.05 |
| `c-0025` | 2 | 0.19 |
| `c-0026` | 2 | 0.10 |
| `c-0032` | 1 | 0.00 |
| `c-0033` | 1 | 0.00 |
| `c-0034` | 1 | 0.00 |
| `c-0043` | 1 | 0.11 |
| `c-0044` | 1 | 0.11 |
| `c-0046` | 1 | 0.11 |
| `c-0047` | 1 | 0.12 |
| `c-0053` | 1 | 0.21 |
| `c-0054` | 1 | 0.12 |
| `c-0060` | 1 | 0.38 |
| `c-0061` | 1 | 0.09 |
| `c-0062` | 1 | 0.17 |
| `c-0066` | 1 | 0.11 |
| `c-0073` | 1 | 0.14 |
| `c-0074` | 1 | 0.10 |
| `c-0075` | 1 | 0.19 |

Ranked by how many people wrote in about each, which is the order somebody would work down. What to do about it is a command a person runs.

## Input length

| | Value |
|---|---:|
| KS statistic | 0.083 |
| Median, earlier | 109 chars |
| Median, later | 108 chars |

The Kolmogorov-Smirnov statistic is the largest gap between the two windows' input-length distributions: 0 means identical, 1 means they do not overlap at all. It is reported as a statistic and not as a p-value, because two windows somebody picked are not a sampling design.

