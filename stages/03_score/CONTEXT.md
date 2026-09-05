# Stage: 03_score — BUILT

Score every record for how much it would teach, so that selection has something
to sort on other than recency.

## Objective

Attach an explainable score, and the evidence behind it, to every record in a
window — deterministically, with no model call anywhere, and with an honest
account of every signal that could not be evaluated at all.

Thirteen signals, each a function from a record and its window to a sentence or
to nothing. A score is the **sum of the weights of the signals that fired**, and
nothing else: no normalisation, no decay, no multiplication. That constraint is
the whole design. A ranking somebody can recompute by hand from the list printed
beside it is a ranking somebody can argue with, and an argument about a weight
is a one-line diff in a reviewed file.

## Inputs

| Path or source | Layer | Authority | Required | Relevant section |
|---|---:|---|---:|---|
| `records/<window>/records.jsonl` | 4 | Authoritative | Yes | Every field |
| `records/<window>/manifest.json` | 4 | Authoritative | Yes | `dedupe_enabled`, `sources[].expect_output_json` |
| `loghog.toml` `[score]` | 3 | Authoritative | Yes | Thresholds and the feedback vocabularies |
| `loghog.toml` `[score.weights]` | 3 | Authoritative | Yes | One non-negative integer per signal |
| `loghog.toml` `[cluster] shingle_words` | 3 | Authoritative | Yes | Only for `novelty`'s comparison |
| A goldens file, via `--existing` | 3 | Advisory | No | Read with project 1's `load_goldens` |

## Process

1. **Read the window.** Every record, validated on the way in; a corrupt line
   stops the read rather than being skipped.
2. **Build the context once.** Three signals are not properties of a record at
   all — an outlier needs a distribution, a version disagreement needs two
   records, novelty needs a dataset — so the window-level facts are computed
   once and scoring a record is then a pure function of the record and them.
3. **Record what cannot be evaluated, and why.** Two kinds, kept apart:
   - an **absence somebody chose** — no goldens file, no mapping declaring JSON,
     a window too small for a percentile;
   - an **impediment the window imposes** — it was deduplicated on the input, so
     two prompt versions answering one question are already one record; or its
     sources disagree about whether outputs should parse as JSON.
4. **Score every record**, in registry order, with the evidence for each signal.
5. **Write both files.** `scores.jsonl` for stages 04 and 05, `score.md` for a
   person.

### The thirteen signals

| Signal | Fires when |
|---|---|
| `error` | The call failed |
| `judge_failure` | A judged criterion did not pass |
| `negative_feedback` | The feedback value is in `negative_feedback_words` |
| `feedback_conflict` | Positive feedback *and* a failure. The most interesting record in any log: one of the two judgements is miscalibrated |
| `version_disagreement` | One input, two prompt versions, different outcomes |
| `injection_pattern` | The input matches one of four fixed injection patterns |
| `refusal_pattern` | The output matches one of three fixed refusal patterns |
| `format_violation` | The mapping declares `[expect] output_json` and the output does not parse |
| `novelty` | Best shingle-Jaccard against every existing golden case is below the threshold |
| `latency_outlier` | At or beyond the window's own p95 latency |
| `length_outlier` | Input or output at or beyond the window's own p95 length |
| `non_ascii_ratio` | More non-ASCII than the threshold: another language, or mojibake |
| `tiny_input` | Shorter than `tiny_input_chars` |

The patterns are code, in a fixed registry with tests naming what each is for,
for the reason extractors are: a regex read from a file is a regex nobody
reviewed, and a badly written one is a run that never finishes. The *weights*
are configuration, because those are the argument.

## Outputs

| Path | Schema or format | Consumer |
|---|---|---|
| `records/<window>/scores.jsonl` | `{record_id, score, signals: [{name, weight, evidence}]}` | Stages 04 and 05 |
| `records/<window>/score.md` | Markdown: what fired, what could not be evaluated, the thresholds and the weights | A human |

Both are mode 0600 under the window's 0700 directory, and both are **replaced**
rather than appended: a derived artefact re-computed under different weights
must describe the window, not be two files stapled together.

## Verify

- Every signal has a test that fires it alone and a test that does not.
- A score equals the sum of the weights beside it, checked on every written line.
- Scoring one window twice writes identical bytes.
- Evidence never quotes the record: named patterns, counts and thresholds only,
  asserted per signal and over the whole report.
- The registry and the configuration cannot drift: a test asserts every name in
  `SIGNAL_NAMES` has a function and a weight.
- Twelve of the thirteen fire on the committed judged sample, by exact count.

## Approval

None to compute a score. Scores decide nothing on their own; stage 05 selects
and stage 07 still requires a named human to promote.

## Failure Behavior

| Situation | What happens |
|---|---|
| No window, or a window with no records | Refused, naming `loghog ingest`. Exit 3 |
| A manifest at a schema version this build does not read | Refused, naming the version. Exit 3 |
| A goldens file that will not load | Refused with project 1's own error. Losing the comparison quietly would propose cases the dataset already holds and call them novel. Exit 3 |
| A goldens file that loads and holds no cases | Refused: every record would be novel, which is a suppression rule that silently does nothing. Exit 3 |
| A signal silenced by the window itself | Named in the report as **blocking**, and the run exits **1** |
| A signal absent because somebody chose so | Named in the report, and the run exits 0 |
| Weights that are all zero | Refused at load: every record would score zero and selection would be alphabetical |
