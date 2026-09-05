#!/usr/bin/env python
"""Command line entry point, for running without installing anything.

    uv run python scripts/loghog.py mappings list
    uv run python scripts/loghog.py redact --text "write to sam@example.com"
    uv run python scripts/loghog.py ingest --input samples/support_chat.synthetic.jsonl \
        --format jsonl --mapping openai_chat_jsonl --window demo --synthetic
    uv run python scripts/loghog.py window show --window demo

Every command takes `--config <path>`, defaulting to `./loghog.toml`.

The logic lives in `loghog.cli` so the test suite can import and exercise it
directly. This file only wires the command line to it.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from loghog.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
