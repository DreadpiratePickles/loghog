# Stage: 03_score — PLANNED

Score every record for how much it would teach, so that selection has something
to sort on other than recency.

## Objective

Attach an explainable score, and the evidence behind it, to every record in a
window — without a model call for any record that arrived with judge verdicts
already attached.

## Inputs

| Path or source | Layer | Authority | Required | Relevant section |
|---|---:|---|---:|---|
| `records/<window>/records.jsonl` | 4 | Authoritative | Yes | Every field |
| `records/<window>/manifest.json` | 4 | Authoritative | Yes | `counts`, for the day's distributions |
| `loghog.toml` `[score.weights]` | 3 | Authoritative | Yes | One integer per signal |
| `regression_detect.judge.criterion` | 3 | Authoritative | No | Only for records with no verdicts |

## Process (planned)

1. Compute the deterministic signals: a failed record; a judge verdict that
   failed; negative feedback; positive feedback contradicting a failed verdict;
   a latency or length outlier against the window's own p95; a non-ASCII ratio
   above a threshold; an injection-pattern hit; a very short input; a record
   whose arm disagrees with another record on the same input.
2. Weight each by an integer from configuration, and record which fired and the
   evidence for each.
3. For records with no verdicts at all, and only for those, one bounded judge
   call per record against feature-level criteria — reusing project 1's
   `judge_criterion` rather than a second judge.

## Outputs (planned)

| Path | Schema or format | Consumer |
|---|---|---|
| `records/<window>/scores.jsonl` | `{record_id, score, signals: [{name, weight, evidence}]}` | Stages 04 and 05 |

## Verify (planned)

- Determinism: the same window scores identically twice, for every signal that
  does not call a model.
- Every signal has a test that fires it alone and a test that does not.
- A score is reproducible from its own signal list and the weights, so a
  disagreement is about a weight rather than about arithmetic nobody can see.

## Approval (planned)

None to compute a score. Scores decide nothing on their own; stage 05 selects
and stage 07 still requires a human to promote.

## Failure Behavior (planned)

| Situation | What happens |
|---|---|
| A window with no records | Nothing written. Exit 2 |
| The judge fails on a record | Recorded as a fact about the judge, with its error type. It never becomes a failed criterion |
| Weights that do not sum to anything sensible | Refused at load: a scoring configuration nobody can read is a ranking nobody can argue with |
