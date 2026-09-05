# Stage: 04_cluster — BUILT

Group near-duplicates, so that twenty-five tickets about one outage become one
case rather than twenty-five.

## Objective

Partition a scored window into clusters of records that are about the same
thing, with a threshold somebody argued about rather than one buried in code —
and without ever comparing every pair.

Stage 01 already removed *exact* duplicates. This is the harder half: "my lamp
flickers" and "the lamp flickers when bright" are one eval case and two strings.

## Inputs

| Path or source | Layer | Authority | Required | Relevant section |
|---|---:|---|---:|---|
| `records/<window>/records.jsonl` | 4 | Authoritative | Yes | `input_text` |
| `records/<window>/scores.jsonl` | 4 | Authoritative | Yes | `score`, and only to pick a representative |
| `loghog.toml` `[cluster]` | 3 | Authoritative | Yes | All five parameters |

## Process

Five steps, and the fourth is the one people leave out.

1. **Normalise.** Lowercase, collapse whitespace, drop digits, and collapse
   redaction tokens: `[EMAIL_1]` and `[EMAIL_2]` carry the same fact — "an
   address was here" — and the number in them is *which customer wrote in*.
   Leaving it would split one cluster by exactly the thing stage 02 worked to
   make stable.
2. **Shingle.** Five-word phrases. A text with fewer than five words becomes one
   shingle of the whole thing, which is how "too short to shingle falls back to
   exact equality" falls out of one rule rather than out of a second code path
   that could disagree with the first. A text with *no* words yields the empty
   set and is a singleton by construction: two absences are not a match.
3. **Sketch and band.** MinHash over 64 seeded permutations, split into 16 bands
   of 4 rows; two records sharing any whole band are candidates. The base hash
   is BLAKE2b and **not** Python's `hash()`, which is salted per process — an
   implementation built on it passes every unit test and silently repartitions
   the same window on the next run.
4. **Verify exactly.** Every candidate pair gets its true Jaccard computed and is
   merged only if it clears the threshold. Banding is a *blocking* step and its
   curve is a probability; a threshold somebody has to argue with should not be
   one. This is what makes precision exactly 1 against brute force.
5. **Merge with union-find**, by name rather than by rank, so that shuffling the
   window cannot change the partition. The highest-scoring member of a cluster
   is its representative; the rest are recorded as members, never discarded.

Single-linkage merging is transitive: A with B and B with C puts A and C
together even when their own similarity is below the threshold. That is a real
property of this design rather than a bug — a chain of paraphrases is one
complaint — and it is why a cluster publishes the **weakest** link that built it
rather than an average.

## Outputs

| Path | Schema or format | Consumer |
|---|---|---|
| `records/<window>/clusters.json` | `{schema_version, window, params, clusters: [{cluster_id, representative_id, member_ids, size, min_link_jaccard}], exact_comparisons, merged_pairs, wordless_record_ids}` | Stages 05 and 09 |
| `records/<window>/cluster.md` | Markdown: the shape of the partition, the parameters, and nothing from inside it | A human |

## Verify

- **Measured against brute force.** On a synthetic corpus of 70 records — ten
  families of five paraphrases plus twenty unrelated singletons — the exact
  answer is computed by comparing all 2,415 pairs, and the suite asserts
  precision and recall against it. Measured: **precision 1.000, recall 0.960**,
  from 96 exact comparisons instead of 2,415.
- Twenty-five paraphrases of one complaint produce one cluster; two genuinely
  different complaints do not merge at the configured threshold.
- Clustering is order-independent: shuffling the window does not change the
  partition, the labels or their order.
- Signatures are identical across two processes under two values of
  `PYTHONHASHSEED` — the only test that catches a salted base hash.
- The report quotes nothing from the window.

## Approval

None. Nothing is deleted; a suppressed member is recorded as a member.

## Failure Behavior

| Situation | What happens |
|---|---|
| A threshold outside 0-1 | Refused at load |
| Bands that do not divide the permutations | Refused at load: a remainder leaves rows no band ever reads, which loses recall without saying so |
| A window that has not been scored | Refused, naming `loghog score`. Exit 3 |
| No window, or a window with no records | Refused, naming `loghog ingest`. Exit 3 |
| Two records sharing an id | Refused: clustering would put one record in two clusters |
| Every record in one cluster | Said in the report, in bold, with the parameter to change — a single cluster over a whole window means the threshold is wrong, and quietly selecting one case out of it would hide that the rest were thrown away |
| Every cluster a singleton | Also said, as a result rather than a failure: selection has no near-duplicates to spend its budget on |
