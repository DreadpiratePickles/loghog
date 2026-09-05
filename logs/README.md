SYNTHETIC — every line in this directory is invented. No customer wrote any of it, no
system produced any of it, and every name, address, card and account number in it was
made up for the purpose.

# Two demo windows

`demo_window_a.jsonl` and `demo_window_b.jsonl` are 120 records each, in the shape
almost every gateway logs by default: one JSON object per line, a `messages` array,
a `usage` block and a latency. They read with the committed
[`openai_chat_jsonl`](../mappings/openai_chat_jsonl.toml) mapping and nothing else.

They exist because a pipeline demonstrated on thirteen lines is a pipeline nobody
has watched work. Clustering on thirteen singletons proves nothing; a p95 needs
twelve observations before it means anything; and a drift comparison between two
windows needs two windows.

| | `demo_window_a.jsonl` | `demo_window_b.jsonl` |
|---|---|---|
| Records | 120 | 120 |
| Week | an invented Monday | the Monday after it |
| Subjects | 12 shared with B, 4 of its own | the same 12, plus 6 of its own |
| Errors | about 1 in 20 | about 1 in 6 |
| Negative feedback | about 1 in 7 | about 1 in 4 |

The difference between the two columns is the point. B is a week in which
something broke: the error rate roughly triples, negative feedback nearly
doubles, and about a third of its subjects are ones A had never seen. `loghog
drift --from a --to b` is supposed to say so, and if it ever stops saying so, one
of us is wrong.

## What is planted in them, and why

**Personal data, eight classes of it, once each per window.** An email address, an
email address inside a URL, two Luhn-valid card numbers, an SSN-shaped reference,
an IBAN, a private IPv4, an international phone number, a street address, and two
names behind honorifics. There is also an order reference —
`1234567812345678` — that is sixteen digits and **fails Luhn**, so it is not a
card and must survive redaction. A redactor that blanks it has destroyed the case.

**Injection attempts**, two in A and three in B, one for each pattern in the fixed
registry: an instruction override, a "repeat everything above", a request for the
system prompt, and a roleplay jailbreak.

**Refusals**, in the assistant's turn rather than the customer's: "I'm sorry, but
I can't help", "I am unable to", and "As an AI language model".

**Near-duplicates.** Twelve subjects appear several times each with a different
closing sentence, so a window is a set of families rather than a set of strangers,
and the cluster cap has something to do.

**One record in Japanese** and **one that says only "hello?"**, so
`non_ascii_ratio` and `tiny_input` have something to fire on.

Four of the thirteen signals cannot fire here, and that is a fact about the
format rather than an omission: this log carries no judge verdicts, no prompt
version and no declared output contract, so `judge_failure`,
`version_disagreement` and `format_violation` have nothing to read, and `novelty`
needs a goldens file passed with `--existing`. The
[`judged_summaries`](../samples/judged_summaries.synthetic.jsonl) sample is the
one that exercises all thirteen.

## Reproducing them

They were generated once, from a seeded script, and committed as data. The
generator is not in the repository: a file that is regenerated is a file whose
diff is noise, and these are inputs to a documented example rather than a fixture
anybody should be editing. If you want different demo data, write your own log —
that is the whole point of a mapping.
