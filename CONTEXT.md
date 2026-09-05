# Context router

Layer 1. This file answers "where do I go?" — it maps a task to the stage that
owns it. Read this, then read that stage's `CONTEXT.md`, then read only the
inputs that stage declares.

## Stages

The tool turns a production log into an evaluation dataset. Nine stages, one job
each, and all nine are built.

Eight of them are deterministic, and that is the shape of the problem rather than
a preference: turning a log line into a canonical record, stripping the personal
data out of it, deciding which records are unusual and which are the same
complaint twice — all of that is mechanical work, and mechanical work is code.

The ninth is `06_label`, the one stage that calls a model, and it makes **exactly
one bounded call per selected candidate**. Nothing it produces is adopted:
`07_emit` writes drafts, and `loghog promote` is the only command in the
repository that puts a case in a goldens file, for an id a named human typed.

| Stage | Job | Lives in | Built? |
|---|---|---|---|
| `01_ingest` | Read one log file under one field mapping into canonical records, counting every line that does not make it | `stages/01_ingest/CONTEXT.md`, `src/loghog/ingest/` | Yes — Phase A |
| `02_redact` | Replace every piece of personal data with a stable token **before anything is written**, and refuse to write text that still carries any | `stages/02_redact/CONTEXT.md`, `src/loghog/privacy/` | Yes — Phase A |
| `03_score` | Score every record against thirteen signals, each explainable: judge failures, disagreements, negative feedback, outliers, refusals, injection attempts | `stages/03_score/CONTEXT.md`, `src/loghog/score/` | Yes — Phase B |
| `04_cluster` | Group near-duplicates so that twenty-five tickets about one bug become one case rather than twenty-five | `stages/04_cluster/CONTEXT.md`, `src/loghog/cluster/` | Yes — Phase B |
| `05_select` | Choose the set: highest signal, one per cluster, and *stratified* so the dataset is not all of one failure | `stages/05_select/CONTEXT.md`, `src/loghog/select/` | Yes — Phase B |
| `06_label` | The one stage that calls a model: draft checkable criteria for each selected record. One bounded call per record | `stages/06_label/CONTEXT.md`, `src/loghog/label/` | Yes — Phase C |
| `07_emit` | Write the dataset in project 1's golden-case schema, as **drafts**, for a named human to promote | `stages/07_emit/CONTEXT.md`, `src/loghog/emit/` | Yes — Phase C |
| `08_health` | Report on the dataset itself: coverage and staleness of the goldens against the traffic they came from | `stages/08_health/CONTEXT.md`, `src/loghog/health/` | Yes — Phase C |
| `09_drift` | Compare two windows: signal rates, subjects the older one never saw, input length, error rates with intervals | `stages/09_drift/CONTEXT.md`, `src/loghog/drift/` | Yes — Phase B |

Stage 02 is not a stage you can skip or run afterwards. It runs *inside* stage
01's write path, between building a record and writing it, and the writer
re-checks its output. That ordering is the whole privacy design: there is no
moment at which unredacted production text exists in a file.

Stage 06 is the only stage that leaves the machine, and it makes exactly one
bounded call per selected candidate. `--dry-run` makes none at all, writes a
fixed placeholder list, and every file it touches says `SYNTHETIC` on its own
first line — including the emitted dataset, which `promote` then refuses to
adopt. A tool that prints "do not promote these" and then promotes them has
taught its operator that its warnings are decorative.

Stage 09 is numbered last because it is out of the pipeline rather than at the
end of it. It is a question a person asks about two windows — has the traffic
moved? — and it needs no goldens file, no shortlist and no model. Stage 08 asks
the neighbouring question, is the *dataset* still about the system, and needs the
goldens that stage 09 does not.

The pipeline is six commands in order: `ingest`, `score`, `cluster`, `select`,
`label`, `emit`. Each refuses to run before its predecessor and names the command
that fixes it. `promote` is the seventh and is not part of the pipeline — it is
the gate at the end of it, and it takes a person's name.

`health` and `drift` are questions somebody asks about what the pipeline
produced, and neither is a step in it.

## Shared resources

| Path | Layer | What it is |
|---|---:|---|
| `README.md` | 0 | Workspace identity: what the tool is for, the four commands, and what Phase A does and does not claim |
| `docs/design.md` | 3 | Every design decision and the reason for it. Read before changing behaviour |
| `loghog.toml` | 3 | The paths, the privacy switch, the name allowlist, the text limit, and every weight, threshold and quota Phase B argues about. No model id lives here |
| `src/loghog/config_values.py` | 3 | The validators every configuration section shares, so eight sections cannot drift in their wording |
| `src/loghog/config.py` | 3 | Model identifiers, and nothing else. The only module that names a model |
| `src/loghog/record.py` | 3 | The canonical record and its invariants. Every stage after 01 reads this and nothing else |
| `src/loghog/errors.py` | 3 | The typed error hierarchy: five categories, because there are five things a caller does about a failure |
| `mappings/*.toml` | 3 | How one producer's log line becomes a canonical record. **Committed** — a window whose mapping is not in the repository is a window nobody can reproduce |
| `samples/` | 3 | Two invented log files and the mapping for the CSV one. Every file says SYNTHETIC on its own first line or in its own name |
| `records/<window>/records.jsonl` | 4 | The canonical records, redacted. Gitignored, mode 0600 under a 0700 directory |
| `records/<window>/manifest.json` | 4 | Where the window came from: source hashes, mapping hashes, counts, redaction statistics |
| `records/<window>/errors.jsonl` | 4 | One object per rejected line: its number, its type, and a reason. Never the line itself |
| `records/<window>/ingest.md` | 4 | The human report. Banner-first when the window is synthetic or unredacted |
| `records/<window>/scores.jsonl` | 4 | One object per record: its score and the evidence for every signal that fired |
| `records/<window>/score.md` | 4 | The human scoring report — and, first among its prose, the signals that could **not** be evaluated |
| `records/<window>/clusters.json` | 4 | The partition: members, representatives, the weakest link that built each cluster, and the parameters used |
| `records/<window>/cluster.md` | 4 | The shape of the partition, and nothing from inside it |
| `selected/<window>/candidates.jsonl` | 4 | The shortlist, carrying the redacted case because stage 06 needs it. Gitignored |
| `selected/<window>/selection.md` | 4 | Every cap and the count it refused. Carries no case text |
| `selected/<window>/labels.jsonl` | 4 | The drafted criteria, beside the candidates they were drafted from. Gitignored |
| `selected/<window>/label.md` | 4 | The labelling run's accounting: calls, model, prompt hash, failures. No case text |
| `goldens/candidates-<window>.yaml` | 4 | The drafted dataset, in project 1's schema. Carries the redacted case, because a golden case IS the case. Gitignored |
| `goldens/review-<window>.md` | 4 | What a person reads: each case, its criteria as unticked boxes, one Accept / Edit / Reject line. Gitignored |
| `health/<window>.{md,json}` | 4 | Coverage, staleness, gaps and redundancy. Carries no text from either side |
| `drift/<a>-vs-<b>.{md,json}` | 4 | Two windows compared. Carries no text from either |
| `logs/*.jsonl` | 3 | Two invented 120-record demo windows. **Committed**, and the directory's README says SYNTHETIC on its first line |
| `docs/examples/*.synthetic.*` | 3 | One recorded end-to-end run, banner-first, plus the artefacts it produced |

## Reused from project 1

`regression-detect`, pinned to commit `e41aa1b`, is declared as a dependency.
Phase A called none of it, deliberately: ingestion and redaction are mechanical,
so they are code, and a dependency imported to look busy is worse than one that
is not imported yet.

**Phases B and C call six seams of it**, and every one of them for the same
reason: the alternative was a second implementation of something project 1
already owns.

- `goldens.load_goldens` and `GoldenDatasetError`, behind `--existing` on
  `loghog score` and `loghog select`. A goldens file is checked by *loading it
  with the code that owns the schema*, which is the only check that cannot drift
  from a restatement.
- `compare.wilson_interval`, for stage 09's rate intervals. A rate computed by
  two copies of one formula is a disagreement waiting to happen in the one place
  nobody would think to look. A test asserts the imported name is project 1's
  own function object rather than a lookalike.
- **the provider seam** — `providers.base` (the `Provider` protocol and its typed
  error hierarchy) and `providers.gemini.gemini_provider_from_env`, for stage 06.
  Nothing outside `cli_label.py` learns that a vendor exists.
- **pacing** — `pacing.pace` and `pacing.validate_interval`, for spreading stage
  06's calls under a per-minute quota. A dry run paces at zero.
- **`compare.fisher_exact_one_sided`**, for stage 08's comparison of coverage on
  the interesting traffic against coverage on the ordinary traffic.
- **the golden-case schema** — `goldens.load_goldens` a third time, and this is
  the one that matters most: stage 07's *output* must load with it. Checked by
  calling it, in the tests and again in CI, rather than by restating a schema
  here that would drift.

One seam is deliberately still unused. **`judge.criterion.judge_criterion` is not
called anywhere**, and stage 03 does not call it even though it could: all
thirteen of its signals are deterministic, and a window whose records arrived
without verdicts is reported as such rather than judged into having some. Stage
06 does not call it either, because drafting criteria and grading against them
are different questions and only the first one belongs here.

**`target.adapters`** (`Target`, `CommandTarget`, `HttpTarget`,
`BuiltinSummarizerTarget`) is the other one, and it is what a tenth stage would
use to replay a mined dataset against the system it came from. There is no such
stage, and a dependency imported to look busy is worse than one that is not
imported yet.

Pinned to a **commit**, not a branch. A window's manifest names the code that
produced it, and a branch that moves underneath makes that name a guess.

This project does not depend on projects 2, 8 or 9, and copies nothing from
them. It reads project 9's event log — that is what
`mappings/regress_rollout_events.toml` is — but reading somebody's output file
is not a dependency on their code.

## Rules that hold across every stage

- **Redaction happens before the first write, not after the last one.** There is
  no moment at which unredacted production text exists in a file. The writer
  re-checks every text field of every record — the four in `REDACTED_TEXT_FIELDS`
  and each `judge_verdicts[].criterion` — against the five structural PII classes
  and refuses the whole batch if one still carries any. Identifiers and labels
  (`record_id`, `prompt_version`, `arm`) are deliberately outside that set.
- **`[privacy] redact = false` needs a second switch on the command line.** Two
  switches, in two places, one of them typed by a person at the moment of the
  decision.
- **A bad line is counted, never dropped.** Every line of every source is a row,
  a blank, or an unparsed line; every row is a record, a duplicate, or an invalid
  row. Both sums are checked before the manifest is written.
- **The two kinds of bad line are kept apart.** Unparsed means the export is
  damaged; invalid usually means the mapping is pointed at the wrong field. A
  thousand of the first is a conversation upstream, a thousand of the second is a
  one-line edit.
- **A partial success does not exit 0.** Nobody reads the report of a command
  that succeeded.
- **Nothing that is written quotes what it redacted.** Not the error report, not
  the manifest, not the terminal output. A report that quotes the data is a
  second copy of the data in the places nobody was thinking about privacy.
- **Absent and empty are different facts.** A field a log did not send is `null`;
  a field it sent empty is an error. Neither is a zero and neither is `""`.
- **Nothing is guessed.** A naive timestamp is refused unless a mapping says
  outright that its producer writes UTC. A sidecar miss is a skipped row, not a
  nearest match.
- **Money is integer micro-USD.** No amount is ever a float, and `bool` is not an
  integer.
- **A model id lives in `config.py` and nowhere else** — checked mechanically by
  a test that scans the source, the scripts, the mappings and the configuration.
- Secrets live in `.env` and never enter source, a mapping, a log line, an error
  message, or a record.
- **Anything synthetic says so on its own first line.** A window built from the
  sample log carries a `SYNTHETIC` banner in its report and a flag in its
  manifest, and the terminal says it too.

## Rules that hold across every stage after ingestion

- **A score is a sum somebody can recompute by hand.** The weights of the
  signals that fired, and nothing else. No normalisation, no decay. A ranking
  nobody can recompute is a ranking nobody can argue with.
- **Evidence never quotes the record.** A signal names a pattern, a criterion, a
  count or a threshold. `scores.jsonl`, `score.md`, `cluster.md`, `selection.md`
  and both drift reports carry no customer's words at all. The only Phase B file
  that holds text is `selected/<window>/candidates.jsonl`, because stage 06 needs
  it, and it is gitignored at mode 0600 like the records.
- **"Could not be evaluated" is not zero.** A signal the window silenced is
  named, and the run exits 1. A signal absent because somebody chose not to
  supply an input is named too, and exits 0. Printing a tidy zero for either
  would read as evidence of absence.
- **No cap is silent.** Every record left off a shortlist was refused by exactly
  one named cap, and the summary counts each. An unfilled quota is never topped
  up from another stratum.
- **Blocking proposes; the exact answer disposes.** LSH decides which pairs are
  worth comparing; the true Jaccard decides which are near-duplicates. A
  threshold somebody has to argue with must not be a probability.
- **Determinism is tested, not assumed.** Every stage writes identical bytes on a
  second run, and clustering is asserted to be independent of the order of the
  window *and* of the interpreter's hash seed.
- **A stage refuses to run before its predecessor**, by name, with the command
  that fixes it — never by quietly treating the missing input as empty.
- **Exactly one model call per judgement, and the budget refuses rather than
  truncating.** More candidates than `[label] max_calls` stops the run before the
  first call. Labelling a prefix would produce a dataset whose contents depend on
  where a budget ran out, and would spend real money doing it.
- **Model output is untrusted input.** The reply is parsed strictly; a failure is
  a recorded row with its error type, never an empty criteria list, and never a
  placeholder. The case travels in delimiters inside the user message and never
  in the system prompt.
- **Nothing is adopted without a name.** `promote` is the only command that
  writes into a goldens file. It needs `--reviewed-by`, it takes ids one at a
  time, there is no `--all`, and it refuses any case still carrying the
  `[SYNTHETIC]` marker.
- **A promotion that would break the target writes nothing.** The appended file
  is re-loaded with `load_goldens` before it replaces anything, and the append is
  textual so a goldens file's comments — half its content — survive.
- **Two files carry the case on purpose**, and it is always the redacted case:
  the emitted dataset, because a golden case *is* the case, and the review
  document, because a review of criteria without the case they came from is a
  spelling check. Every other file this tool writes carries counts, ids,
  thresholds and named patterns.
