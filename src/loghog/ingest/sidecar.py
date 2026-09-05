"""Rejoining text a log stored only as a hash.

Some logs are careful. `regress-rollout` records `input_sha256` and not the
ticket, because its monitor never needs the input text and a log that stores
less leaks less. That is the right call for a monitor and exactly the wrong
shape for an eval dataset, where the input text *is* the case.

So the two halves are rejoined here, explicitly, from a file the operator names
on the command line — rather than by ingestion quietly deciding that a missing
input is fine.
"""

import hashlib
import json
from pathlib import Path

from loghog.errors import MissingFieldError, SourceFormatError
from loghog.ingest.mapping import SidecarSpec


def load_sidecar(path: Path, spec: SidecarSpec) -> dict[str, str]:
    """Index a sidecar file by the SHA-256 of its text field.

    Raises:
        SourceFormatError: the file is missing or a line is not a JSON object.
        MissingFieldError: a line has no text field. Skipping it silently would
            make a later "no sidecar match" impossible to explain.
    """
    path = Path(path)
    if not path.is_file():
        raise SourceFormatError(f"no sidecar file at {path}")
    index: dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line_no, raw in enumerate(handle, start=1):
            text = raw.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise SourceFormatError(
                    f"{path} line {line_no} is not valid JSON ({exc.msg})"
                ) from exc
            if not isinstance(payload, dict):
                raise SourceFormatError(f"{path} line {line_no} is not a JSON object")
            value = payload.get(spec.text_field)
            if not isinstance(value, str) or not value.strip():
                raise MissingFieldError(
                    f"{path} line {line_no} has no {spec.text_field!r}. A sidecar entry "
                    "without text cannot restore anything, and dropping it quietly would "
                    "turn into an unexplainable miss later."
                )
            index[hashlib.sha256(value.encode("utf-8")).hexdigest()] = value
    return index
