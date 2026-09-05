# Stage: 05_select — BUILT

Choose the set — highest signal, one per cluster, and stratified so the dataset
is not all of one failure.

## Objective

Turn a scored, clustered window into a shortlist of a stated size, with the
reason each record was chosen recorded beside it — and, more importantly, with
**every record that did not make it accounted for by exactly one named cap**.

A shortlist whose omissions are unexplained is a shortlist nobody can trust to
be representative, and representativeness is the only property it has.

## Inputs

| Path or source | Layer | Authority | Required | Relevant section |
|---|---:|---|---:|---|
| `records/<window>/records.jsonl` | 4 | Authoritative | Yes | The text a candidate carries |
| `records/<window>/scores.jsonl` | 4 | Authoritative | Yes | `score`, `signals` |
| `records/<window>/clusters.json` | 4 | Authoritative | Yes | `member_ids` |
| `loghog.toml` `[select]` | 3 | Authoritative | Yes | `max_candidates`, `max_per_cluster` |
| `loghog.toml` `[select.quotas]` | 3 | Authoritative | Yes | One integer per stratum, `ordinary` included |
| A goldens file, via `--existing` | 3 | Advisory | No | Read with project 1's `load_goldens` |

## Process

1. **Order** every scored record by descending score, then by record id. Nothing
   after this depends on the order a file happened to be written in.
2. **Apply four caps, in this order**, and the order is the design:
   1. **already in the goldens** — a case you have is not a case to mine, and it
      must not consume the slot a new one needed. First, so it never does.
   2. **the cluster cap** — twenty-five tickets about Tuesday's outage are one
      case. At `max_per_cluster = 1` the record that survives a cluster is its
      highest-scoring member, which is exactly the representative stage 04 named.
   3. **the stratum quota** — a record's stratum is its highest-weighted signal,
      ties broken by the fixed registry order, or `ordinary` if it fired none.
      A pure top-N by score is a dataset made entirely of the loudest failure
      mode of that week, which then measures one thing N times.
   4. **the global cap** — last, so that it is only ever blamed for records that
      would otherwise have been taken.
3. **Count every refusal by cap**, and report the shortfall of every stratum
   that could not be filled. A shortfall is **never** topped up from another
   stratum: borrowing against it would quietly restore the monoculture the
   quotas exist to prevent.

## Outputs

| Path | Schema or format | Consumer |
|---|---|---|
| `selected/<window>/candidates.jsonl` | `{rank, record_id, score, stratum, cluster_id, cluster_size, reasons, input_text, output_text}` | Stage 06 |
| `selected/<window>/selection.md` | Markdown: the caps, the count refused by each, the strata table, the shortfalls, and the shortlist by id | A human |

The division is deliberate. `candidates.jsonl` carries the redacted case,
because stage 06 needs the text to draft criteria against; `selection.md` is the
file somebody pastes into a ticket and carries **no text from the window at
all**. `selected/` is gitignored for the same reason `records/` is.

## Verify

- A window of one failure mode cannot fill more than its stratum's quota.
- Deterministic: same inputs, same shortlist, same order, same bytes.
- An existing goldens file genuinely suppresses, and a suppressed case does not
  spend a quota — asserted by comparing two runs over one window.
- Every drop reason appears in the summary with its count.
- `selection.md` quotes no case text.

## Approval

None to select. Selection proposes; stage 07 still requires a named human to
promote anything into a dataset.

## Failure Behavior

| Situation | What happens |
|---|---|
| A window that has not been scored | Refused, naming `loghog score`. Exit 3 |
| A window that has not been clustered | Refused, naming `loghog cluster`. Exit 3 |
| A scores file naming a record the window does not hold | Refused, naming the record and the command. Exit 3 |
| A record with no score, or in no cluster | Refused, never silently left out of the ranking |
| `--max-candidates` below 1 | Refused |
| The global cap truncated the shortlist | Exit **1**: there was more worth having and the cap stopped it, which is exactly when somebody should read the report |
| A stratum that could not be filled | Named in the summary and on the terminal, and the exit code stays 0 — most windows contain no injection attempts, and a code that was 1 on nearly every run would stop being read |
| Nothing selected at all | Exit 2. An empty shortlist is not a shortlist |
