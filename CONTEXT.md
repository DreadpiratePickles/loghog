# Context router

Layer 1. This file answers "where do I go?" — it maps a task to the stage that
owns it. Read this, then read that stage's `CONTEXT.md`, then read only the
inputs that stage declares.

## Stages

The tool turns a production log into an evaluation dataset. Eight stages, one
job each, and the first two are built. Everything in Phase A is deterministic:
not one line of it calls a model, because turning a log line into a canonical
record and stripping the personal data out of it is mechanical work, and
mechanical work is code.

| Stage | Job | Lives in | Built? |
|---|---|---|---|
| `01_ingest` | Read one log file under one field mapping into canonical records, counting every line that does not make it | `stages/01_ingest/CONTEXT.md`, `src/loghog/ingest/` | Yes — Phase A |
| `02_redact` | Replace every piece of personal data with a stable token **before anything is written**, and refuse to write text that still carries any | `stages/02_redact/CONTEXT.md`, `src/loghog/privacy/` | Yes — Phase A |
| `03_score` | Score every record for how much it would teach: judge failures, disagreements, negative feedback, outliers, refusals | `stages/03_score/CONTEXT.md` | PLANNED |
| `04_cluster` | Group near-duplicates so that twenty-five tickets about one bug become one case rather than twenty-five | `stages/04_cluster/CONTEXT.md` | PLANNED |
| `05_select` | Choose the set: highest signal, deduplicated, and *stratified* so the dataset is not all of one failure | `stages/05_select/CONTEXT.md` | PLANNED |
| `06_label` | The one stage that calls a model: draft checkable criteria for each selected record. One bounded call per record | `stages/06_label/CONTEXT.md` | PLANNED |
| `07_emit` | Write the dataset in project 1's golden-case schema, as **drafts**, for a named human to promote | `stages/07_emit/CONTEXT.md` | PLANNED |
| `08_health` | Report on the dataset itself: coverage, staleness, drift against the traffic it came from | `stages/08_health/CONTEXT.md` | PLANNED |

Stage 02 is not a stage you can skip or run afterwards. It runs *inside* stage
01's write path, between building a record and writing it, and the writer
re-checks its output. That ordering is the whole privacy design: there is no
moment at which unredacted production text exists in a file.

Stage 06 is the only stage that will ever leave the machine, and when it exists
it will make exactly one bounded call per selected record.

## Shared resources

| Path | Layer | What it is |
|---|---:|---|
| `README.md` | 0 | Workspace identity: what the tool is for, the four commands, and what Phase A does and does not claim |
| `docs/design.md` | 3 | Every design decision and the reason for it. Read before changing behaviour |
| `loghog.toml` | 3 | The paths, the privacy switch, the name allowlist and the text limit. No model id lives here |
| `src/loghog/config.py` | 3 | Model identifiers, and nothing else. The only module that names a model |
| `src/loghog/record.py` | 3 | The canonical record and its invariants. Every stage after 01 reads this and nothing else |
| `src/loghog/errors.py` | 3 | The typed error hierarchy: five categories, because there are five things a caller does about a failure |
| `mappings/*.toml` | 3 | How one producer's log line becomes a canonical record. **Committed** — a window whose mapping is not in the repository is a window nobody can reproduce |
| `samples/` | 3 | Two invented log files and the mapping for the CSV one. Every file says SYNTHETIC on its own first line or in its own name |
| `records/<window>/records.jsonl` | 4 | The canonical records, redacted. Gitignored, mode 0600 under a 0700 directory |
| `records/<window>/manifest.json` | 4 | Where the window came from: source hashes, mapping hashes, counts, redaction statistics |
| `records/<window>/errors.jsonl` | 4 | One object per rejected line: its number, its type, and a reason. Never the line itself |
| `records/<window>/ingest.md` | 4 | The human report. Banner-first when the window is synthetic or unredacted |

## Reused from project 1

`regression-detect`, pinned to commit `e41aa1b`, is declared as a dependency and
**called by nothing in Phase A**. That is deliberate rather than an omission:
ingestion and redaction are mechanical, so they are code, and a dependency
imported to look busy is worse than one that is not imported yet.

The pin is declared now so that the dependency set a Phase A reader installs is
the one Phase B runs against, and so that stage 07's schema can be checked
against project 1's own loader rather than against a restatement of it. What the
later stages will take:

- **the provider seam** — `providers.base` (the `Provider` protocol and the typed
  error hierarchy), `providers.gemini.gemini_provider_from_env`, and
  `providers.fake.FakeProvider`, for stage 06;
- **pacing** — `pacing.pace`, for spreading stage 06's calls under a per-minute
  quota;
- **the criterion judge** — `judge.criterion.judge_criterion` and
  `parse_verdict`, for stage 03's scoring of records that arrived without
  verdicts;
- **the statistics** — `compare.fisher_exact_one_sided` and
  `compare.wilson_interval`, for stage 08's coverage intervals;
- **the golden-case schema** — `goldens.load_goldens`, which stage 07's output
  must load with, checked by calling it rather than by restating the schema;
- **the target adapters** — `target.adapters` (`Target`, `CommandTarget`,
  `HttpTarget`, `BuiltinSummarizerTarget`), so that a dataset mined here can be
  replayed against the system it came from.

Pinned to a **commit**, not a branch. A window's manifest names the code that
produced it, and a branch that moves underneath makes that name a guess.

This project does not depend on projects 2, 8 or 9, and copies nothing from
them. It reads project 9's event log — that is what
`mappings/regress_rollout_events.toml` is — but reading somebody's output file
is not a dependency on their code.

## Rules that hold across every stage

- **Redaction happens before the first write, not after the last one.** There is
  no moment at which unredacted production text exists in a file. The writer
  re-checks every record against the five structural PII classes and refuses the
  whole batch if one still carries any.
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
