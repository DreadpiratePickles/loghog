# Stage: 02_redact — BUILT (Phase A)

Replace every piece of personal data with a stable token **before anything is
written**, and refuse to write text that still carries any.

## Objective

Make it impossible for production personal data to reach a file this tool wrote,
while keeping everything about the text that makes it worth writing down.

Those two goals fight, and the whole design is where the line was drawn. A
redactor that blanks every long number destroys "why was order 1234567812345678
charged twice", which is the case. A redactor that only matches whitespace-
delimited addresses misses the one inside a URL, which is most of them.

## Inputs

| Path or source | Layer | Authority | Required | Relevant section |
|---|---:|---|---:|---|
| The text fields of a built record | 4 | Authoritative | Yes | `input_text`, `output_text`, `feedback`, `error` |
| `loghog.toml` | 3 | Authoritative | Yes | `[privacy] redact`, `[privacy] name_allowlist` |

This stage has no output directory and no command of its own to write anything.
It runs inside stage 01's write path. `loghog redact` exists so a person can
point it at their own text and see what would survive, and it writes nothing.

## Process

1. **Detect**, over the original text, in eight classes. Five are *structural* —
   `EMAIL`, `CARD`, `IBAN`, `SSN`, `IPV4` — with a shape a regex can be sure
   about, two of them checksummed. Three are *heuristic* — `PHONE`, `ADDRESS`,
   `NAME` — and each is deliberately narrow: a phone needs a country code or two
   separated groups, an address needs a house number *and* a street word, a name
   needs an honorific.
2. **Validate.** A card-shaped run of digits is a card only if it passes Luhn. An
   IBAN-shaped string is one only if it is 15-34 characters. A phone-shaped
   string is one only if it has seven digits and is not a date.
3. **Allowlist.** A `NAME` match whose text is in `[privacy] name_allowlist` is
   dropped, case-insensitively. This is the correction for "we stock Dr Pepper",
   and it cannot be a regex.
4. **Resolve overlaps** once, by a fixed priority, so a Luhn-valid card is one
   `[CARD_1]` rather than a card with a phone number inside it.
5. **Number in reading order, replace in reverse.** The first address in a window
   is `[EMAIL_1]`; the replacement pass runs right to left so that each edit
   leaves the offsets of the spans still to be replaced exactly where they were.
6. **Re-check at the door.** `WindowStore.append_records` runs the five
   structural detectors over every record about to be written and refuses the
   whole batch if one still matches.

## Outputs

| Path | Schema or format | Consumer |
|---|---|---|
| The redacted text fields of each record | Same fields, tokens substituted | Stage 01's writer, then every later stage |
| A `RedactionReport` | `{enabled, by_class, distinct_by_class, total, texts_seen, texts_changed}` | The manifest and the terminal |

The report counts and never quotes. The map from token back to value lives in
memory for the length of one run and is never written anywhere.

## Verify

- `tests/test_privacy_detect.py` — 68 cases, every one of them something
  somebody actually types: an email inside a URL, a `mailto:`, an address in
  angle brackets, a Luhn-valid card beside a sixteen-digit order reference, a
  24-digit machine id containing a Luhn-valid window, an IP at the end of a
  sentence, a date that is shaped exactly like a phone number, a Title Case pair
  that is a product.
- `tests/test_privacy_luhn.py` — the vendors' own published test numbers, and the
  same numbers with one digit changed.
- `tests/test_privacy_redact.py` — token stability within a text, across calls
  and across spellings; that the report never contains what it removed; that
  re-running over already-redacted text is a no-op.
- `tests/test_window_store.py` — the write guard, including that a refused write
  leaves nothing behind.
- End to end, `tests/test_ingest_run.py` asserts on the bytes of the written
  file: no address survives, the URL-embedded one was the one caught, the card is
  gone, the order reference is not, and `Dr Pepper` is still there.

## Approval

Turning redaction off requires two switches in two places: `[privacy] redact =
false` in a reviewed configuration file **and** `--allow-unredacted` on the
command line. The window's manifest then records `redacted: false` for ever, its
report says `UNREDACTED` on its first line, and appending an unredacted run into
a redacted window makes the whole window unredacted — because a window is only as
private as its least careful run.

## Failure Behavior

| Situation | What happens |
|---|---|
| `[privacy] redact = false` without `--allow-unredacted` | The run is refused before a line is read. Exit 3 |
| A record still carries structural PII after redaction | `UnredactedWriteError`, naming the record id and the class and **not** the value. The whole batch is refused; nothing is written |
| An allowlist entry that is not a string | Refused when the redactor is built |
| Text that is `None` | Stays `None`. Absent and empty are different facts, and redaction is not the place to conflate them |
| Text already containing tokens | A no-op. Re-running ingestion over a redacted window does not renumber it |

## Known limits, stated rather than papered over

- **The name heuristic over-redacts.** "Dr Calvin Called back" becomes
  `[NAME_1] back`, because without a dictionary "Calvin Called" and "Susan
  Calvin" are the same shape. It errs toward losing a word of context rather
  than a surname.
- **A name with no honorific is not detected at all.** "Susan Calvin says the
  lamp flickers" keeps the name. This is the deliberate limit of the heuristic:
  without the honorific, "Lumen Desk" and "Susan Calvin" are indistinguishable,
  and blanking every Title Case pair would destroy every product name in the
  dataset.
- **`PHONE` needs three groups, a country code, or a parenthesised area code.**
  Two groups of digits is an invoice number far more often than it is a number
  anybody dials — `9911-2233` in the sample CSV is one — so a bare two-group
  run is left alone. A real seven-digit local number written without any of the
  three markers would survive.
- **`PHONE` is not in the write guard.** It has the widest net of the three
  heuristics, and a guard built on it would refuse an honest ingest because a
  product code looked dialable. It is still redacted; it is just not what the
  refusal is built on.
- **Non-English addresses beyond a handful of street words are missed.** The
  patterns cover English, plus `Rue`, `Via`, `Calle`, `Avenida`, `Piazza`,
  `Plaza`, `Strasse` and `Straat` in the leading position.
