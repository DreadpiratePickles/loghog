# Stage: 04_cluster — PLANNED

Group near-duplicates, so that twenty-five tickets about one outage become one
case rather than twenty-five.

## Objective

Partition a scored window into clusters of records that are about the same
thing, with a threshold somebody argued about rather than one buried in code.

Stage 01 already removed *exact* duplicates. This is the harder half: "my lamp
flickers" and "the lamp flickers when bright" are one eval case and two strings.

## Inputs

| Path or source | Layer | Authority | Required | Relevant section |
|---|---:|---|---:|---|
| `records/<window>/records.jsonl` | 4 | Authoritative | Yes | `input_text` |
| `records/<window>/scores.jsonl` | 4 | Authoritative | Yes | `score`, to pick a representative |
| `loghog.toml` `[cluster]` | 3 | Authoritative | Yes | `jaccard_threshold`, `shingle_words` |

## Process (planned)

1. Normalise: lowercase, collapse whitespace, strip digits.
2. Take word shingles and compare by Jaccard similarity. Deliberately not
   embeddings: an embedding threshold is a number nobody can explain, and a
   shingle overlap is one anybody can check by hand.
3. Texts too short to shingle fall back to exact equality.
4. The highest-scoring record in a cluster is its representative; the rest are
   recorded as its members, not thrown away.

## Outputs (planned)

| Path | Schema or format | Consumer |
|---|---|---|
| `records/<window>/clusters.json` | `{clusters: [{representative_id, member_ids, similarity}]}` | Stage 05 |

## Verify (planned)

- Twenty-five paraphrases of one complaint produce one cluster.
- Two genuinely different complaints do not merge at the configured threshold.
- Clustering is order-independent: shuffling the window does not change the
  partition.

## Approval (planned)

None. Nothing is deleted; a suppressed member is recorded as a member.

## Failure Behavior (planned)

| Situation | What happens |
|---|---|
| A threshold outside 0-1 | Refused at load |
| Every record in one cluster | Reported loudly rather than quietly selected from: a single cluster means the threshold is wrong |
