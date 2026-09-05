<div align="center">

# 🐗 loghog

### Your production logs are already an eval set. They are also a database of your customers.

**This is the part in between: read the log, take the people out of it before anything is written, find the handful of records that would teach you something, and hand a person the one command that adopts one.**

[![ci](https://github.com/DreadpiratePickles/loghog/actions/workflows/ci.yml/badge.svg)](https://github.com/DreadpiratePickles/loghog/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-3776ab)](.python-version)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![tests: 1168](https://img.shields.io/badge/tests-1168-brightgreen)](tests/)
[![coverage: 99%](https://img.shields.io/badge/coverage-99%25-brightgreen)](#status)
[![redaction: before the first write](https://img.shields.io/badge/redaction-before%20the%20first%20write-8a2be2)](#the-principle-nothing-unredacted-is-ever-written)
[![model calls: 1 per case](https://img.shields.io/badge/model%20calls-1%20per%20case-8a2be2)](#the-one-model-call)
[![promotion: needs a name](https://img.shields.io/badge/promotion-needs%20a%20name-e8590c)](#the-gate)
[![near-dup precision: 1.00](https://img.shields.io/badge/near--dup%20precision-1.00-0b7285)](#near-duplicates-without-embeddings)

</div>

---

Somebody on the team says the sentence. *We should be evaluating this against real traffic.* Everybody
agrees, because it is obviously right, and then nothing happens for eight months. Not because anybody is
lazy — because the distance between "we have logs" and "we have an eval set" is five separate jobs, four
of which are boring in the specific way where a mistake is invisible until it is expensive.

The logs are not one shape: the gateway writes chat completions, the rollout tool writes events with the
input hashed out, somebody exported a CSV from Zendesk, and each of them has a different name for *the
answer*. Most of the logs are the same thing said twenty-five times, because there was an outage on
Tuesday. Nobody knows which lines matter, and recency is not a signal. Then, if you get that far, every
selected case needs criteria written for it, one at a time, by somebody who would rather be doing
anything else. And — the one that actually stops people — **the interesting lines are the ones with a
person in them.** The good cases are where somebody typed their order number, their address, the card
that got charged twice. An eval set built out of those is a database of personal data with a friendly
filename, sitting in a repository, being copied onto laptops.

So this tool does the four jobs where a mistake is permanent deterministically, before anything else
happens, and the fifth one exactly once per case. It reads a log under a field mapping you can review and
hash. It takes the people out **before the first byte is written**. It scores every record against
thirteen signals you can read and reweight, folds Tuesday's twenty-five tickets into one case, and hands
you a shortlist in which **every record left out was refused by exactly one named cap**. Then it makes one
bounded model call per shortlisted case to draft criteria, writes them as *drafts* in
[`regress`](https://github.com/DreadpiratePickles/regress)'s golden-case schema, and stops. A person
promotes them, one id at a time, with their name on it.

I wrote the last part twice before I got it right. The first version would happily promote a dry run's
placeholder criteria into a real goldens file, while printing "do not promote them" three lines above.

## What it is, and what it is not

This is the standalone big sibling of the miner inside
[`regress-rollout`](https://github.com/DreadpiratePickles/regress-rollout). That one mines candidates out
of a rollout it is already running, from traffic it already has in its own event log, for the feature it
is already watching. This one starts from a log file you point it at, in a format it has never seen, from
a system it knows nothing about — and does the privacy work that a tool with its own event log never had
to do, because it wrote that log itself.

It eats [`prompton`](https://github.com/DreadpiratePickles/prompton) and `regress-rollout` events
natively — there is a committed mapping for each — and it writes `regress` golden cases, so the three of
them compose into a loop: serve, log, mine, promote, regress-test, serve. But nothing here depends on you
running any of them. A mapping is a TOML file, and yours is as good as mine.

**It redacts before it remembers.** That is the sentence to keep if you keep one.

## What it does

Nine stages, one job each, and all nine are built. Eight are deterministic; the ninth makes exactly one
model call per case.

| Stage | What it does | |
|---|---|:--:|
| [`01_ingest`](stages/01_ingest/CONTEXT.md) | One log file, one field mapping, into canonical records — accounting for every line that does not make it | ✅ |
| [`02_redact`](stages/02_redact/CONTEXT.md) | Eight classes of personal data replaced by stable tokens, **inside the write path**, with the writer re-checking its work and refusing the batch if anything survived | ✅ |
| [`03_score`](stages/03_score/CONTEXT.md) | Thirteen signals, each explainable, each with an integer weight in a file you review. The score is their sum and nothing else | ✅ |
| [`04_cluster`](stages/04_cluster/CONTEXT.md) | Near-duplicates grouped, so twenty-five tickets about one outage become one case. Shingles and MinHash, **no embeddings** | ✅ |
| [`05_select`](stages/05_select/CONTEXT.md) | The set, stratified — because a top-N by score is a dataset made entirely of the loudest failure. No cap is silent | ✅ |
| [`06_label`](stages/06_label/CONTEXT.md) | The only stage that calls a model. **One bounded call per case**, drafting three to five checkable criteria with at least one negative | ✅ |
| [`07_emit`](stages/07_emit/CONTEXT.md) | `regress`'s golden-case schema, as **drafts**, plus a review document — and one command that adopts one, for a named human | ✅ |
| [`08_health`](stages/08_health/CONTEXT.md) | Is this eval **set** still about the system you are running? Coverage, staleness, gaps and redundancy | ✅ |
| [`09_drift`](stages/09_drift/CONTEXT.md) | Has the **traffic** moved? Signal rates, subjects you had never seen, input length, error rates with intervals | ✅ |

Read [`CONTEXT.md`](CONTEXT.md) to navigate and [`docs/design.md`](docs/design.md) for why each decision
went the way it did — sixty-nine of them. §27, §49 and §68 are the ones worth reading first: they are the
bugs that running it found and reasoning about it did not. §68 is the best of them, because one of the
four is a CI check that could only ever pass.

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

Of everything this tool writes, exactly **four** files hold a customer's words: the records, the
shortlist, the emitted dataset and the review document. The first two are gitignored working state. The
last two are the ones that leave the machine — a golden case *is* the ticket, and a review of criteria
without the case they came from is a spelling check. They hold the **redacted** words, and that is the
only reason they are allowed to exist.

## Why it exists

| | |
|---|---|
| 🩹 **Redaction is in the write path, not after it** | There is no file, at any point, holding unredacted production text — all five text fields, named in `REDACTED_TEXT_FIELDS` and re-checked at the door by the writer itself. "We delete it afterwards" is a hope about a code path, not a privacy property |
| 💳 **A card is not sixteen digits** | Luhn separates `4242 4242 4242 4242` from `1234567812345678`. A redactor that blanks both has destroyed *"why was order 1234567812345678 charged twice"*, which was the case |
| 🔗 **The email inside the URL** | `https://app.example.com/users/sam@example.com?ref=1`. The most common way an address survives a redactor is by not having spaces around it. It is in the samples so the suite fails if that regresses |
| 🏷️ **`[EMAIL_1]` means the same person everywhere** | Tokens are stable across a whole window, so a later stage can still tell *one customer wrote in three times* from *three customers wrote in once*. The map from token to value is never written down |
| 🧾 **Every line has exactly one home** | `lines_read == rows + blank + unparsed`, and `rows == written + deduplicated + invalid`. Both checked before the manifest exists. A window whose arithmetic does not close is refused, not reported |
| 🚦 **A partial success exits 1** | Nobody reads the report of a command that succeeded |
| 🧮 **A score you can recompute with a pencil** | The sum of the weights of the signals listed beside it. No normalisation, no decay. A ranking nobody can recompute is a ranking nobody can argue with |
| 🫥 **"Not evaluated" is not zero** | A deduplicated window physically cannot show a version disagreement. It says so, in capitals, and exits 1 — rather than printing a tidy `0` that reads as "we looked and found none" |
| 🧷 **No cap is silent** | Every record left off the shortlist was refused by exactly one named cap, and `selection.md` counts each. A shortlist whose omissions are unexplained is not a representative sample |
| 💸 **One call per case, and the budget refuses** | A shortlist longer than `[label] max_calls` stops the run. Labelling a prefix produces a dataset whose contents depend on where a budget ran out, and spends real money doing it |
| ✍️ **Nothing is adopted without a name** | `promote` takes ids one at a time and `--reviewed-by`. There is no `--all`, and there is no `--force` for the placeholders it refuses |

## Install

```bash
git clone https://github.com/DreadpiratePickles/loghog
cd loghog
uv sync
```

Python 3.12 and [uv](https://docs.astral.sh/uv/). Eight of the nine stages need no key of any kind.

For a live `loghog label`, put a Gemini key in a `.env` file at the repository root:

```
GEMINI_API_KEY=your-key-here
```

It is gitignored, it is read by `regress`'s provider seam and by nothing here, and it never appears in a
log, an error message or a record. Without it, `loghog label --dry-run` runs the whole stage offline.

## Use it

Twelve commands. Six of them are the pipeline, in order: `ingest`, `score`, `cluster`, `select`, `label`,
`emit`. Each refuses to run before its predecessor and names the command that fixes it. `promote` is the
seventh and is not part of the pipeline — it is the gate at the end of it.

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

### The whole pipeline, on the committed demo data

`logs/` holds two invented weeks of 120 records each, in the shape almost every gateway logs by default.
Window B is a week in which something broke.

```bash
uv run loghog ingest  --input logs/demo_window_a.jsonl --format jsonl \
    --mapping openai_chat_jsonl --window 2026-08-24 --synthetic
uv run loghog score   --window 2026-08-24 --existing docs/examples/goldens.handwritten.yaml
uv run loghog cluster --window 2026-08-24
uv run loghog select  --window 2026-08-24 --existing docs/examples/goldens.handwritten.yaml
uv run loghog label   --window 2026-08-24 --dry-run
uv run loghog emit    --window 2026-08-24
```

The whole transcript, with every exit code, is committed at
[`docs/examples/lifecycle.synthetic.md`](docs/examples/lifecycle.synthetic.md). Here is the middle of it.

It was recorded in a throwaway copy of the repository with `[dedupe] dedupe = false` set, so that the two
windows keep their near-duplicates instead of collapsing them — which is what makes 120 records in and 120
records out. The committed `loghog.toml` ships `dedupe = true`, so the commands above as written print
`104 record(s) written, 16 deduplicated` and carry every later count down with them. Every number below is
from the deduplication-off run; `docs/examples/lifecycle.synthetic.md` says the same thing at the top.

```
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
```

```
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
```

Nine of the thirteen signals fire on that log, and the tenth needs `--existing`. The last line is the one
worth reading: `format_violation` could not be evaluated, because the generic chat mapping declares no
output contract, and the report says so rather than printing a tidy `0` that would read as "we looked".

The three that cannot fire here — `judge_failure`, `version_disagreement`, `format_violation` — need a
log carrying judge verdicts, a prompt version and a declared output contract. The committed
[`judged_summaries`](samples/judged_summaries.synthetic.jsonl) sample is thirteen lines that exercise all
thirteen, and the suite asserts the exact count for each, so a signal that quietly stopped firing fails
the build.

### The shortlist, and everything it left out

```
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
  unfilled strata, never topped up from another: error (5 short), judge_failure (8 short), ...
```

Four caps in a fixed order: a case the goldens already hold, a cluster that is full, a stratum whose quota
is met, and the global limit — last, so it is only ever blamed for records that would otherwise have been
taken. They add up: 18 taken plus 102 refused is 120. An unfilled quota is **never** topped up from
another stratum, because borrowing against it quietly restores the monoculture the quotas exist to
prevent.

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

### The one model call

```bash
uv run loghog label --window 2026-08-24 --min-interval-ms 6500
```

One call per shortlisted case. Not one per criterion, not a draft-critique-revise loop, not a retrieval
step that fetches three similar cases first. Each of those is defensible on its own and together they make
the cost of labelling a dataset a number nobody can predict.

So it is `len(candidates)` calls, and you can read that number off the `select` output before you spend
anything. A shortlist longer than `[label] max_calls` **refuses** rather than truncating: a dataset whose
contents depend on where a budget ran out is not one anybody can reason about.

The reply is parsed strictly — exactly the keys `criteria` and `notes`, three to five criteria, at least
one starting "Does not", and none of them quoting a redaction token. That last rule is peculiar to this
tool and it exists because of stage 02: the input reaching the drafter says `[EMAIL_1]` where an address
was, and a model that has not been told otherwise will cheerfully write *"Names the account holder
[EMAIL_1]"* — an acceptance test asserting that your production system emits loghog's own redaction
marker.

A failed draft is a row with `criteria: null` and its error type, never an empty list and never a
placeholder. A run that aborted on the first rate limit would throw away every draft it had already paid
for.

`--dry-run` calls nothing, writes four fixed `[SYNTHETIC]` criteria identical for every case, paces at
zero because there is no quota to respect, and says `SYNTHETIC` on the first line of everything it
touches.

### The gate

```bash
uv run loghog emit --window 2026-08-24
```

Writes `goldens/candidates-<window>.yaml` in `regress`'s golden-case schema — it loads with
`regression_detect.goldens.load_goldens` exactly as it stands, and both the test suite and CI check that
by *calling that function* rather than by restating a schema that would drift. And
`goldens/review-<window>.md`, which is the document a person actually reads:

```markdown
## 3. `loghog_2026_08_24_a_044`

Record `a-044` · stratum **negative_feedback** · score **9** · signals: `negative_feedback`, `novelty`, `latency_outlier`

**The input, as redacted:**

> The printer driver you linked will not install on the current release at all. Nobody has replied to my earlier message.

**What the system answered:**

> Customer cannot install the linked printer driver.

**Drafted criteria** — tick the ones you accept:

- [ ] [SYNTHETIC] States the problem the request describes, in the requester's terms.
- [ ] [SYNTHETIC] Is at most 3 sentences.
- [ ] [SYNTHETIC] Does not add an order number, date, amount or name the request does not contain.
- [ ] [SYNTHETIC] Is written for a colleague to act on, not addressed to the requester.

**Accept / Edit / Reject:**
```

Copied verbatim from [`docs/examples/review.synthetic.md`](docs/examples/review.synthetic.md), including
the `[SYNTHETIC]` tags — that run was a dry run, so those four criteria are the same four criteria on
every case in the file, and `promote` will not touch them.

Then, and only then:

```bash
uv run loghog promote --file goldens/candidates-2026-08-24.yaml \
    --ids loghog_2026_08_24_a_044 \
    --into path/to/goldens.yaml --reviewed-by 'Your Name'
```

Ids one at a time, in the order you typed them. `--reviewed-by` is required. There is no `--all`, because
a switch that promoted everything would make `--reviewed-by` a lie in the same commit that introduced it —
and the name in the notes is the only thing that answers *"who decided this was correct?"* the first time
the case fails somebody's build at four in the afternoon.

The append is **textual**, so the comments in your goldens file — the category checklist, the worked
examples, the note explaining why a case exists — survive. A PyYAML round trip deletes every one of them.
The result is re-loaded with `load_goldens` before it replaces anything, so a promotion that would break
your dataset writes nothing at all.

And it refuses a dry run's placeholders:

```
$ loghog promote --file goldens/candidates-2026-08-24.yaml --ids loghog_2026_08_24_a_072 \
      --into cases.yaml --reviewed-by "Bobby Meher"
loghog_2026_08_24_a_072 still carries the [SYNTHETIC] marker, which means the criteria came from
`loghog label --dry-run` and are a fixed placeholder list identical for every case. Nothing read the
record. Re-run `loghog label` without --dry-run, or write the criteria by hand and remove the marker
from the notes.
[exit 3]
```

The candidates file says "do not promote them" in its first three lines. A tool that prints that and then
does it anyway has taught its operator that its warnings are decorative, and the next warning it prints —
about something that matters — gets skimmed.

### Ask whether the dataset is still about the system

```bash
uv run loghog health --window 2026-08-31 --goldens docs/examples/goldens.handwritten.yaml
```

```
Dataset 'goldens.handwritten.yaml' against window '2026-08-31': 4 case(s), 82 cluster(s).
  coverage 6/82 (7%), Wilson 3%–15%
  staleness 0/4 (0%) — no traffic here looks like them
  signalled clusters covered 5/50, ordinary 1/32, Fisher p = 0.955
  76 cluster(s) have no case at all; the 10 biggest are ranked in the report
```

Coverage with a Wilson interval, because a figure computed from eighty clusters is not a point. Staleness
read off the *same* threshold, so the report cannot say a cluster is covered by a case that is itself
stale against that cluster. A signal-by-signal coverage table with a row for every signal including the
ones that never fired. And the uncovered clusters ranked by size — the list of what to mine next.

The Fisher line is the one worth having. It compares coverage of clusters where something fired against
clusters where nothing did, because **a dataset that covers the dull traffic and misses the interesting
traffic passes every release and catches nothing**, and no single coverage figure shows that.

`novelty` deliberately does not count as a signal in that split, and finding out why cost me a lifecycle
run: novelty is a property of the *dataset*, not the traffic, so counting it makes the comparison read
"clusters the dataset does not cover are covered less often than the ones it does". Which is true of every
dataset ever assembled. The first recorded run came out 82 signalled clusters against 0 ordinary ones,
which is a comparison with one group in it.

`health` has **no unhealthy exit code**. The threshold at which a dataset becomes unhealthy is a decision
this stage does not make, and putting one in an exit code would make it — quietly, in a constant, for
everybody.

### Ask whether the traffic has moved

```bash
uv run loghog drift --from 2026-08-24 --to 2026-08-31
```

```
Drift '2026-08-24' -> '2026-08-31': 120 record(s) then, 120 now.
  25 new cluster(s) of 82 (30%) — nothing in '2026-08-24' looks like them
  error rate 3.3% -> 13.3% (intervals separated)
  input length KS statistic 0.083, median 109 -> 108 chars
```

That is window B doing what it was built to do. Signal rates, the share of today's subjects last week had
never seen, a two-sample Kolmogorov-Smirnov statistic over input lengths, and error and negative-feedback
rates with Wilson intervals — taken from `regress`'s `compare`, not reimplemented here.

It says `separated`, never "significant", and reports a KS *statistic* and never a p-value. Two windows a
person picked are not a sampling design, and dressing a judgement call up as a test would be a claim this
tool has not earned.

Both reports hold no text from either window at all.

### Look at what you have

```bash
uv run loghog window show --window 2026-08-24
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

## The floor plan

```
src/loghog/
├── record.py        the canonical record and its invariants. Every stage after 01 reads this
├── errors.py        seven categories, because there are seven things a caller does about a failure
├── config.py        model identifiers, and nothing else. The only module that names a model
├── config_file.py   loghog.toml, refused strictly: an unknown key is a typo, not a preference
├── ingest/          one log line, one mapping, one canonical record — and a count for every line
├── privacy/         eight detectors, Luhn, and the token map that is never written down
├── score/           thirteen signals, each a function from a record to a sentence of evidence
├── cluster/         shingles → MinHash → banding → exact Jaccard → union-find
├── select/          four caps in a fixed order, and an accounting for every record refused
├── label/           the one model call: the prompt, the strict parse, the pacing, the budget
├── emit/            the golden-case renderer, the review document, and the promotion gate
├── health/          coverage, staleness, gaps, redundancy — and one Fisher comparison
├── drift/           two windows, four questions, no text from either
└── window/          how a window is written, and the refusal that makes redaction a guarantee

logs/                two invented 120-record demo windows. Committed. README says SYNTHETIC first
samples/             the thirteen-line judged sample that makes all thirteen signals fire
mappings/            how one producer's log line becomes a record. Committed, hashed into manifests
docs/examples/       one recorded end-to-end run, banner-first, plus everything it produced
stages/*/CONTEXT.md  seven sections each: objective, inputs, process, outputs, verify, approval, failure
```

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
├── selection.md     every cap and the count it refused. Carries no case text at all
├── labels.jsonl     the drafted criteria, the model that drafted them, the prompt's hash
└── label.md         the run's accounting: calls, failures by type. No case text

goldens/
├── candidates-<window>.yaml  the drafted dataset, in regress's schema. Loads with its loader
└── review-<window>.md        what a person reads, with a box per criterion

health/<window>.{md,json}     coverage, staleness, gaps, redundancy. Quotes nothing
drift/<a>-vs-<b>.{md,json}    two windows compared. No text from either
```

`records/`, `selected/`, `goldens/` and `health/` are all gitignored, mode 0600 under 0700 directories.
They hold production text, which is what they are *for* — you cannot mine an eval set out of text nobody
kept. The goldens file you eventually promote **into** is wherever you point `--into`, which is your
repository's business rather than this one's.

The manifest is what makes a window evidence rather than a pile of JSON somebody has to take on trust:

```json
"sources": [
  {
    "bytes": 4697,
    "ingested_utc": "2026-09-05T08:11:20Z",
    "mapping": "openai_chat_jsonl",
    "mapping_sha256": "5d89ecf60523835b…",
    "path": "logs/demo_window_a.jsonl",
    "redactions": 11,
    "sha256": "5aba437e8ee5d01f…",
    "source_format": "jsonl"
  }
]
```

## Prior art, and what it is not trying to be

The idea that production traffic makes better eval data than anything you invent is not mine, and it is
not new. [LangSmith](https://docs.smith.langchain.com/) has had "add to dataset" since 2023 and it is the
right button in the right place; if you already run your traffic through it, adding a case is one click
and this tool is four commands.
[Braintrust](https://www.braintrust.dev/) and [Phoenix](https://phoenix.arize.com/) both do log-to-dataset
well and both do the observability half properly, which this does not do at all.
[Argilla](https://argilla.io/) is a better annotation surface than a markdown file with checkboxes will
ever be, and if a human is going to review a hundred cases a week they should be using it.

The difference is where the trust boundary sits. All four are services: your production text goes to
them, and then you decide what to keep. This is a command line that reads a file on your disk and takes
the people out before it writes anything, which matters exactly when you cannot send the interesting
records anywhere — and the interesting records are the ones with a person in them.

It is also deliberately small in a place they are not. There is no UI, no server, no queue, no database.
`records/` is a directory of JSONL. If you want the annotation surface, promote into Argilla instead of a
YAML file; nothing here would notice.

## It is pinned to `regress`, and calls six seams of it

`regression-detect` is a dependency, pinned to commit
[`e41aa1b`](https://github.com/DreadpiratePickles/regress) — a **commit**, not a branch, because a
window's manifest names the code that produced it and a branch that moves underneath makes that name a
guess.

Every seam it uses is used because the alternative was a second implementation of something project 1
already owns.

- **`goldens.load_goldens`**, three times over. Behind `--existing` on `score` and `select`, so a goldens
  file is checked by *loading it with the code that owns the schema*. In `health`, so a dataset that will
  not load is refused with project 1's own error. And — the one that matters most — against `emit`'s
  **output**, in the tests and again in CI, because the contract for that file is not "valid YAML in
  roughly the right shape", it is "a file that function accepts".
- **`compare.wilson_interval`**, for drift's rate intervals and health's coverage. A rate computed by two
  copies of one formula is a disagreement waiting to happen in the one place nobody would think to look.
  There is a test asserting the imported name *is* project 1's function object rather than a lookalike.
- **`compare.fisher_exact_one_sided`**, for the one comparison in the health report.
- **`providers.base`** and **`providers.gemini.gemini_provider_from_env`**, for stage 06. Nothing outside
  `cli_label.py` learns that a vendor exists.
- **`pacing.pace`** and **`pacing.validate_interval`**, for spreading stage 06's calls under a per-minute
  quota.

Two seams are deliberately still unused, and both for the same reason.
**`judge.criterion.judge_criterion`** is not called anywhere: all thirteen scoring signals are
deterministic, and a window whose records arrived without verdicts is reported as such rather than judged
into having some. Drafting criteria and grading against them are different questions and only the first
belongs here. **`target.adapters`** is what a tenth stage would use to replay a mined dataset against the
system it came from. There is no tenth stage, and a dependency imported to look busy is worse than one
that is not imported yet.

## Honest caveats

Read these before pointing it at anything real.

- **There is no live model call in this repository.** `loghog label` without `--dry-run` was run once, on
  2026-09-05, and refused for want of a credential — `GEMINI_API_KEY is not set`, exit 3, which is
  `regress`'s own message from its provider seam. Every criterion in `docs/examples/` is therefore a
  `[SYNTHETIC]` placeholder, every one of those files says so on its own first line, and `promote` refuses
  all of them. When a live run happens it will be committed as `*.live.*` **beside** the dry run, not
  instead of it.
- **The drafting prompt has never been read by a model.** Its bytes are hashed into every label row so a
  reviewer can tell which wording produced a file, and that hash has exactly one value so far. Whether
  these instructions produce *good* criteria is a claim I cannot make. What is tested is that a reply
  which is not the agreed shape is refused.
- **CI is configured and has run green on GitHub.** The workflow is committed, and I extracted its whole
  lifecycle job with PyYAML and ran it locally against the committed tree, including the clean-checkout
  assertion. GitHub now runs both workflows — `ci` and `dataset` — on every push to `main`, and
  [every run so far has succeeded](https://github.com/DreadpiratePickles/loghog/actions). What it has
  still never done is make a live model call; the caveat above stands.
- **The numbers in `docs/examples/` are about invented traffic.** Seven per cent coverage and a 3.3% → 13.3%
  error rate are arithmetic over two files I wrote for the purpose. They demonstrate that the stages
  compose and that the numbers move in the direction the data was built to move them. They are not
  measurements of anything.
- **Nothing here has been used to catch a real regression.** The tool produces a dataset in `regress`'s
  schema and a test proves `regress`'s loader accepts it. Whether a dataset mined this way finds
  regressions a hand-written one misses is the question the whole series is pointed at, and it needs a
  system, a quarter and somebody's real traffic.
- **The heuristic detectors miss things.** A name with no honorific survives — "Susan Calvin says the lamp
  flickers" keeps the name — because without the honorific, "Lumen Desk" and "Susan Calvin" are the same
  string to a regex, and blanking every Title Case pair would remove every product name in your dataset.
  An address in a language whose street words are not in the list survives. A seven-digit local phone
  number with no country code and only two groups survives.
- **"No file holds unredacted production text" is a claim about the text fields.** Five of them —
  `input_text`, `output_text`, `feedback`, `error` and each `judge_verdicts[].criterion` — go through the
  redactor and are re-checked by the write guard, and `REDACTED_TEXT_FIELDS` is one list both of them
  import so they cannot drift apart again. `record_id`, `prompt_version` and `arm` are deliberately
  **not** redacted: they are identifiers and labels, and redacting an id would break dedupe, the manifest
  and every cross-reference a later stage makes. If your logs key records by the customer's address, that
  address reaches `records.jsonl` in the `record_id` field. Map something else to `record_id`.
- **The structural detectors miss three things, and they are named.** A bare nine-digit SSN —
  `123456789`, no separators — is not detected: the pattern requires the hyphens or spaces, because
  without them it is indistinguishable from an order reference and matching it would blank one on every
  line. **IPv6 is not detected at all**; the address pattern is a dotted quad and nothing else. A card
  separated by anything outside `CARD_SEPARATORS` — a slash, say — is likewise missed. The first two are
  forced trade-offs, the third is a gap; all three mean `contains_hard_pii` returns `False` for text a
  human would call personal, and so does the write guard built on it.
- **And it over-redacts in the other direction.** "Dr Calvin Called back" becomes "[NAME_1] back". That is
  the direction to be wrong in, and there is a test named after the trade-off.
- **`records/` is gitignored, not encrypted.** The property this tool provides is that personal data is
  removed before it is written. It provides nothing about the disk it is written to.
- **The precision and recall figures are against a synthetic corpus.** 1.000 and 0.960 are measured,
  deterministic and reproducible, against ten families of paraphrases somebody wrote for the purpose. They
  say the blocking step loses about four per cent of the pairs an exhaustive comparison would find *on
  that corpus*. Point it at your own log before believing the second decimal.
- **Thirteen signals are not *the* thirteen signals.** They are the ones that were cheap, deterministic
  and defensible. A real deployment will want one about its own domain, and adding one is a function, a
  name in `SIGNAL_NAMES`, a weight and a quota.
- **The thresholds are the ones the samples needed.** `jaccard_threshold = 0.6` is where support traffic
  sat in an invented corpus. It is the first number to change against your own log, and every report
  prints it so that changing it is an argument somebody can have.
- **Clustering is single-linkage, so it is transitive.** A merges with B and B with C, and A and C end up
  together even if their own similarity is below the threshold. That is correct for a chain of paraphrases
  and wrong for a chain of loosely related complaints, which is why a cluster publishes its *weakest* link
  rather than an average — if that number looks wrong, the threshold is wrong.
- **`prompton_events.toml` is an unverified shape.** Copy it and edit the paths; nothing downstream knows
  or cares what your vendor called anything.

## Development

```bash
uv sync
uv run pytest -q                        # 1168 tests, none touching the network
uv run pytest -q --cov=src/loghog       # 99% of 3,824 statements
uv run ruff check .                      # line length 100
```

The whole test suite runs offline. `--dry-run` substitutes a fixed placeholder list for the one stage that
would otherwise make a call, and there is a test that replaces the provider constructor with one that
raises and asserts `loghog label --dry-run` still exits 0 — the seam a dry run would touch if it touched
anything.

CI runs four things in order of how fast they fail: lint, the suite, a privacy job that ingests the
committed samples through the real command line and greps the resulting window for the addresses that must
not be in it, and a lifecycle job that runs all nine stages over the two demo windows on a **copy** of the
repository — asserting the banners, asserting the emitted YAML loads with `regress`'s loader, asserting
that `promote` refuses a placeholder, and asserting at the end that the checkout was not touched.

## Status

| | |
|---|---|
| Tests | **1168**, `uv run pytest -q`, none touching the network |
| Coverage | **99%** of 3,824 statements, `uv run pytest -q --cov=src/loghog` |
| Lint | `uv run ruff check .` clean, line length 100 |
| Stages built | **9 of 9** |
| Deterministic stages | 8. The ninth makes one call per case |
| Near-duplicate detection | precision **1.000**, recall **0.960**, measured against brute force |
| Live model calls made | **0** — attempted once, refused for want of a key |
| CI | configured; `ci` and `dataset` run on every push, [**all green** on GitHub Actions](https://github.com/DreadpiratePickles/loghog/actions) |

## Licence

MIT. See [LICENSE](LICENSE).

---

<div align="center">

*It redacts before it remembers. Nothing is adopted without a name on it.*

</div>
