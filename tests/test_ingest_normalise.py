"""One source row becomes one canonical record, or one typed failure.

Nothing here guesses. A field the mapping asked for and the row does not have is
a named error on a numbered line; it is never a default, an empty string, or a
zero.
"""

import hashlib

import pytest

from conftest import MAPPINGS_DIR, chat_row, write_jsonl
from loghog.errors import MappingError, MissingFieldError, RecordError, TimestampError
from loghog.ingest.mapping import load_mapping
from loghog.ingest.normalise import build_record
from loghog.ingest.sidecar import load_sidecar
from loghog.record import JudgeVerdict

MINIMAL = """
schema_version = 1
name = "minimal"
description = "The smallest mapping that can produce a record."
source_format = "jsonl"

[fields]
record_id = { path = "id" }
ts_utc = { path = "ts" }
input_text = { path = "prompt" }
output_text = { path = "completion" }
latency_ms = { path = "latency_ms" }
error = { path = "error" }
feedback = { path = "feedback" }
arm = { path = "arm" }
judge_verdicts = { path = "verdicts" }
"""

ROW = {
    "id": "r-1",
    "ts": "2026-09-05T10:00:00Z",
    "prompt": "my lamp flickers",
    "completion": "Customer reports a flickering lamp.",
}


def mapping_from(tmp_path, text=MINIMAL):
    path = tmp_path / "m.toml"
    path.write_text(text, encoding="utf-8")
    return load_mapping(path)


def build(tmp_path, row=None, *, text=MINIMAL, **kwargs):
    return build_record(
        dict(ROW if row is None else row),
        mapping_from(tmp_path, text),
        max_text_chars=1000,
        **kwargs,
    )


def test_a_row_becomes_a_record(tmp_path):
    built = build(tmp_path)
    assert built.record.record_id == "r-1"
    assert built.record.input_text == "my lamp flickers"
    assert built.record.ts_utc == "2026-09-05T10:00:00Z"


def test_absent_optional_fields_stay_absent(tmp_path):
    built = build(tmp_path)
    assert built.record.latency_ms is None
    assert built.record.arm is None
    assert built.record.judge_verdicts == ()


def test_a_null_optional_field_is_the_same_as_an_absent_one(tmp_path):
    built = build(tmp_path, {**ROW, "feedback": None})
    assert built.record.feedback is None


def test_a_blank_optional_field_is_the_same_as_an_absent_one(tmp_path):
    # The CSV case: every cell somebody left empty arrives as "" rather than as
    # null, and reading that as a feedback value of "" would fail the whole row
    # over a column nobody filled in.
    built = build(tmp_path, {**ROW, "feedback": "  "})
    assert built.record.feedback is None


def test_a_blank_required_field_is_still_a_missing_field(tmp_path):
    with pytest.raises(MissingFieldError, match="input_text"):
        build(tmp_path, {**ROW, "prompt": "   "})


def test_an_optional_field_that_is_present_is_carried(tmp_path):
    built = build(tmp_path, {**ROW, "latency_ms": 412, "arm": "candidate"})
    assert built.record.latency_ms == 412
    assert built.record.arm == "candidate"


def test_a_missing_required_field_names_the_field(tmp_path):
    row = dict(ROW)
    del row["prompt"]
    with pytest.raises(MissingFieldError, match="input_text"):
        build(tmp_path, row)


def test_a_missing_required_field_names_the_path_it_looked_at(tmp_path):
    row = dict(ROW)
    del row["ts"]
    with pytest.raises(MissingFieldError, match="ts"):
        build(tmp_path, row)


def test_a_bad_timestamp_is_a_timestamp_error(tmp_path):
    with pytest.raises(TimestampError):
        build(tmp_path, {**ROW, "ts": "the other day"})


def test_a_row_with_neither_an_output_nor_an_error_is_refused(tmp_path):
    row = dict(ROW)
    del row["completion"]
    with pytest.raises(RecordError, match="neither"):
        build(tmp_path, row)


def test_a_failed_call_becomes_a_failed_record(tmp_path):
    row = dict(ROW)
    del row["completion"]
    row["error"] = "ProviderTransientError"
    built = build(tmp_path, row)
    assert built.record.failed is True
    assert built.record.error == "ProviderTransientError"


def test_an_output_and_an_error_together_are_refused(tmp_path):
    with pytest.raises(RecordError, match="both"):
        build(tmp_path, {**ROW, "error": "Timeout"})


def test_verdicts_are_carried_through(tmp_path):
    built = build(tmp_path, {**ROW, "verdicts": [{"criterion": "is short", "passed": True}]})
    assert built.record.judge_verdicts == (JudgeVerdict(criterion="is short", passed=True),)


# --- defaults ---------------------------------------------------------------


def test_a_default_fills_a_field_the_row_does_not_have(tmp_path):
    text = MINIMAL + '\n[defaults]\narm = "control"\n'
    assert build(tmp_path, text=text).record.arm == "control"


def test_a_value_in_the_row_beats_the_default(tmp_path):
    text = MINIMAL + '\n[defaults]\narm = "control"\n'
    built = build(tmp_path, {**ROW, "arm": "candidate"}, text=text)
    assert built.record.arm == "candidate"


def test_a_default_can_supply_a_field_with_no_path_at_all(tmp_path):
    text = MINIMAL.replace('arm = { path = "arm" }\n', "") + '\n[defaults]\narm = "control"\n'
    assert build(tmp_path, text=text).record.arm == "control"


# --- truncation -------------------------------------------------------------


def test_a_long_input_is_truncated_and_the_record_says_which_field(tmp_path):
    built = build_record(
        {**ROW, "prompt": "x" * 500},
        mapping_from(tmp_path),
        max_text_chars=100,
    )
    assert built.truncated_fields == ("input_text",)
    assert "TRUNCATED" in built.record.input_text


def test_nothing_is_marked_truncated_when_nothing_was(tmp_path):
    assert build(tmp_path).truncated_fields == ()


# --- the sidecar join -------------------------------------------------------


def test_the_input_text_can_be_rejoined_from_a_sidecar(tmp_path):
    text = "my lamp flickers"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    traffic = write_jsonl(tmp_path / "traffic.jsonl", [{"text": text, "request_id": "r-1"}])
    mapping = load_mapping(MAPPINGS_DIR / "regress_rollout_events.toml")
    index = load_sidecar(traffic, mapping.sidecar)
    row = {
        "request_id": "r-1",
        "ts_utc": "2026-09-05T10:00:00Z",
        "input_sha256": digest,
        "output_text": "Customer reports a flickering lamp.",
        "status": "ok",
        "arm": "control",
        "prompt_label": "1.1.0",
        "latency_ms": 412,
        "cost_micro_usd": 136,
    }
    built = build_record(row, mapping, max_text_chars=1000, sidecar=index)
    assert built.record.input_text == text
    assert built.record.prompt_version == "1.1.0"


def test_a_sidecar_miss_is_a_named_failure_not_a_guess(tmp_path):
    traffic = write_jsonl(tmp_path / "traffic.jsonl", [{"text": "something else"}])
    mapping = load_mapping(MAPPINGS_DIR / "regress_rollout_events.toml")
    index = load_sidecar(traffic, mapping.sidecar)
    row = {
        "request_id": "r-1",
        "ts_utc": "2026-09-05T10:00:00Z",
        "input_sha256": "0" * 64,
        "output_text": "a reply",
        "status": "ok",
    }
    with pytest.raises(MissingFieldError, match="sidecar"):
        build_record(row, mapping, max_text_chars=1000, sidecar=index)


def test_a_mapping_that_needs_a_sidecar_and_was_given_none_is_refused(tmp_path):
    mapping = load_mapping(MAPPINGS_DIR / "regress_rollout_events.toml")
    with pytest.raises(MappingError, match="sidecar"):
        build_record({"request_id": "r-1"}, mapping, max_text_chars=1000)


def test_the_sidecar_index_maps_the_hash_of_the_text_to_the_text(tmp_path):
    text = "my lamp flickers"
    traffic = write_jsonl(tmp_path / "traffic.jsonl", [{"text": text}])
    mapping = load_mapping(MAPPINGS_DIR / "regress_rollout_events.toml")
    index = load_sidecar(traffic, mapping.sidecar)
    assert index[hashlib.sha256(text.encode("utf-8")).hexdigest()] == text


def test_a_sidecar_line_without_the_text_field_is_refused(tmp_path):
    traffic = write_jsonl(tmp_path / "traffic.jsonl", [{"nope": "x"}])
    mapping = load_mapping(MAPPINGS_DIR / "regress_rollout_events.toml")
    with pytest.raises(MissingFieldError, match="line 1"):
        load_sidecar(traffic, mapping.sidecar)


# --- the built-in mappings against realistic rows ---------------------------


def test_the_openai_mapping_reads_a_chat_completion_line():
    mapping = load_mapping(MAPPINGS_DIR / "openai_chat_jsonl.toml")
    built = build_record(chat_row(1, user="my lamp flickers"), mapping, max_text_chars=1000)
    assert built.record.input_text == "my lamp flickers"
    assert built.record.output_text == "A reply."
    assert built.record.input_tokens == 101
    assert built.record.output_tokens == 21


def test_the_openai_mapping_rejects_a_line_with_no_assistant_turn():
    mapping = load_mapping(MAPPINGS_DIR / "openai_chat_jsonl.toml")
    row = chat_row(2, user="hello", assistant=None)
    with pytest.raises(RecordError, match="neither"):
        build_record(row, mapping, max_text_chars=1000)


def test_the_prompton_mapping_reads_its_nested_shape():
    mapping = load_mapping(MAPPINGS_DIR / "prompton_events.toml")
    row = {
        "event_id": "ev-1",
        "timestamp": "2026-09-05T10:00:00Z",
        "generation": {
            "input": {"text": "my lamp flickers"},
            "output": {"text": "Customer reports a flickering lamp."},
            "usage": {"input_tokens": 100, "output_tokens": 20},
            "latency_ms": 412,
        },
        "prompt": {"version": "1.1.0"},
        "experiment": {"variant": "candidate"},
    }
    built = build_record(row, mapping, max_text_chars=1000)
    assert built.record.input_text == "my lamp flickers"
    assert built.record.prompt_version == "1.1.0"
    assert built.record.arm == "candidate"
    assert built.record.latency_ms == 412
