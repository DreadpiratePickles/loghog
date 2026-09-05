SYNTHETIC — every number in this file was produced from two invented log files. No
model was called, nothing here is a measurement, and no customer wrote any of the text
these numbers are about.

# SYNTHETIC — the whole pipeline, offline, end to end

**Nothing in this file is a measurement.** Every command below ran against
`logs/demo_window_a.jsonl` and `logs/demo_window_b.jsonl`, which are 240 invented
records with the personal data, injections and refusals planted in them
deliberately. `loghog label` ran with `--dry-run`, which calls nothing and writes
a fixed placeholder list identical for every case. The transcript demonstrates
that the *machinery* composes. It says nothing about any real system.

Recorded 2026-09-05 in a throwaway copy of the repository: `loghog.toml` and
`mappings/` copied into an empty directory, every command pointed at that copy
with `--config`, and `[dedupe] dedupe = false` set in the copy so the two windows
keep their near-duplicates instead of collapsing them. The committed tree is
therefore untouched, and the CI job asserts that. Two cosmetic edits to the pasted
output: the temporary directory is written `<demo>`, and the shell wrapper that
echoed each command and its exit code is not shown.

## The five things worth reading it for

**`select` names every cap.** Thirty records were refused because the goldens file
already holds a case like them, ten because their cluster was full, sixty-two by a
stratum quota. Every record that is not on the shortlist was refused by exactly one
named cap, and they add up.

**`promote` refuses the drafts.** This is the important line in the file. The
candidates file says "do not promote them" in its first three lines, and a tool
that prints that and then does it anyway has taught its operator that its warnings
are decorative. So the refusal is enforced: any case still carrying `[SYNTHETIC]`
is turned away by id, and exit 3 is what a dry run's output is worth.

**`health` is honest about a nearly empty dataset.** Four hand-written cases
against eighty-two clusters is seven per cent coverage with a Wilson interval from
three to fifteen, and the report says so rather than rounding it into a verdict.
The Fisher comparison of signalled against ordinary clusters comes back at
p = 0.955 — there is no evidence the interesting traffic is covered worse, and
with counts this small there would not be.

**`drift` sees the bad week.** The error rate goes from 3.3% to 13.3% and the
intervals separate; thirty per cent of the later window's subjects are ones the
earlier window never saw. That is what window B was built to contain, and a
comparison that missed it would mean the stage is broken.

**`score` says what it could not evaluate.** `format_violation` is absent from
both windows and named both times, because the generic chat mapping declares no
output contract. A tidy `0` there would read as "we looked and found none".

## The transcript

```console
$ loghog ingest --input logs/demo_window_a.jsonl --format jsonl --mapping openai_chat_jsonl --window 2026-08-24 --synthetic
SYNTHETIC — built from an invented sample log, not from production traffic. No customer wrote any of the text this window holds.
Window '2026-08-24' at <demo>/records/2026-08-24
  120 line(s) read: 120 row(s), 0 blank, 0 unparsed
  120 record(s) written, 0 deduplicated, 0 invalid
  redaction: 11 replacement(s)
  ADDRESS  1
  CARD     2
  EMAIL    2
  IBAN     1
  IPV4     1
  NAME     2
  PHONE    1
  SSN      1
  the full report is in ingest.md
[exit 0]

$ loghog score --window 2026-08-24 --existing docs/examples/goldens.handwritten.yaml
SYNTHETIC — built from an invented sample log, not from production traffic. No customer wrote any of the text this window holds.
Window '2026-08-24': 120 record(s) scored, 104 of which fired at least one signal.
  error  4
  negative_feedback  18
  feedback_conflict  1
  injection_pattern  4
  refusal_pattern  3
  novelty  90
  latency_outlier  10
  length_outlier  14
  non_ascii_ratio  1
  tiny_input  1
  not evaluated: format_violation — no mapping in this window declares [expect] output_json, so nothing here claims its output should parse.
  the full report is in score.md
[exit 0]

$ loghog cluster --window 2026-08-24
Window '2026-08-24': 84 cluster(s), 61 singleton(s), largest 5.
  131 pair(s) compared exactly, 41 merged at a Jaccard of 0.6 or more
  the full report is in cluster.md
[exit 0]

$ loghog select --window 2026-08-24 --existing docs/examples/goldens.handwritten.yaml
Window '2026-08-24': 18 candidate(s) of 120 scored record(s), at most 40 and at most 1 per cluster.
  error  1 of 6
  negative_feedback  6 of 6
  feedback_conflict  1 of 4
  injection_pattern  3 of 3
  refusal_pattern  3 of 3
  novelty  4 of 4
  dropped, by cap:
    already_in_goldens  30
    cluster_cap  10
    quota:injection_pattern  1
    quota:negative_feedback  7
    quota:novelty  54
  unfilled strata, never topped up from another: error (5 short), judge_failure (8 short), feedback_conflict (3 short), version_disagreement (4 short), format_violation (3 short), latency_outlier (2 short), length_outlier (2 short), non_ascii_ratio (2 short), tiny_input (1 short), ordinary (6 short)
  the full summary is in selection.md
[exit 0]

$ loghog label --window 2026-08-24 --dry-run
SYNTHETIC — every criterion in this run is a fixed placeholder. No model was called, nothing read these records, and none of it may be promoted.
Window '2026-08-24': 18 call(s) to nothing (dry run), one per candidate — 18 drafted, 0 failed.
  criteria in labels.jsonl, the accounting in label.md
  nothing has been adopted. Run `loghog emit --window 2026-08-24` next.
[exit 0]

$ loghog emit --window 2026-08-24
Window '2026-08-24': 18 drafted case(s), 0 left out for want of criteria.
  SYNTHETIC — these criteria are placeholders. Do not promote them.
  the dataset is in candidates-2026-08-24.yaml
  the review document is in review-2026-08-24.md
  nothing is adopted until `loghog promote --ids <id> --reviewed-by <name>`.
[exit 0]

$ loghog promote --file <demo>/goldens/candidates-2026-08-24.yaml --ids loghog_2026_08_24_a_072 --into <demo>/cases.yaml --reviewed-by Bobby Meher
loghog_2026_08_24_a_072 still carries the [SYNTHETIC] marker, which means the criteria came from `loghog label --dry-run` and are a fixed placeholder list identical for every case. Nothing read the record. Re-run `loghog label` without --dry-run, or write the criteria by hand and remove the marker from the notes.
[exit 3]

$ loghog health --window 2026-08-24 --goldens docs/examples/goldens.handwritten.yaml
Dataset 'goldens.handwritten.yaml' against window '2026-08-24': 4 case(s), 84 cluster(s).
  coverage 5/84 (6%), Wilson 3%–13%
  staleness 0/4 (0%) — no traffic here looks like them
  signalled clusters covered 2/43, ordinary 3/41, Fisher p = 0.477
  79 cluster(s) have no case at all; the 10 biggest are ranked in the report
  written to 2026-08-24.md and 2026-08-24.json
[exit 0]

$ loghog ingest --input logs/demo_window_b.jsonl --format jsonl --mapping openai_chat_jsonl --window 2026-08-31 --synthetic
SYNTHETIC — built from an invented sample log, not from production traffic. No customer wrote any of the text this window holds.
Window '2026-08-31' at <demo>/records/2026-08-31
  120 line(s) read: 120 row(s), 0 blank, 0 unparsed
  120 record(s) written, 0 deduplicated, 0 invalid
  redaction: 11 replacement(s)
  ADDRESS  1
  CARD     2
  EMAIL    2
  IBAN     1
  IPV4     1
  NAME     2
  PHONE    1
  SSN      1
  the full report is in ingest.md
[exit 0]

$ loghog score --window 2026-08-31 --existing docs/examples/goldens.handwritten.yaml
SYNTHETIC — built from an invented sample log, not from production traffic. No customer wrote any of the text this window holds.
Window '2026-08-31': 120 record(s) scored, 109 of which fired at least one signal.
  error  16
  negative_feedback  36
  feedback_conflict  3
  injection_pattern  4
  refusal_pattern  3
  novelty  92
  latency_outlier  11
  length_outlier  13
  non_ascii_ratio  2
  tiny_input  2
  not evaluated: format_violation — no mapping in this window declares [expect] output_json, so nothing here claims its output should parse.
  the full report is in score.md
[exit 0]

$ loghog cluster --window 2026-08-31
Window '2026-08-31': 82 cluster(s), 56 singleton(s), largest 4.
  133 pair(s) compared exactly, 49 merged at a Jaccard of 0.6 or more
  the full report is in cluster.md
[exit 0]

$ loghog health --window 2026-08-31 --goldens docs/examples/goldens.handwritten.yaml
Dataset 'goldens.handwritten.yaml' against window '2026-08-31': 4 case(s), 82 cluster(s).
  coverage 6/82 (7%), Wilson 3%–15%
  staleness 0/4 (0%) — no traffic here looks like them
  signalled clusters covered 5/50, ordinary 1/32, Fisher p = 0.955
  76 cluster(s) have no case at all; the 10 biggest are ranked in the report
  written to 2026-08-31.md and 2026-08-31.json
[exit 0]

$ loghog drift --from 2026-08-24 --to 2026-08-31
Drift '2026-08-24' -> '2026-08-31': 120 record(s) then, 120 now.
  25 new cluster(s) of 82 (30%) — nothing in '2026-08-24' looks like them
  error rate 3.3% -> 13.3% (intervals separated)
  input length KS statistic 0.083, median 109 -> 108 chars
  written to 2026-08-24-vs-2026-08-31.md and 2026-08-24-vs-2026-08-31.json
[exit 0]
```

## What the run left behind

Six of these files are committed beside this one, exactly as the run wrote them.

| File | What it is |
|---|---|
| [`selection.synthetic.md`](selection.synthetic.md) | Every cap and the count it refused. Carries no case text at all |
| [`label.synthetic.md`](label.synthetic.md) | The labelling run's accounting: calls, model, prompt hash, failures |
| [`candidates.synthetic.yaml`](candidates.synthetic.yaml) | Eighteen drafted cases in project 1's schema. Loads with `load_goldens` as it stands |
| [`review.synthetic.md`](review.synthetic.md) | The document a person reads: each case, its criteria as unticked boxes, Accept / Edit / Reject |
| [`health.synthetic.md`](health.synthetic.md) | Coverage, staleness, the signal table, and what to mine next |
| [`drift.synthetic.md`](drift.synthetic.md) | Two windows compared. Not one word from either |

[`goldens.handwritten.yaml`](goldens.handwritten.yaml) is the seventh, and it is
the odd one out: four cases written by a person about the demo traffic, so that
`--existing` and `health` had an honest dataset to be measured against rather than
a file of placeholders measuring itself.

Of everything above, exactly two files hold a customer's words — the candidates
YAML and the review document — and both of them hold the *redacted* words. That
is the whole reason they are the two files allowed to leave the machine.

## What is missing from this file

**A live run.** There is none, and the reason is on the record rather than
implied: `loghog label` without `--dry-run` was run once, on 2026-09-05, and
refused for want of a credential:

```console
$ loghog label --window 2026-08-24 --min-interval-ms 6500
GEMINI_API_KEY is not set. Create a .env file in the repository root containing a line 'GEMINI_API_KEY=<your key>', or export the variable in your shell. Keys are never committed.
[exit 3]
```

That message is project 1's own, from `providers.gemini`, and it does not contain
a key because it has never had one to contain. When a live run happens it will be
committed as `*.live.*` with a LIVE banner, and until then there is no number in
this repository that came from a model.
