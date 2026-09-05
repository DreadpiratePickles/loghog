"""One source row becomes one canonical record, or one typed failure.

Nothing here guesses. A field the mapping asked for and the row does not have is
a named error on a numbered line; it is never a default, an empty string, or a
zero. That is what makes the per-line error report worth reading — every entry
in it names a field and a reason, and a thousand entries naming the same field
is a mapping to fix rather than a log to apologise for.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from loghog.errors import MappingError, MissingFieldError
from loghog.ingest.coerce import (
    coerce_int,
    coerce_text,
    coerce_timestamp,
    coerce_verdicts,
    truncate,
)
from loghog.ingest.extractors import extractor_for
from loghog.ingest.mapping import FieldMapping, FieldSpec
from loghog.ingest.paths import MISSING, extract_path
from loghog.record import Record

_IDENTIFIER_FIELDS = frozenset({"record_id"})
_TEXT_FIELDS = ("input_text", "output_text")
_COUNT_FIELDS = ("latency_ms", "input_tokens", "output_tokens", "cost_micro_usd")
_PLAIN_TEXT_FIELDS = ("prompt_version", "arm", "error", "feedback")


@dataclass(frozen=True)
class BuiltRecord:
    """A record, plus what had to be done to the row to get it."""

    record: Record
    truncated_fields: tuple[str, ...] = ()


def build_record(
    payload: Mapping[str, Any],
    mapping: FieldMapping,
    *,
    max_text_chars: int,
    sidecar: dict[str, str] | None = None,
) -> BuiltRecord:
    """Turn one source row into a canonical record.

    Raises:
        MappingError: the mapping and the run disagree — a sidecar is declared
            and none was supplied. A configuration problem, not a data one.
        RecordError: this row is not a usable record. The caller counts it and
            carries on.
    """
    values: dict[str, Any] = {}
    if mapping.sidecar is not None:
        if sidecar is None:
            raise MappingError(
                f"mapping {mapping.name!r} declares a [sidecar]: its log stores "
                f"{mapping.sidecar.target} only as a hash. Pass --sidecar <file>."
            )
        values[mapping.sidecar.target] = _from_sidecar(payload, mapping, sidecar)

    for target, spec in mapping.fields.items():
        if target in values:
            continue
        raw = _raw_value(payload, spec)
        if _absent(raw):
            fallback = mapping.defaults.get(target, MISSING)
            if fallback is MISSING:
                if spec.required:
                    raise MissingFieldError(
                        f"{target} is absent: the mapping reads it from {spec.path!r}"
                    )
                continue
            raw = fallback
        values[target] = _coerce(target, raw, spec, mapping=mapping)

    for target, fallback in mapping.defaults.items():
        if target not in values:
            values[target] = _coerce(
                target, fallback, mapping.fields.get(target), mapping=mapping
            )

    for required in ("record_id", "ts_utc", "input_text"):
        if required not in values:
            raise MissingFieldError(f"{required} is absent and the mapping supplies no default")

    truncated = []
    for target in _TEXT_FIELDS:
        text = values.get(target)
        if isinstance(text, str):
            values[target], was_cut = truncate(text, max_text_chars)
            if was_cut:
                truncated.append(target)
    return BuiltRecord(record=Record(**values), truncated_fields=tuple(truncated))


def _from_sidecar(payload: Mapping[str, Any], mapping: FieldMapping, index: dict[str, str]) -> str:
    spec = mapping.sidecar
    key = payload.get(spec.key_field)
    if not isinstance(key, str) or not key.strip():
        raise MissingFieldError(
            f"the row has no {spec.key_field!r}, which is the key the sidecar is joined on"
        )
    text = index.get(key)
    if text is None:
        raise MissingFieldError(
            f"no sidecar entry for {spec.key_field}={key[:12]}…. The row is skipped rather "
            "than guessed at: an eval case built on the wrong input is worse than no case."
        )
    return text


def _absent(raw: Any) -> bool:
    """Whether a raw value counts as "the row did not say".

    A blank string is absent. That matters most for CSV, where every cell that
    was left empty arrives as `""` rather than as null, and where reading an
    empty `rating` column as a feedback value of "" would fail the whole row
    over a field nobody filled in.
    """
    if raw is MISSING or raw is None:
        return True
    return isinstance(raw, str) and not raw.strip()


def _raw_value(payload: Mapping[str, Any], spec: FieldSpec) -> Any:
    if spec.path is None:
        return MISSING
    return extractor_for(spec.extractor)(extract_path(payload, spec.path))


def _coerce(target: str, raw: Any, spec: FieldSpec | None, *, mapping: FieldMapping) -> Any:
    if target == "ts_utc":
        return coerce_timestamp(raw, field_name=target, naive_is_utc=mapping.naive_is_utc)
    if target in _COUNT_FIELDS:
        return coerce_int(raw, field_name=target)
    if target == "judge_verdicts":
        return coerce_verdicts(
            raw,
            field_name=target,
            criterion_key=spec.criterion_key if spec else "criterion",
            passed_key=spec.passed_key if spec else "passed",
        )
    if target in _TEXT_FIELDS or target in _PLAIN_TEXT_FIELDS:
        return coerce_text(raw, field_name=target)
    return coerce_text(raw, field_name=target, allow_number=target in _IDENTIFIER_FIELDS)
