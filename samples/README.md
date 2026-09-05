SYNTHETIC — every line in this directory is invented. No customer wrote any of it.

# Sample logs

Three files, written to exercise the things that are hard rather than the things
that are easy.

| File | Format | What it is for |
|---|---|---|
| `support_chat.synthetic.jsonl` | jsonl | An OpenAI-style chat log. Read with the `openai_chat_jsonl` mapping |
| `support_tickets.synthetic.csv` | csv | The same kind of traffic exported flat from a ticketing tool. Read with `samples/support_csv.toml` |
| `judged_summaries.synthetic.jsonl` | jsonl | Judged summary events with verdicts, two prompt versions and JSON outputs. Read with `samples/judged_summaries.toml` |

## What is deliberately in them

Every personal detail below is fictional, and the card numbers are the vendors'
own published test numbers — the ones every payment stack on the internet ships
in its documentation. They are not accounts and never were.

- **an email inside a URL**, which is how an address survives a naive redactor;
- **a Luhn-valid card** next to **a sixteen-digit order reference that is not
  one**, because a redactor that blanks both has destroyed the case;
- **an IP address**, **a UK phone number**, **a US phone number** and **an SSN**;
- **a street address** and **a name behind an honorific**;
- **`Dr Pepper`**, which is on the allowlist in `loghog.toml` and must survive;
- **the same complaint twice, worded identically**, so deduplication has
  something to do;
- **two lines that are meant to fail**: one that is not JSON at all, and one
  whose conversation never got an assistant turn and names no error either;
- **a blank line**, because real exports have them.

Ingesting this file is the fastest way to see what the tool does:

```bash
uv run loghog ingest --input samples/support_chat.synthetic.jsonl \
    --format jsonl --mapping openai_chat_jsonl --window demo --synthetic
```

Expect a non-zero exit code. Two of the lines are broken on purpose, and a run
that quietly returned 0 over them would be the failure this tool exists to
prevent.

## The judged sample, and what it is for

`judged_summaries.synthetic.jsonl` is thirteen invented events written so that
**twelve of the thirteen scoring signals fire on it**. That is the whole reason
it exists: a scoring stage demonstrated against a log where nothing fires is a
scoring stage nobody has seen work, and a signal that quietly stopped firing
would cost nothing and be noticed by nobody. The suite asserts the exact count
for each.

What is deliberately in it, one per signal: a failed call, a failed judged
criterion, a customer who said "up" about an answer the judge failed, negative
feedback, two prompt versions reaching different verdicts on one question, a
prompt-injection attempt, a refusal, two outputs that should have been JSON and
are not, a paraphrase of another line, an input in Japanese, a one-word message,
and one very slow request. The thirteenth signal is `novelty`, which needs a
goldens file:

```bash
# dedupe off, because deduplication is on the input — so with it on, the two
# prompt versions answering one question are already one record and stage 03
# says so rather than reporting zero disagreements.
sed 's/^dedupe = true/dedupe = false/' loghog.toml > /tmp/nodedupe.toml

uv run loghog ingest --input samples/judged_summaries.synthetic.jsonl \
    --format jsonl --mapping samples/judged_summaries.toml \
    --window judged --synthetic --config /tmp/nodedupe.toml
uv run loghog score   --window judged --config /tmp/nodedupe.toml
uv run loghog cluster --window judged --config /tmp/nodedupe.toml
uv run loghog select  --window judged --config /tmp/nodedupe.toml
```

Its mapping is also the only one that sets `[expect] output_json`, which is the
one mapping flag a later stage reads.
