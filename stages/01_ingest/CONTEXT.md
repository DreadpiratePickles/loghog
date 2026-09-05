# Stage: 01_ingest — BUILT (Phase A)

Read one log file, under one field mapping, into canonical records — and account
for every single line that does not make it.

## Objective

Turn a producer-specific log line into the canonical record every later stage
reads, or into a numbered, typed, quotable-nowhere failure.

## Inputs

| Path or source | Layer | Authority | Required | Relevant section |
|---|---:|---|---:|---|
| `--input <file>` | 4 | Authoritative | Yes | The whole file, line by line |
| `--mapping <name or path>` | 3 | Authoritative | Yes | `[fields]`, `[defaults]`, `[sidecar]`, `[timestamp]` |
| `--sidecar <file>` | 4 | Authoritative | Only for a mapping that declares one | The text field named in `[sidecar]` |
| `loghog.toml` | 3 | Authoritative | Yes | `[paths]`, `[ingest] max_text_chars`, `[dedupe]` |
| `records/<window>/` | 4 | Authoritative | Only with `--append` | The existing manifest and record fingerprints |

## Process

1. **Resolve the mapping** and refuse it if `--format` contradicts its declared
   `source_format`. One of the two is wrong, and guessing which would read the
   file the wrong way for its whole length.
2. **Refuse early.** A mapping that declares a `[sidecar]` and was given none; a
   window that already exists without `--append`; `[privacy] redact = false`
   without `--allow-unredacted`; a source that is not there. All of them stop
   the run before a line is read.
3. **Hash the source** and check, when appending, that this window has not
   already ingested this file at this hash. Doing it twice would double every
   count for no new records, and finding that out at the end wastes the pass.
4. **Read**, line by line. Each line is a row, a blank, or an unparsed line, and
   the three are counted separately.
5. **Map** each row: follow a dotted path, run a named extractor from a fixed
   registry, coerce to the canonical type. Absent is distinct from null, and a
   blank string counts as absent — which matters most for CSV, where every cell
   somebody left empty arrives as `""`.
6. **Truncate** text over `[ingest] max_text_chars`, with a visible marker, and
   count it.
7. **Redact** — stage 02, in the write path, before deduplication. See
   `stages/02_redact/CONTEXT.md`.
8. **Deduplicate** on the SHA-256 of the normalised, redacted input, seeded from
   the window on disk when appending.
9. **Write** four files, or none.

Steps 1-9 are entirely deterministic. There is no judgement in this stage, and
therefore no model call.

## Outputs

| Path | Schema or format | Consumer |
|---|---|---|
| `records/<window>/records.jsonl` | One canonical record per line, keys sorted, `src/loghog/record.py` | Stages 03-08 |
| `records/<window>/manifest.json` | `src/loghog/window/manifest.py`, schema version 1 | Stage 08, and any human asking where a case came from |
| `records/<window>/errors.jsonl` | One `{line_no, error_type, detail}` per rejected line | A human fixing a mapping or an export |
| `records/<window>/ingest.md` | Markdown, banner-first when synthetic or unredacted | A human |

Written mode 0600 under a 0700 directory, and gitignored. A window is production
text: that is what it is for.

## Verify

- `uv run pytest -q` — the suite, none of which touches the network.
- **The arithmetic.** `lines_read == rows + blank_lines + unparsed` and
  `rows == records_written + duplicates_dropped + invalid`, both checked in
  `Manifest.__post_init__` before anything is written. A window whose counts do
  not close is refused rather than reported.
- **The committed sample**, end to end: thirteen lines, one blank, one that is
  not JSON, one that reads perfectly and is not a record, one duplicate. The
  test suite asserts each of those counts by name.
- **Round trip:** every written record re-reads with `record_from_json_dict`,
  which refuses an unknown key as firmly as a missing one.

## Approval

None required. This stage writes only inside `records/`, calls no model, spends
nothing, and sends nothing anywhere.

The one thing it will refuse without a human is writing unredacted text: that
needs `[privacy] redact = false` in a reviewed file **and** `--allow-unredacted`
typed at the moment of the decision.

## Failure Behavior

| Situation | What happens |
|---|---|
| `--format` contradicts the mapping | Refused before the file is opened. Exit 3 |
| The mapping declares a `[sidecar]` and none was given | Refused by name, before the file is opened. Exit 3 |
| The window exists and `--append` was not given | Refused, naming `--append`. Exit 3 |
| `--append` and the window does not exist | Refused. Exit 3 |
| This exact file is already in this window | Refused, naming when it was ingested. Nothing is read. Exit 3 |
| A line is not valid JSON, or a CSV row is too wide | Counted `unparsed`, listed in `errors.jsonl`, the run continues |
| A row cannot become a record | Counted `invalid`, listed with the field at fault, the run continues |
| A row's sidecar key matches nothing | An `invalid` row naming the key prefix. Never a nearest match |
| An unknown extractor, discovered mid-file | Stops the run: a bad mapping is not sixty thousand bad lines. Exit 3 |
| Some lines were rejected and records were written | Exit **1**. A partial success that returned 0 is the failure this tool exists to prevent |
| No line became a record | Nothing is written at all — not even an empty window with a manifest describing it. The first few failures are printed. Exit 2 |
| A record still carries structural PII at write time | The whole batch is refused, naming the record and the class but never the value. Nothing is written |
