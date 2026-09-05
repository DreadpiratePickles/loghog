<div align="center">

# 🐗 loghog

### Your production logs are already an eval set. They are also a database of your customers.

**This is the part in between: read the log, take the people out of it, count every line that did not make it — then find the handful of records that would actually teach you something.**

[![Python 3.12](https://img.shields.io/badge/python-3.12-3776ab)](.python-version)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![tests: 904](https://img.shields.io/badge/tests-904-brightgreen)](tests/)
[![coverage: 99%](https://img.shields.io/badge/coverage-99%25-brightgreen)](#status)
[![redaction: before the first write](https://img.shields.io/badge/redaction-before%20the%20first%20write-8a2be2)](#the-principle-nothing-unredacted-is-ever-written)
[![cards: checked with Luhn](https://img.shields.io/badge/cards-checked%20with%20Luhn-8a2be2)](#2-a-card-is-not-sixteen-digits)
[![near-dup precision: 1.00](https://img.shields.io/badge/near--dup%20precision-1.00-0b7285)](#near-duplicates-without-embeddings)
[![near-dup recall: 0.96](https://img.shields.io/badge/near--dup%20recall-0.96-0b7285)](#near-duplicates-without-embeddings)
[![model calls: zero](https://img.shields.io/badge/model%20calls-zero-critical)](#status)

</div>

---

Somebody on the team says the sentence. *We should be evaluating this against real traffic.* Everybody
agrees, because it is obviously right, and then nothing happens for eight months. Not because anybody is
lazy — because the distance between "we have logs" and "we have an eval set" is four separate jobs, three
of which are boring in the specific way where a mistake is invisible until it is expensive.

The logs are not one shape: the gateway writes chat completions, the rollout tool writes events with the
input hashed out, somebody exported a CSV from Zendesk, and each of them has a different name for *the
answer*. Most of the logs are the same thing said twenty-five times, because there was an outage on
Tuesday. Nobody knows which lines matter, and recency is not a signal. And — the one that actually stops
people — **the interesting lines are the ones with a person in them.** The good cases are where somebody
typed their order number, their address, the card that got charged twice. An eval set built out of those
is a database of personal data with a friendly filename, sitting in a repository, being copied onto
laptops.

So this tool does the jobs where a mistake is permanent, deterministically, before anything else
happens. It reads a log under a field mapping you can review and hash, it takes the people out **before
the first byte is written**, and it counts every single line that did not make it, in two buckets,
because "your export is damaged" and "your mapping points at the wrong field" are different mornings.

Then it does the part everybody guesses at. It scores every record against thirteen signals you can read
and reweight, folds the twenty-five tickets about Tuesday's outage into one case, and hands you a
shortlist in which **every record left out was refused by exactly one named cap**.

Nothing in it calls a model. Not one line. Turning a log line into a record, stripping the personal data
out of it, noticing that a customer said "up" about an answer the judge failed, and working out that two
tickets are the same complaint — all of that is mechanical work, and mechanical work is code.

## What it does

Nine stages, one job each. **Six are built.** The other three have written contracts and no
implementation, which is what PLANNED means here.

| Stage | What it does | Built? |
|---|---|:--:|
| [`01_ingest`](stages/01_ingest/CONTEXT.md) | One log file, one field mapping, into canonical records — accounting for every line that does not make it | ✅ |
| [`02_redact`](stages/02_redact/CONTEXT.md) | Eight classes of personal data replaced by stable tokens, **inside the write path**, with the writer re-checking its work and refusing the batch if anything survived | ✅ |
| [`03_score`](stages/03_score/CONTEXT.md) | Thirteen signals, each explainable, each with an integer weight in a file you review. The score is their sum and nothing else | ✅ |
| [`04_cluster`](stages/04_cluster/CONTEXT.md) | Near-duplicates grouped, so twenty-five tickets about one outage become one case. Shingles and MinHash, **no embeddings** | ✅ |
| [`05_select`](stages/05_select/CONTEXT.md) | The set, stratified — because a top-N by score is a dataset made entirely of the loudest failure. No cap is silent | ✅ |
| [`06_label`](stages/06_label/CONTEXT.md) | The only stage that will ever call a model. One bounded call per selected record | PLANNED |
| [`07_emit`](stages/07_emit/CONTEXT.md) | Project 1's golden-case schema, as **drafts**, promoted one id at a time by a named human | PLANNED |
| [`08_health`](stages/08_health/CONTEXT.md) | Is this eval **set** still about the system you are running? Coverage and staleness against the goldens | PLANNED |
| [`09_drift`](stages/09_drift/CONTEXT.md) | Has the **traffic** moved? Signal rates, subjects you had never seen, input length, error rates with intervals | ✅ |

Read [`CONTEXT.md`](CONTEXT.md) to navigate and [`docs/design.md`](docs/design.md) for why each decision
went the way it did — fifty of them. §27 and §49 are the ones worth reading first: the seven bugs that
running it found and reasoning about it did not. §34 is the best of them, because it is not a bug at all —
it is two correct decisions contradicting each other, reported rather than papered over.

## The principle: nothing unredacted is ever written

Not "we redact it and then delete the original". Not "the raw file only exists for a moment". There is no
moment. Redaction happens between building a record and writing it, and then the writer runs the
detectors again over what it is about to turn into bytes and refuses the whole batch if one of them
fires — naming the record and the class, and never the value.

That last clause matters more than it looks. An error message that says *record `r-9` still carries an
EMAIL* goes in a log, a ticket and a Slack channel. One that quotes the address puts it in all three.

Turning it off takes two switches in two places: `[privacy] redact = false` in a reviewed configuration
file **and** `--allow-unredacted` typed on the command line at the moment of the decision. The window's
manifest then says `redacted: false` for ever, and appending an unredacted run into a redacted window
makes the whole window unredacted — because a window is only as private as its least careful run.

## Why it exists

| | |
|---|---|
| 🩹 **Redaction is in the write path, not after it** | There is no file, at any point, holding unredacted production text. "We delete it afterwards" is a hope about a code path, not a privacy property |
| 💳 **A card is not sixteen digits** | Luhn separates `4242 4242 4242 4242` from `1234567812345678`. A redactor that blanks both has destroyed *"why was order 1234567812345678 charged twice"*, which was the case |
| 🔗 **The email inside the URL** | `https://app.example.com/users/sam@example.com?ref=1`. The most common way an address survives a redactor is by not having spaces around it. It is in the sample so the suite fails if that regresses |
| 🏷️ **`[EMAIL_1]` means the same person everywhere** | Tokens are stable across a whole window, so a later stage can still tell *one customer wrote in three times* from *three customers wrote in once*. The map from token to value is never written down |
| 🧾 **Every line has exactly one home** | `lines_read == rows + blank + unparsed`, and `rows == written + deduplicated + invalid`. Both checked before the manifest exists. A window whose arithmetic does not close is refused, not reported |
| 🚦 **A partial success exits 1** | Nobody reads the report of a command that succeeded |
| 🔌 **A mapping is data, not a plugin** | TOML you can diff, review and hash — and the hash goes in the manifest, so in a year you can still establish what "the answer field" meant when this window was built |
| 🧮 **A score you can recompute with a pencil** | The sum of the weights of the signals listed beside it. No normalisation, no decay. A ranking nobody can recompute is a ranking nobody can argue with |
| 🫥 **"Not evaluated" is not zero** | A deduplicated window physically cannot show a version disagreement. It says so, in bold, and exits 1 — rather than printing a tidy `0` that reads as "we looked and found none" |
| 🧷 **No cap is silent** | Every record left off the shortlist was refused by exactly one named cap, and `selection.md` counts each. A shortlist whose omissions are unexplained is not a representative sample |

## Install

```bash
git clone https://github.com/DreadpiratePickles/loghog
cd loghog
uv sync
```

Python 3.12, [uv](https://docs.astral.sh/uv/), and no key of any kind — nothing here talks to a network.

## Use it

Eight commands. Four of them write, and the four that do are the pipeline: `ingest`, `score`, `cluster`,
`select`. Each refuses to run before its predecessor and names the command that fixes it.

### See what redaction would do, before trusting it with anything

```bash
uv run loghog redact --text "Dr Susan Calvin, sam@example.com, 4242 4242 4242 4242, order 1234567812345678"
```

```
[NAME_1], [EMAIL_1], [CARD_1], order 1234567812345678

Replaced 3 value(s), 3 distinct:
  CARD   1
  EMAIL  1
  NAME   1
```

The order reference is still there. That is the whole argument of the module in one line: it fails Luhn,
so it is not a card, so it survives — and the ticket is still about something.

This command writes nothing. Point it at your own worst log line before you point the ingester at your
whole log.

### Ingest a log into a window

```bash
uv run loghog ingest --input samples/support_chat.synthetic.jsonl \
    --format jsonl --mapping openai_chat_jsonl --window demo --synthetic
```

```
SYNTHETIC — built from an invented sample log, not from production traffic. No customer wrote any of the text this window holds.
Window 'demo' at /path/to/records/demo
  13 line(s) read: 11 row(s), 1 blank, 1 unparsed
  9 record(s) written, 1 deduplicated, 1 invalid
  redaction: 9 replacement(s)
  ADDRESS  1
  CARD     1
  EMAIL    1
  IBAN     1
  IPV4     1
  NAME     1
  PHONE    2
  SSN      1
  2 rejected line(s) listed in errors.jsonl
  the full report is in ingest.md
```

**It exits 1.** Two of the sample's thirteen lines are broken on purpose — one is not JSON, one reads
perfectly and is not a record — and a run that returned 0 over them would be the exact failure this tool
exists to prevent. Both are named in `errors.jsonl`, with their line numbers and their types, and neither
entry quotes the line:

```json
{"detail": "not valid JSON (Expecting value at column 56)", "error_type": "LineParseError", "line_no": 9}
{"detail": "record 'chat-012' carries neither an output nor an error. A failed read must not become a successful no-op.", "error_type": "RecordError", "line_no": 13}
```

### Find the records that would teach you something

Three commands after `ingest`, in order. Each refuses to run before its predecessor and names the
command that fixes it.

```bash
uv run loghog score   --window demo --existing goldens.yaml
uv run loghog cluster --window demo
uv run loghog select  --window demo
```

```
Window 'judged': 13 record(s) scored, 11 of which fired at least one signal.
  error  1
  judge_failure  2
  negative_feedback  1
  feedback_conflict  1
  version_disagreement  2
  injection_pattern  1
  refusal_pattern  1
  format_violation  2
  novelty  11
  latency_outlier  1
  length_outlier  3
  non_ascii_ratio  1
  tiny_input  1
  the full report is in score.md
```

That is the committed `judged_summaries` sample: thirteen invented events written so that **twelve of the
thirteen signals fire**, because a scoring stage demonstrated against a log where nothing fires is a
scoring stage nobody has seen work. The thirteenth is `novelty`, which needs `--existing`. The suite
asserts the exact count for each, so a signal that quietly stopped firing would fail the build.

`feedback_conflict` is the one to look at first. It is the record where the judge said the output was
wrong and the customer said it was fine — one of the two is miscalibrated, and the case is the only way to
find out which. It carries the highest weight in the shipped configuration, and that weight is a line in
`loghog.toml` you can disagree with.

#### Near-duplicates without embeddings

Five-word shingles → MinHash over 64 seeded permutations → LSH banding → an **exact** Jaccard check on
every candidate pair before anything merges. Banding only proposes; the exact number disposes — because a
threshold somebody has to argue with should not be a probability from a curve.

Measured by the suite against a brute-force comparison of all 2,415 pairs in a 70-record corpus:

| | |
|---|---|
| Precision | **1.000** — by construction: every merge was verified against the true Jaccard |
| Recall | **0.960** — this is what the blocking step actually costs |
| Comparisons | **96**, not 2,415 |

That recall figure is measured and asserted rather than assumed, because a clustering tool that does not
say what its blocking step lost is a tool making a claim nobody checked.

The base hash is BLAKE2b and **not** Python's `hash()`, which is salted per process — an implementation
built on it passes every unit test and silently repartitions the same window on the next run. There is a
test that runs the module in two subprocesses under two values of `PYTHONHASHSEED`, because that is the
only kind of test that catches it.

#### The shortlist, and everything it left out

```
Window 'judged': 10 candidate(s) of 13 scored record(s), at most 40 and at most 1 per cluster.
  error  1 of 6
  judge_failure  1 of 8
  feedback_conflict  1 of 4
  ordinary  1 of 6
  dropped, by cap:
    cluster_cap  3
  unfilled strata, never topped up from another: version_disagreement (4 short), novelty (4 short), ...
```

Four caps, checked in a fixed order: a case the goldens already hold, a cluster that is full, a stratum
whose quota is met, and the global limit — last, so it is only ever blamed for records that would
otherwise have been taken. An unfilled quota is **never** topped up from another stratum, because
borrowing against it quietly restores the monoculture the quotas exist to prevent.

### Ask whether the traffic has moved

```bash
uv run loghog drift --from 2026-08-28 --to 2026-09-04
```

```
Drift 'chat' -> 'judged': 10 record(s) then, 13 now.
  10 new cluster(s) of 10 (100%) — nothing in 'chat' looks like them
  error rate 10.0% -> 7.7% (intervals overlap)
  input length KS statistic 0.500, median 80 -> 74 chars
  written to chat-vs-judged.md and chat-vs-judged.json
```

Signal rates, the share of today's subjects last week had never seen, a two-sample Kolmogorov-Smirnov
statistic over input lengths, and error and negative-feedback rates with Wilson intervals — taken from
project 1's `compare`, not reimplemented here.

It says `separated`, never "significant", and reports a KS *statistic* and never a p-value. Two windows a
person picked are not a sampling design, and dressing a judgement call up as a test would be a claim this
tool has not earned.

The report holds no text from either window at all.

### Look at what you have

```bash
uv run loghog window show --window demo
uv run loghog window list
uv run loghog mappings list
```

### The mappings

Three are built in, and writing a fourth is a TOML file rather than a pull request.

| Mapping | For | Note |
|---|---|---|
| `openai_chat_jsonl` | Anything logging chat completions | The input is not a field, it is *the last user turn*. That is a named extractor, not a path |
| `regress_rollout_events` | [`regress-rollout`](https://github.com/DreadpiratePickles/regress-rollout)'s event log | Its log stores `input_sha256` and **not** the ticket — the right call for a monitor. Pass `--sidecar <traffic file>` and the two halves are rejoined by hash |
| `prompton_events` | A nested hosted-observability export | **The shape is unverified.** Its header says so in capitals. It is committed because nested paths are the second thing a mapping must do, and no other built-in exercises them |

`[expect] output_json = true` is the one mapping flag a later stage reads: it says this producer's output
is supposed to parse, and stage 03 turns that into the `format_violation` signal. It lives in the mapping
because it is a fact about one producer, and a window can hold several — so it travels to the scorer in
the manifest, per source. If two sources in one window disagree about it, the signal is **refused rather
than guessed**, because a record does not carry which source it came from.

```bash
uv run loghog ingest --input events/summarizer-1.1/2026-09-04.jsonl \
    --format jsonl --mapping regress_rollout_events \
    --sidecar traffic/tickets_v1.jsonl --window 2026-09-04
```

Without `--sidecar`, that run is refused by name before a line is read — rather than failing every line
for a missing `input_text` and leaving you to work out why.

## What a window is

```
records/<window>/
├── records.jsonl    one canonical record per line, redacted, keys sorted
├── manifest.json    source hashes, mapping hashes, counts, redaction statistics
├── errors.jsonl     one object per rejected line: number, type, reason. Never the line
├── ingest.md        the human report, banner-first when synthetic or unredacted
├── scores.jsonl     one object per record: its score and the evidence for every signal
├── score.md         what fired, and — first among the prose — what could NOT be evaluated
├── clusters.json    members, representatives, the weakest link that built each cluster
└── cluster.md       the shape of the partition, and nothing from inside it

selected/<window>/
├── candidates.jsonl the shortlist, carrying the redacted case because stage 06 needs it
└── selection.md     every cap and the count it refused. Carries no case text at all

drift/<a>-vs-<b>.md   and .json — two windows compared. No text from either
```

Of all of those, exactly two hold a customer's words: `records.jsonl` and `candidates.jsonl`. Everything
else is counts, ids, thresholds and named patterns — because reports are what people paste into tickets.

Mode 0600 under a 0700 directory, and gitignored — it holds production text, which is what it is *for*.
You cannot mine an eval set out of text nobody kept.

The manifest is what makes a window evidence rather than a pile of JSON somebody has to take on trust:

```json
"sources": [
  {
    "bytes": 4697,
    "ingested_utc": "2026-09-05T08:11:20Z",
    "mapping": "openai_chat_jsonl",
    "mapping_sha256": "5d89ecf60523835b…",
    "path": "samples/support_chat.synthetic.jsonl",
    "redactions": 9,
    "sha256": "5aba437e8ee5d01f…",
    "source_format": "jsonl"
  }
]
```

## It is pinned to `regress`, and now calls two seams of it

`regression-detect` is a dependency, pinned to commit
[`e41aa1b`](https://github.com/DreadpiratePickles/regress). Phase A imported none of it, deliberately:
ingestion and redaction are mechanical, so they are code, and a dependency imported to look busy is worse
than one that is not imported yet.

Phase B imports two things, and both for the same reason — the alternative was a second implementation of
something project 1 already owns.

- **`goldens.load_goldens`**, behind `--existing`. A goldens file is checked by *loading it with the code
  that owns the schema*, which is the only check that cannot drift from a restatement. A file that will
  not load is a refusal, not a skip: losing the comparison quietly would propose cases you already hold
  and call them novel, which is the exact failure the flag exists to prevent.
- **`compare.wilson_interval`**, for the drift report's rate intervals. A rate computed by two copies of
  one formula is a disagreement waiting to happen in the one place nobody would think to look — a number
  here disagreeing with the same number in project 1 for six months until somebody diffed two reports.
  There is a test asserting the imported name *is* project 1's function object rather than a lookalike.

Stage 03 deliberately does **not** call `judge_criterion`, even though it could. All thirteen of its
signals are deterministic, and a window whose records arrived without verdicts is reported as such rather
than judged into having some. Judging is stage 06's business, where the call is bounded and budgeted.

[`CONTEXT.md`](CONTEXT.md) lists what is left: the `Provider` protocol and `gemini_provider_from_env` for
stage 06, `pacing` for its quota, `fisher_exact_one_sided` for stage 08, and the target adapters so a
dataset mined here can be replayed against the system it came from.

Pinned to a **commit**, not a branch: a window's manifest names the code that produced it, and a branch
that moves underneath makes that name a guess.

## Honest caveats

Read these before pointing it at anything real.

- **There is no live evidence in this repository, because there is nothing to be live about.** Six of nine
  stages are built and none has ever made a model call, by design. The first stage that will is
  `06_label`, and it is PLANNED.
- **CI is configured and has never run.** The workflow is committed; nothing has been pushed. Every number
  on the badges above came from `uv run pytest -q` and `--cov` on this machine.
- **The heuristic detectors miss things.** A name with no honorific survives — "Susan Calvin says the lamp
  flickers" keeps the name — because without the honorific, "Lumen Desk" and "Susan Calvin" are the same
  string to a regex, and blanking every Title Case pair would remove every product name in your dataset.
  An address in a language whose street words are not in the list survives. A seven-digit local phone
  number with no country code, no parentheses and only two groups survives.
- **And it over-redacts in the other direction.** "Dr Calvin Called back" becomes "[NAME_1] back". That is
  the direction to be wrong in, and there is a test named after the trade-off.
- **`records/` is gitignored, not encrypted.** The property this tool provides is that personal data is
  removed before it is written. It provides nothing about the disk it is written to.
- **`prompton_events.toml` is an unverified shape.** Copy it and edit the paths; nothing downstream knows
  or cares what your vendor called anything.
- **The precision and recall figures are against a synthetic corpus.** 1.000 and 0.960 are measured,
  deterministic and reproducible, and they are measured against ten families of paraphrases somebody wrote
  for the purpose. They say the blocking step loses about four per cent of the pairs an exhaustive
  comparison would find *on that corpus*. Point it at your own log before believing the second decimal.
- **Thirteen signals are not *the* thirteen signals.** They are the ones that were cheap, deterministic
  and defensible. A real deployment will want one about its own domain, and adding one is a function, a
  name in `SIGNAL_NAMES`, a weight and a quota.
- **The thresholds are the ones the samples needed.** `jaccard_threshold = 0.6` is where support traffic
  sat in an invented corpus. It is the first number to change against your own log, and every report
  prints it so that changing it is an argument somebody can have.
- **Clustering is single-linkage, so it is transitive.** A merges with B and B with C, and A and C end up
  together even if their own similarity is below the threshold. That is correct for a chain of
  paraphrases and wrong for a chain of loosely related complaints, which is why a cluster publishes its
  *weakest* link rather than an average — if that number looks wrong, the threshold is wrong.

## Status

| | |
|---|---|
| Tests | **904**, `uv run pytest -q`, none touching the network |
| Coverage | **99%** statements, `uv run pytest -q --cov=src/loghog` |
| Lint | `uv run ruff check .` clean, line length 100 |
| Stages built | 6 of 9 — `01_ingest`, `02_redact`, `03_score`, `04_cluster`, `05_select`, `09_drift` |
| Near-duplicate detection | precision **1.000**, recall **0.960**, measured against brute force |
| Model calls made | **0** |
| CI | configured, never run |

The thirteenth project in a series, and the one whose whole job is the part everybody skips.
