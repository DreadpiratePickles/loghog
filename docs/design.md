# Design decisions

Layer 3. Every decision in this repository that could reasonably have gone the
other way, with the reason it went this way. Read this before changing
behaviour: a rule with a reason written down is cheap to revisit, and a rule
without one gets re-litigated every six months.

Phase A is stages 01 and 02 — ingestion, normalisation and redaction. §1-§7 are
the problem and the shape of the answer, §8-§14 are the canonical record and the
mapping layer, §15-§21 are privacy, §22-§26 are the window, and §27-§29 are what
was found by running it rather than by reasoning about it.

Phase B is stages 03, 04, 05 and 09 — scoring, clustering, selection and drift.
§30-§34 are scoring, §35-§40 are near-duplicate detection, §41-§44 are selection,
§45-§47 are drift, and §48-§49 are what Phase B found by running it. All four
stages are deterministic; §30 is about why.

---

## 1. The problem, and why "log the traffic" is not a solution to it

Everybody agrees you should evaluate an LLM feature against real traffic, and
almost nobody does, and the reason is not laziness. It is that the gap between
"we have logs" and "we have an eval set" is made of four separate jobs, each of
which is boring, and three of which are the kind of boring where a mistake is
invisible for six months.

The four:

- **The logs are not one shape.** The gateway writes chat completions, the
  rollout tool writes events with the input hashed out, somebody exported a CSV
  from the ticketing system. Each has a different name for the answer.
- **The logs contain customers.** Not incidentally — centrally. The interesting
  cases are the ones where somebody typed their order number, their address,
  their card. An eval set built from those is a database of personal data with a
  friendly filename.
- **Most of the logs are the same thing.** Twenty-five people wrote in about one
  outage. A dataset with all twenty-five measures one thing twenty-five times.
- **Nobody knows which ones matter.** Recency is not signal. "The model refused",
  "the judge failed it", "the customer said it was wrong" are signal.

This repository does the first two, deterministically, and lays out contracts for
the other two. That split is deliberate and §2 is about why.

## 2. Why ingestion and redaction are the whole of Phase A

The temptation with a tool like this is to start at the interesting end —
scoring, clustering, drafting criteria with a model — and treat ingestion as
plumbing to be got through.

That is backwards, and the argument is short. Every later stage reads what this
one wrote. If the record shape is loose, every later stage re-checks the same
things and each does it slightly differently. If the redaction is late, there is
a window of time in which a file on disk holds unredacted production text, and
"we delete it afterwards" is not a privacy property. If a bad line is dropped
silently, the coverage number stage 08 eventually reports is computed against a
denominator nobody can reconstruct.

So Phase A is the two stages where a mistake is permanent, and both of them are
deterministic code with no model anywhere near them.

## 3. Why the record schema is strict about the ok/failed split

A canonical record either has an `output_text` and no `error`, or an `error` and
no `output_text`. Both is refused. Neither is refused, with a message that
quotes the rulebook: *a failed read must not become a successful no-op.*

The alternative — allow both to be absent, treat an empty output as a failure —
is what almost every log pipeline does, and it is how an eval set ends up with
forty cases whose expected answer is the empty string. `chat-012` in the sample
is exactly that line, and it is rejected by name.

## 4. Why `bool` is refused everywhere an integer is expected

`isinstance(True, int)` is `True` in Python. A `latency_ms` of `True` is a
latency of one millisecond, and a `cost_micro_usd` of `True` is a cost of one
micro-USD, and both will be summed a million times before anybody notices. Every
integer coercion checks for `bool` first.

## 5. Why money is integer micro-USD and time is UTC with a `Z`

Both are the workspace rule and both are load bearing here for the same reason:
these numbers are summed across a window and compared across windows. A float
cost that is right to eleven decimal places is wrong in the twelfth, and a
timestamp with an offset is two representations of one instant that have to be
kept in step for ever.

The canonical record's `ts_utc` is `%Y-%m-%dT%H:%M:%SZ` and nothing else.
Offsets are resolved in `coerce.py` at the boundary; by the time a `Record`
exists the instant is already UTC.

## 6. Why a naive timestamp is an error rather than an assumption

`2026-09-05T10:00:00` with no offset is refused, by default, with a message
naming the setting that would accept it.

This is the decision most likely to annoy somebody, and it is the one I am most
confident about. A log written in Berlin and read in London is off by an hour for
the rest of its life, and nothing downstream will ever notice: every case will
still be a case, every count will still count, and the day boundaries will be
wrong. A mapping can set `[timestamp] naive_is_utc = true` and then the
assumption is written down in a reviewed file with somebody's name on the commit,
which is the entire difference.

## 7. Why the error hierarchy has exactly five categories

Because there are exactly five things a caller does about a failure: fix the
configuration and re-run (`ConfigError`), count this line and keep going
(`RecordError`), stop because the file is not what it claimed (`SourceError`),
stop because writing would leak (`RedactionError`), stop because what is on disk
contradicts what is about to be written (`WindowError`).

The line between `RecordError` and `SourceError` is the one that earns its keep:
a bad line is counted and the run continues, a bad *file* stops it. Collapsing
the two would make a typo in a mapping look like sixty thousand bad log lines.

## 8. Why a mapping is a TOML file and not a Python function

The obvious design is a plugin: each producer gets a function that takes a dict
and returns a record. It is more flexible and it is worse.

A mapping written as data can be diffed, reviewed, hashed, and recorded in a
manifest — and the manifest is the thing that lets somebody in a year's time
establish what "the answer field" meant when a window was built. A mapping
written as code can do anything, which means reviewing it is reviewing code, and
recording *which* mapping produced a window means recording a git SHA of the
whole repository rather than a hash of one file.

The manifest records `mapping` and `mapping_sha256` per source for exactly this
reason.

## 9. Why extractors are a fixed registry and not an expression

Some things a dotted path cannot express, and the biggest is the one everybody
needs: the input is not a field, it is *the last user turn of a conversation*.

The lazy answer is to let a mapping supply a small expression and `eval` it. The
answer here is a registry of four named functions — `identity`,
`openai_last_user_message`, `openai_assistant_message`, `join_text` — and an
unknown name is a typed error that lists the four.

A mapping file is something somebody edits in a hurry with a vendor's
documentation open beside it. The blast radius of a typo in one should be an
error message, not arbitrary code execution.

## 10. Why `MISSING` is a sentinel and not `None`

A log line whose `feedback` is literally `null` and one that has no `feedback`
key are different facts. The first says "we asked and there was none"; the
second says "this producer does not record feedback". Collapsing them means a
mapping pointed at a field that does not exist looks exactly like a field that
is always empty, and nobody ever finds the typo.

`extract_path` returns `MISSING` for absent and `None` for null, and the two are
distinguished all the way to the record.

## 11. …and why a blank string counts as absent anyway

The exception, and it is a real one. Every CSV cell somebody left empty arrives
as `""`, not as null. Treating that as a present-but-empty value fails the whole
row over a column nobody filled in — which is what happened the first time the
sample CSV was ingested, with its empty `rating` column.

So `_absent()` treats a blank string as absent. A *required* field that is blank
is still a `MissingFieldError`, so nothing is lost at the top end.

## 12. Why the sidecar join exists at all

`regress-rollout` — this workspace's project 9 — logs `input_sha256` and not the
ticket. That is the right call for a rollout monitor: it never needs the input
text, and a log that stores less leaks less.

It is exactly the wrong shape for an eval dataset, where the input text *is* the
case. So `mappings/regress_rollout_events.toml` declares a `[sidecar]`, and the
operator passes the traffic file the rollout was served from. The two halves are
rejoined by hash, explicitly, on a command line — rather than by ingestion
quietly deciding that a missing input is fine.

A sidecar miss is a skipped row naming the key, never a nearest match. An eval
case built on the wrong input is worse than no case.

## 13. Why `--format` and the mapping's `source_format` must agree

They are two statements of the same fact and one of them can be wrong. Reading a
JSONL file as CSV produces one enormous row with a header made of JSON; reading
a CSV as JSONL produces a file of parse failures. Neither is a useful error, and
neither is worth guessing between: the run stops and names both.

## 14. Why `prompton_events.toml` is committed despite being unverified

It says so in its own header, in capitals, in the second paragraph: the shape
was written from a specification rather than from an export anybody here has
run.

It is committed because the mapping layer needs two examples to look like a
mapping layer rather than a special case for one vendor, and because nested
paths — `generation.usage.input_tokens` — are the second thing a mapping has to
be able to do and no other built-in exercises them. What it is not is a claim
about a vendor's schema, and the header says how to fix it: copy the file, edit
the paths, nothing downstream knows or cares.

## 15. Why redaction runs before the write and not as a separate pass

There is no moment at which unredacted production text exists in a file this
tool wrote. Not one that is cleaned up afterwards, not one that lives inside a
temporary directory: none.

A two-pass design — ingest, then redact — is easier to write and easier to test,
and it means that between the two passes there is a file on disk full of
customer data, and that a crash between them leaves it there. "We delete it
afterwards" is not a privacy property. It is a hope about a code path.

## 16. Why the writer re-checks what the redactor already did

`[privacy] redact = true` is a promise, and a promise kept by a habit somewhere
upstream is a hope about code somebody might refactor next month.

`WindowStore.append_records` runs the five structural detectors over every
record about to become bytes and refuses the whole batch if one still matches.
That refusal is what makes the default a guarantee. It has a cost — the
detectors run twice — and the cost is a rounding error next to being wrong about
this once.

## 17. Why the guard uses five of the eight classes

`EMAIL`, `CARD`, `IBAN`, `SSN` and `IPV4` are *structural*: a shape a regex can
be sure about, two of them checksummed. A match is almost never wrong.

`PHONE`, `ADDRESS` and `NAME` guess. A guard built on them would refuse an
honest ingest because a product code looked dialable or because a description
mentioned 10 Downing Street. They are still redacted; they are just not what the
refusal is built on.

## 18. Why Luhn, specifically

Because the alternative destroys the dataset. "Why was order 1234567812345678
charged twice" is a support ticket, and a redactor that blanks every long number
turns it into "why was order [CARD_1] charged twice", which is not a case about
anything.

Luhn costs one pass over the digits, is what every payment form on the internet
uses, and separates `4242 4242 4242 4242` from `1234567812345678` exactly. It is
not proof that a number is a live account; it is proof that it is card-*shaped*,
which is the right question for a redactor.

The card regex is also anchored to non-digits at *both* ends, so a run of digits
yields exactly one candidate rather than a sliding window of them. Without that,
a 24-digit machine id containing a Luhn-valid 16-digit window would have its
middle redacted and its ends left.

## 19. Why the email pattern has no word boundary at the front

The single most common way an address survives a naive redactor: it is inside a
URL, surrounded by slashes rather than spaces. `https://app.example.com/users/
sam@example.com?ref=1` is in the sample precisely so that the test suite fails if
this ever regresses.

The local-part character class excludes `/` and `:`, which is what stops the
match starting too early. There is a test asserting the redacted text reads
`app.example.com/users/[EMAIL_1]`.

## 20. Why tokens are stable across a whole window

`[EMAIL_1]` in one record and `[EMAIL_1]` in another mean the same address. That
is the difference between "the same customer wrote in three times" and "three
customers wrote in once", and therefore the difference between one eval case and
three.

A `Redactor` is stateful for the length of a run and holds the map in memory. It
is never written anywhere — not to the manifest, not to the report, not to a
sidecar file. The report counts classes and distinct values and quotes nothing.

Canonicalisation matters here too: `SAM@Example.com` and `sam@example.com` are
one mailbox, `4242 4242 4242 4242` and `4242-4242-4242-4242` are one card.
Giving either pair two tokens would silently split one customer in half.

## 21. Why the name heuristic needs an honorific, and over-redacts when it fires

Without an honorific, "Lumen Desk" and "Susan Calvin" are the same string to a
regex. Blanking every Title Case pair would remove every product name from the
dataset, which is most of what a support ticket is about. So the heuristic fires
only behind `Mr`, `Mrs`, `Ms`, `Miss`, `Mx`, `Dr`, `Prof`, `Sir`, `Dame`, `Rev`,
`Fr`, `Capt`, `Sgt`, `Lord`, `Lady`.

When it does fire it takes up to two following capitalised words, which means
"Dr Calvin Called back" becomes "[NAME_1] back". That is an over-redaction and it
is the direction to over-redact in: it loses a word of context rather than a
surname. There is a test asserting exactly this, named after the trade-off rather
than after the behaviour.

The allowlist is the correction for the other direction. "We stock Dr Pepper"
would otherwise lose the product, and no regex can know that. `[privacy]
name_allowlist` is matched case-insensitively against the whole span.

## 22. Why deduplication is exact, on the input, after redaction

Three choices, three reasons.

**Exact**, not near: near-duplicate clustering is stage 04's job, where it gets a
threshold somebody argued about instead of happening silently at the door.

**The input**, not the whole row: the dataset is keyed on what was asked. Two
different answers to one question is one eval case with a disagreement in it, and
noticing that disagreement is a later stage's job.

**After redaction**, not before: two tickets identical except for the customer's
name collapse into one record. For an eval dataset that is correct — they are one
case — and it is the only ordering that lets a window be deduplicated without
keeping the raw text around to compare against.

## 23. Why the counts are checked and not merely stored

`Manifest.__post_init__` asserts two sums before anything is written:

    lines_read == rows + blank_lines + unparsed
    rows       == records_written + duplicates_dropped + invalid

Between them, every line of every source has exactly one home. "We ingested
58,102 of 60,000 lines" is only a useful sentence if the missing 1,898 are
enumerated somewhere, and the arithmetic is what proves they are.

This invariant caught a real double-count during construction, twice — see §27.

## 24. Why a bad line has two buckets rather than one

`unparsed` is a line the source format could not read at all. `invalid` is a row
that read perfectly and could not become a record.

They are different problems with different fixes. A thousand unparsed lines means
the export is damaged, and that is a conversation with whoever produces it. A
thousand invalid rows almost always means the mapping is pointed at the wrong
field, and that is a one-line edit to a TOML file. A single "rejected" number
hides which, and the difference is a day.

## 25. Why a partial success exits 1

Because nobody reads the report of a command that succeeded. A run that rejected
two thousand lines and returned 0 is worse than one that crashed: the crash gets
investigated.

Four codes: 0 worked, 1 worked with rejections, 2 ran and produced nothing, 3
could not run. 2 and 3 are separate because "your log contains nothing usable"
and "your configuration is wrong" are different mornings.

## 26. Why nothing is written when nothing survives

Not even an empty window with a manifest describing it. A window on disk is a
thing later stages read and a thing a person believes in; an empty one with a
tidy manifest is worse than an absence, because an absence is obvious.

The run prints the first few failures instead, and exits 2.

## 27. What running it found that reasoning about it did not

Four bugs, all caught by executing the thing rather than by reading it, and all
worth keeping in the record.

**Tokens numbered backwards.** Redaction replaces right to left, because every
replacement changes the length of the string and only that direction leaves the
remaining offsets valid. I allocated the token numbers in the same pass, so
`"sam@example.com and kim@example.com"` came out as `[EMAIL_2] and [EMAIL_1]`. The
fix is two passes: number left to right, replace right to left. The lesson is
that "replace backwards" is a fact about string mutation and had quietly become a
fact about numbering, which it is not.

**Rows counted twice.** A row that read fine and failed to become a record was
counted both as a row and as a rejection, so `lines_read` was two short of the
sum of its parts on the very first end-to-end run. The invariant in §23 refused
to build the manifest and named the numbers. The fix is §24's two buckets, which
is a better design than the one I set out to write — the constraint produced it.

**An IP address at the end of a sentence.** The IPv4 pattern ended with
`(?![\d.])`, to stop a fifth octet. `"…timing out from 192.168.1.14. Is that
blocked?"` therefore matched nothing, because a full stop is a dot. The correct
guard is `(?!\.?\d)`: what must be refused is a dot *followed by a digit*. This
one is the reason the sample log is written in prose rather than as a list of
values — the bug is invisible against test fixtures that end in whitespace, and
it was found the first time the real sample was ingested from a shell.

**An invoice number read as a telephone number.** The CSV sample contains
`invoice 9911-2233`, and the first phone pattern took it: two groups of digits
separated by a hyphen, eight digits in total, above the seven-digit floor. The
fix narrows the heuristic to three shapes — a country code, a parenthesised area
code, or *three* groups — because every genuine number in the test set has one of
the three, so the extra group costs nothing and removes a whole class of false
positive. Found the same way as the IP bug: by running the committed sample
through the real command line and reading what came out.

## 28. Why the sample log is committed, and why every file in it says so

`samples/` is thirteen lines of invented traffic. Its README says `SYNTHETIC` on
its first line, the JSONL and CSV files carry `.synthetic.` in their names, and a
window ingested with `--synthetic` says so in its manifest, on the first line of
its report, and on the first line of the terminal output.

The point of the sample is not to demonstrate a happy path. It is to hold, in the
repository, one of everything that is hard: the email inside a URL, the Luhn-
valid card beside the order reference that is not one, `Dr Pepper` on the
allowlist, an IP at the end of a sentence, the same complaint twice, a line that
is not JSON, and a line that reads perfectly and is not a record. Running it is
supposed to exit 1.

## 29. What Phase A does not claim

- **No stage here has ever called a model.** There is no live evidence in this
  repository because there is nothing to be live about yet: stage 06 is the first
  stage that will call one, and it is PLANNED. The dependency on project 1 is
  pinned and unused, and §CONTEXT.md says which seams it is pinned for.
- **The heuristic detectors miss things.** A name with no honorific survives. An
  address in a language whose street words are not in the list survives. This is
  a redactor for support traffic in English, tested against cases somebody chose,
  and it should be pointed at your own data with `loghog redact` before it is
  trusted with a window of it.
- **The mapping for `prompton_events` is unverified.** §14.
- **`records/` is gitignored, not encrypted.** The privacy property this tool
  provides is that personal data is removed before it is written. It provides
  nothing at all about the disk it is written to.

---

# Phase B

Stages 03, 04, 05 and 09 — scoring, clustering, selection and drift.

## 30. Why none of Phase B calls a model either

The obvious design for "which of these records is interesting" is to ask a
model. It would work, and it is the wrong tool for three separate reasons.

**It would not be explainable.** A number a model produced cannot be recomputed,
so a disagreement about a ranking becomes a disagreement about a model, which is
not an argument anybody can win. Thirteen signals with integer weights produce a
score somebody can recompute in their head from the list printed beside it, and
an argument about that is a one-line diff in a reviewed file.

**It would not be reproducible.** A window scored twice would rank differently,
and stage 05's shortlist is meant to be a function of the window.

**It would cost a call per record.** The whole point of scoring is to decide
which handful of records are worth a model call in stage 06. Spending one per
record to decide that is spending the budget on the decision instead of on the
work.

So Phase B is deterministic in its entirety, and stage 06 remains the only stage
that will ever leave the machine.

## 31. Why a score is a plain sum of integers

No normalisation, no decay, no multiplication, no per-window rescaling. The
score printed on a record is the sum of the weights of the signals listed beside
it, and the arithmetic is checkable with a pencil.

Every alternative was more accurate and less useful. Normalising to 0-1 makes
two windows comparable and makes a single score meaningless on its own.
Recency decay makes yesterday's outage outrank last week's unfixed one. Both
would have made "why is this record ranked above that one?" a question only the
code can answer, and the person asking it is usually the person who has to
defend the dataset.

## 32. Why the patterns are code and the weights are configuration

The line is between a *definition* and an *argument*.

"What does a prompt injection look like?" is a definition. It belongs with tests
naming each shape, in a fixed registry, for the same reason extractors are a
fixed registry: a regex read from a configuration file is a regex nobody
reviewed, and a badly written one is a run that never finishes over somebody
else's log.

"Is a refusal worth more than a slow answer?" is an argument, and it belongs in
`[score.weights]` where changing it is a diff somebody reviews.

The feedback vocabularies sit on the configuration side of that line, because
whether "up" or "5" or "helpful" means positive is a fact about somebody's
product rather than about the world.

## 33. Why "not evaluated" is a first-class outcome, and sometimes exits 1

The most dangerous number a scoring report can print is a zero it did not earn.
"No version disagreements in this window" and "version disagreements cannot be
seen in this window" are different facts, and a table that renders both as `0`
tells the reader the first when the truth is the second.

So every signal that produced no answer is listed with its reason, and the
reasons are of two kinds:

- **an absence somebody chose** — no goldens file was passed, no mapping in the
  window declares `[expect] output_json`, the window is too small for a p95.
  These exit 0. Nothing is wrong.
- **an impediment the window imposes** — see §34, and the case where two sources
  in one window disagree about whether outputs should parse. These exit **1**,
  the same code a partial ingest returns, for the same reason: nobody reads the
  report of a command that succeeded.

The distinction matters because a code that was 1 on every run would stop being
read, which is exactly the failure it exists to prevent.

## 34. Why a deduplicated window cannot show a version disagreement

This one fell out of writing the signal and is the clearest thing Phase B
learned about Phase A.

Stage 01 deduplicates on the SHA-256 of the normalised, redacted **input** —
§22, and it is right. But `version_disagreement` asks a question about *two
records with the same input*: one arm passed, another failed. In a deduplicated
window those two are already one record, and the signal is looking for something
the ingester correctly removed.

The options were to change dedupe to key on `(input, prompt_version)`, or to say
so. Changing it would make two arms answering one question two eval cases, which
is wrong — they are one case with a disagreement in it, which is exactly what
§22 argues. So the scorer reads the manifest, and when `dedupe_enabled` is true
it reports the signal as **blocked**, names `[dedupe] dedupe = false` as the fix,
and exits 1.

A window ingested to *find disagreements* is a different window from one
ingested to *build a dataset*, and it is better for that to be a sentence in a
report than an assumption in a hash.

## 35. Why near-duplicate detection uses shingles and not embeddings

An embedding threshold of 0.83 is a number nobody can explain, nobody can check
by hand, and nobody can reproduce without pinning a model. A shingle overlap of
0.6 is a number a reviewer can verify with a pencil by writing out two sets of
five-word phrases.

When somebody later asks "why did these two tickets merge", the answer here is a
list of phrases they shared. "They were close in vector space" is not an answer,
and the person asking is usually the person who has to defend the dataset to
somebody else.

It is also the only choice that keeps the whole of Phase B offline and free.

## 36. Why normalisation collapses redaction tokens

`[EMAIL_1]` and `[EMAIL_2]` both mean "an address was here". The number in them
is *which customer wrote in* — which is precisely the fact stage 02 worked to
make stable across a window (§20).

Left in, that number would split one cluster by customer: twenty-five people
writing in about one outage, each with their own token, would be twenty-five
clusters. So normalisation rewrites `[CLASS_N]` to `[class]` **before** digits
are stripped — in the other order the token becomes `[EMAIL_]` and two tokens of
one class are still two different words.

## 37. Why a text with no words is always a singleton

An input of `"12345 67890"` normalises to nothing: the digits go, and there are
no other words. The tempting implementation gives it a shingle set of `{""}`,
and then two such records have a Jaccard of 1.0 and cluster together.

That is two absences being called a match. `jaccard(∅, ∅)` is conventionally 1
and is **0** here, records with no shingles never reach the LSH stage at all, and
the cluster report says how many there were. A bare order number is not evidence
that two tickets are about the same thing; it is evidence of nothing.

## 38. Why the base hash is BLAKE2b and not Python's `hash()`

`hash()` of a `str` is salted per interpreter process. It is stable within one
run and different in the next.

An implementation built on it passes every unit test — signatures are
self-consistent, identical sets agree, disjoint sets do not — and silently
produces a different partition of the same window on the next invocation.
Nothing would fail. The clusters in `clusters.json` would simply stop matching
the ones in yesterday's, and the first person to notice would be someone
comparing two drift reports six weeks later.

The catch is a test that runs the module in two subprocesses under two values of
`PYTHONHASHSEED` and compares the output. It is the only kind of test that
catches this, and it is the reason this section exists.

## 39. Why LSH only proposes, and the exact Jaccard disposes

Banding gives each pair a probability of becoming a candidate:
`1 - (1 - s^r)^b` for similarity `s`. It is a smooth curve, not a threshold.

A tool whose merge rule was that curve would have a threshold that is a
probability, and "these two merged because they collided in a band" is not a
sentence anybody can argue with. So banding is used as a **blocking** step and
nothing more: every candidate pair gets its true Jaccard computed and is merged
only if it clears the configured number.

That costs one set intersection per candidate — 96 of them on the suite's
70-record corpus, against 2,415 pairs compared exhaustively — and it buys a
partition whose every merge is a number a reviewer can recompute.

The measured consequence, from `tests/test_cluster_run.py` against a brute-force
comparison of all 2,415 pairs: **precision 1.000, recall 0.960**. Precision is 1
by construction. Recall is where the banding actually costs something, and the
suite asserts it rather than assuming it, because a clustering tool that does not
measure what its blocking step lost is a tool making a claim nobody checked.

## 40. Why a cluster publishes its weakest link

Union-find gives single-linkage clustering, which is transitive: A merges with
B, B merges with C, and A and C are in one cluster even if their own similarity
is below the threshold.

That is a real property of this design rather than a bug — a chain of
paraphrases is one complaint, and cutting the chain would split it. But it means
"this cluster's similarity is 0.81" would be a number about one pair presented
as a number about a group. So a cluster reports the **lowest** exact Jaccard
among the edges that built it, which is the honest summary and the one a reader
can act on: if the weakest link looks wrong, the threshold is wrong.

Union is by *name* rather than by rank or size, so the partition and its labels
do not depend on the order the pairs arrived in.

## 41. Why selection has four caps and why their order is fixed

1. **already in the goldens**, first, so that a case you already hold never
   consumes the slot a new one needed;
2. **the cluster cap**, so that twenty-five tickets about Tuesday's outage
   cannot spend twenty-five of the budget on one subject;
3. **the stratum quota**, so that the dataset is not made entirely of the
   loudest failure mode of that week;
4. **the global cap**, last, so that it is only ever blamed for records that
   would otherwise have been taken.

The order is what makes the counts in `selection.md` mean something. Put the
global cap first and every refused record is attributed to it, and the report
stops being able to say whether a quota would have stopped them anyway.

## 42. Why a record's stratum is its highest-weighted signal

A record that fired `error`, `length_outlier` and `tiny_input` has to be counted
against exactly one quota, or the quotas do not add up.

Counting it against the highest-weighted signal counts it against the evidence
that actually made it interesting. Ties are broken by the fixed registry order,
so two runs over one window put every record in the same stratum — and a signal
name a later build invented, appearing in a scores file this build reads, falls
back to `ordinary` rather than being guessed into a quota nobody configured.

## 43. Why every stratum must be named in configuration, zero included

An absent quota is a silent zero, and a silent zero is a stratum that never gets
chosen for a reason nobody wrote down. So `[select.quotas]` must name every
signal and `ordinary`, and a missing one is refused at load with the name in the
message.

Zero itself is allowed, and means "never take this kind" — which is a decision
somebody made. Note the asymmetry with `[score.weights]`, where a weight of zero
for *every* signal is refused: a zero quota says "not this kind of case", which
is a choice, while all-zero weights say "no evidence is worth anything", which
would make selection alphabetical.

## 44. Why an unfilled stratum does not make the exit code 1

Most windows contain no prompt injections and no format violations. If an
unfilled quota returned 1, `loghog select` would return 1 on almost every run,
and a code that is always 1 conveys nothing — which is the same argument §25
makes for why a *partial* ingest must not return 0.

So the shortfall is printed, on the terminal and in `selection.md`, and never
topped up from another stratum. What does return 1 is **truncation**: the global
cap stopped a record that would otherwise have been taken, which means there was
more worth having and somebody should look.

## 45. Why the drift stage is numbered 09 and is not in the pipeline

Stage 08 (`08_health`, PLANNED) asks whether the *dataset* is still about the
system, and needs a goldens file to do it. Stage 09 asks whether the *traffic*
has moved, and needs no goldens file, no shortlist and no model — only two
windows that have been scored and clustered.

They are neighbouring questions with different inputs and different answers, and
folding the second into the first would mean you could not ask "has anything
changed?" until after you had built a dataset to compare against. The number is
last because it is out of the pipeline, not at the end of it.

## 46. Why the KS statistic is reported as a statistic

The two-sample Kolmogorov-Smirnov statistic is the largest gap between two
empirical distribution functions. There is a well-known p-value for it, and this
tool does not compute one.

Two windows compared here are two windows a person picked — last week and this
week, before a deploy and after it. That is not a sampling design under which a
p-value means anything, and printing one would dress a judgement call up as a
test. `0.62` with "inputs got longer" beside it is the honest thing to publish.

The same reasoning names the Wilson comparison `separated` rather than
`significant`: two non-overlapping intervals are a conservative screen, and
calling it a test would be a claim this tool has not earned.

## 47. Why `wilson_interval` is imported and `ks_statistic` is written

Both are short. The difference is that project 1 already has one of them.

A rate interval computed by two implementations of one formula is a
disagreement waiting to happen in the one place nobody would think to look — a
coverage figure in this repository disagreeing by half a percent with the same
figure in project 1, for six months, until somebody diffed two reports. So
`compare.wilson_interval` is imported, and a test asserts the imported name is
project 1's own function object rather than a lookalike with the same name.

The KS statistic is thirty lines of pure Python and nothing else in the
workspace has one. A dependency for thirty lines is a dependency for thirty
lines.

## 48. Why the manifest schema went to version 2

`format_violation` needs to know whether a producer's output was *supposed* to
parse as JSON. That is a fact about a mapping, and the stage that checks it runs
days later against a window rather than against a file — so the flag has to
travel, and it travels in the manifest, per source.

A window written by version 1 cannot say. Defaulting it to "no" would make the
signal permanently quiet on exactly the windows somebody most wanted it for, so a
version-1 manifest is refused and the window is re-ingested — one command over a
per-run artefact that was never committed.

When two sources in one window disagree about the flag, the signal is refused
rather than guessed at: a record does not carry which source it came from, and
guessing would apply one producer's contract to another producer's output.

## 49. What running Phase B found that reasoning about it did not

Three, and the first is the one worth the section.

**A refusal pattern that needed two "I"s.** The `cannot_help` regex was written
around the apologetic shape — "I'm sorry, but I can't help with that" — and
required the word "I" twice, once before the apology and once before the
inability. `"I cannot assist with this request."` therefore matched nothing at
all, which is the single most common refusal shape a model produces. The fix is
two alternatives in one pattern: the apologetic form, and a flat
`I cannot <verb>` pinned to a list of verbs so that "I can't find the order
number you gave me" stays a support answer rather than becoming a refusal. Found
by writing the test table first and watching two of five rows fail.

**Two configuration keys that shadowed each other.** `[score]` had
`non_ascii_ratio` as a threshold and `[score.weights]` had `non_ascii_ratio` as a
weight; likewise `negative_feedback`. Both are legal TOML in different tables and
both are a trap for anybody editing the file — and they broke a test that edits
one line by key, which is how they were found. Renamed to
`non_ascii_threshold`, `negative_feedback_words` and `positive_feedback_words`.
The lesson is that a configuration file is read by people using find, not by a
parser using scopes.

**Version disagreement against a deduplicated window** — §34. Not a bug in the
code; a genuine contradiction between two correct decisions, found by writing
the signal and having nothing to point it at. It became a reported impediment
rather than a silent zero, which is a better outcome than either of the two
changes that would have hidden it.

## 50. What Phase B does not claim

- **Still no model call, anywhere.** Six of nine stages are built and none of
  them has ever left the machine. There is no live figure in this repository
  because there is nothing to be live about: `06_label` is the first stage that
  will call a model, and it is PLANNED. Every number reported here came from
  `uv run pytest` or from the committed samples through the real command line.
- **The precision and recall figures are against a synthetic corpus.** 1.000 and
  0.960 are measured, deterministic and reproducible, and they are measured
  against ten families of paraphrases somebody wrote for the purpose. They say
  the blocking step loses about four per cent of the pairs the exact comparison
  would find *on that corpus*. Point it at your own log before believing the
  second decimal place.
- **Thirteen signals are not the thirteen signals.** They are the ones that were
  cheap, deterministic and defensible. A real deployment will want one about its
  own domain, and adding one is a function, a name in `SIGNAL_NAMES`, a weight
  and a quota.
- **The thresholds are the ones the samples needed.** `jaccard_threshold = 0.6`
  is where support traffic sat in an invented corpus. It is the first number to
  change against your own log, and the report prints it every time so that
  changing it is an argument somebody can have.
