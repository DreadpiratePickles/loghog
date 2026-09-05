SYNTHETIC — every line in this directory is invented. No customer wrote any of it.

# Sample logs

Two files, in the two formats `loghog ingest` reads, written to exercise the
things that are hard rather than the things that are easy.

| File | Format | What it is for |
|---|---|---|
| `support_chat.synthetic.jsonl` | jsonl | An OpenAI-style chat log. Read with the `openai_chat_jsonl` mapping |
| `support_tickets.synthetic.csv` | csv | The same kind of traffic exported flat from a ticketing tool. Read with `samples/support_csv.toml` |

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
