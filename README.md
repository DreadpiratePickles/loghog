<div align="center">

# 🐗 loghog

### Your production logs are already an eval set. They are also a database of your customers.

**This is the part in between: read the log, take the people out of it, and count every line that did not make it.**

[![Python 3.12](https://img.shields.io/badge/python-3.12-3776ab)](.python-version)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![tests: 566](https://img.shields.io/badge/tests-566-brightgreen)](tests/)
[![coverage: 98%](https://img.shields.io/badge/coverage-98%25-brightgreen)](#status)
[![redaction: before the first write](https://img.shields.io/badge/redaction-before%20the%20first%20write-8a2be2)](#the-principle-nothing-unredacted-is-ever-written)
[![cards: checked with Luhn](https://img.shields.io/badge/cards-checked%20with%20Luhn-8a2be2)](#2-a-card-is-not-sixteen-digits)
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

So this tool does the two jobs where a mistake is permanent, deterministically, before anything else
happens. It reads a log under a field mapping you can review and hash, it takes the people out **before
the first byte is written**, and it counts every single line that did not make it, in two buckets,
because "your export is damaged" and "your mapping points at the wrong field" are different mornings.

Nothing in it calls a model. Turning a log line into a record and stripping the personal data out of it is
mechanical work, and mechanical work is code.

## What it does

Eight stages, one job each. **The first two are built.** The other six have written contracts and no
implementation, which is what PLANNED means here.

| Stage | What it does | Built? |
|---|---|:--:|
| [`01_ingest`](stages/01_ingest/CONTEXT.md) | One log file, one field mapping, into canonical records — accounting for every line that does not make it | ✅ |
| [`02_redact`](stages/02_redact/CONTEXT.md) | Eight classes of personal data replaced by stable tokens, **inside the write path**, with the writer re-checking its work and refusing the batch if anything survived | ✅ |
| [`03_score`](stages/03_score/CONTEXT.md) | Score each record for how much it would teach: failures, judge disagreements, negative feedback, outliers | PLANNED |
| [`04_cluster`](stages/04_cluster/CONTEXT.md) | Near-duplicates grouped, so twenty-five tickets about one outage become one case | PLANNED |
| [`05_select`](stages/05_select/CONTEXT.md) | The set, stratified — because a top-N by score is a dataset made entirely of the loudest failure | PLANNED |
| [`06_label`](stages/06_label/CONTEXT.md) | The only stage that will ever call a model. One bounded call per selected record | PLANNED |
| [`07_emit`](stages/07_emit/CONTEXT.md) | Project 1's golden-case schema, as **drafts**, promoted one id at a time by a named human | PLANNED |
| [`08_health`](stages/08_health/CONTEXT.md) | Is this eval set still about the system you are running? Coverage, staleness, drift | PLANNED |

Read [`CONTEXT.md`](CONTEXT.md) to navigate and [`docs/design.md`](docs/design.md) for why each decision
went the way it did — twenty-nine of them. §27 is the one worth reading first: the four bugs that running
it found and reasoning about it did not.

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

## Install

```bash
git clone https://github.com/DreadpiratePickles/loghog
cd loghog
uv sync
```

Python 3.12, [uv](https://docs.astral.sh/uv/), and no key of any kind — nothing here talks to a network.

## Use it

Four commands. Only one of them writes anything.

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
└── ingest.md        the human report, banner-first when synthetic or unredacted
```

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

## It is pinned to `regress`, and calls none of it

`regression-detect` is a dependency, pinned to commit
[`e41aa1b`](https://github.com/DreadpiratePickles/regress), and Phase A does not import one line of it.

That is deliberate rather than an oversight. Ingestion and redaction are mechanical, so they are code, and
a dependency imported to look busy is worse than one that is not imported yet. The pin is declared now so
the dependency set a reader installs today is the one Phase B runs against — and so that stage 07's output
can eventually be checked against project 1's *own* `load_goldens` rather than against a schema restated
here, because a restated schema is a schema that drifts.

[`CONTEXT.md`](CONTEXT.md) lists exactly which seams the later stages will take: the `Provider` protocol
and `gemini_provider_from_env` for stage 06, `pacing` for its quota, `judge_criterion` for stage 03,
`wilson_interval` for stage 08's coverage intervals, and the target adapters so a dataset mined here can
be replayed against the system it came from.

Pinned to a **commit**, not a branch: a window's manifest names the code that produced it, and a branch
that moves underneath makes that name a guess.

## Honest caveats

Read these before pointing it at anything real.

- **There is no live evidence in this repository, because there is nothing to be live about.** Phase A has
  made zero model calls, by design. The first stage that will make one is `06_label`, and it is PLANNED.
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

## Status

| | |
|---|---|
| Tests | **566**, `uv run pytest -q`, none touching the network |
| Coverage | **98%** statements, `uv run pytest -q --cov=src/loghog` |
| Lint | `uv run ruff check .` clean, line length 100 |
| Stages built | 2 of 8 — `01_ingest`, `02_redact` |
| Model calls made | **0** |
| CI | configured, never run |

The thirteenth project in a series, and the one whose whole job is the part everybody skips.
