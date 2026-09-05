"""`[expect] output_json`: the one mapping flag a later stage reads.

A mapping is the only place that knows what a producer's output is supposed to
look like, so "this feature returns JSON" is a fact about the mapping. But the
stage that checks it runs days later against a window, not against a file — so
the flag has to travel, and it travels in the manifest, per source.

That is why the manifest schema version went to 2. A window written before this
flag existed cannot say whether its outputs were meant to parse, and guessing
"no" would silently make the signal permanently quiet on exactly the windows
somebody most wanted it for.
"""

import json

import pytest

from conftest import MAPPINGS_DIR, load_test_config, write_jsonl
from loghog.errors import MappingError, ScoreError
from loghog.ingest.mapping import load_mapping
from loghog.ingest.run import ingest
from loghog.score.run import score_window
from loghog.window.manifest import MANIFEST_SCHEMA_VERSION
from loghog.window.store import WindowStore

MAPPING = """
schema_version = 1
name = "json_out"
description = "A feature whose output is a JSON object."
source_format = "jsonl"

[expect]
output_json = true

[fields]
record_id = { path = "id" }
ts_utc = { path = "ts" }
input_text = { path = "question" }
output_text = { path = "answer" }
"""


def write_mapping(tmp_path, text=MAPPING):
    path = tmp_path / "json_out.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_the_flag_defaults_to_false_when_no_mapping_declares_it():
    mapping = load_mapping(MAPPINGS_DIR / "openai_chat_jsonl.toml")
    assert mapping.expect_output_json is False


def test_a_mapping_can_declare_that_its_output_is_json(tmp_path):
    assert load_mapping(write_mapping(tmp_path)).expect_output_json is True


def test_a_non_boolean_flag_is_refused(tmp_path):
    path = write_mapping(tmp_path, MAPPING.replace("output_json = true", 'output_json = "yes"'))
    with pytest.raises(MappingError, match="output_json"):
        load_mapping(path)


def test_an_unknown_key_in_the_expect_table_is_refused(tmp_path):
    path = write_mapping(tmp_path, MAPPING.replace("[expect]", "[expect]\noutput_xml = true"))
    with pytest.raises(MappingError, match="output_xml"):
        load_mapping(path)


def test_the_manifest_is_at_schema_version_two_and_carries_the_flag(tmp_path):
    config, outcome = _ingest_json_window(tmp_path)
    payload = json.loads((outcome.directory / "manifest.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == MANIFEST_SCHEMA_VERSION == 2
    assert payload["sources"][0]["expect_output_json"] is True


def test_the_flag_reaches_the_scorer_through_the_manifest(tmp_path):
    config, _ = _ingest_json_window(tmp_path)
    outcome = score_window(config, window="jsonwin")
    assert outcome.context.expect_output_json is True
    by_id = {entry.record_id: entry for entry in outcome.scores}
    assert "format_violation" in {s.name for s in by_id["r-2"].signals}
    assert "format_violation" not in {s.name for s in by_id["r-1"].signals}


def test_two_sources_disagreeing_about_json_block_the_signal(tmp_path):
    config, _ = _ingest_json_window(tmp_path)
    plain = tmp_path / "plain.jsonl"
    write_jsonl(
        plain,
        [{"id": "r-3", "ts": "2026-09-05T10:00:00Z", "question": "why", "answer": "because"}],
    )
    mapping = write_mapping(tmp_path, MAPPING.replace("output_json = true", "output_json = false"))
    ingest(
        config,
        input_path=plain,
        source_format="jsonl",
        mapping_reference=str(mapping),
        window="jsonwin",
        append=True,
    )
    outcome = score_window(config, window="jsonwin")
    blocked = {entry.signal: entry for entry in outcome.context.not_evaluated if entry.blocking}
    assert "format_violation" in blocked
    assert "disagree" in blocked["format_violation"].reason


def test_a_manifest_from_the_previous_schema_version_is_refused(tmp_path):
    config, outcome = _ingest_json_window(tmp_path)
    path = outcome.directory / "manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["schema_version"] = 1
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ScoreError, match="schema_version"):
        score_window(config, window="jsonwin")


def _ingest_json_window(tmp_path):
    config = load_test_config(tmp_path)
    source = tmp_path / "json_out.jsonl"
    write_jsonl(
        source,
        [
            {
                "id": "r-1",
                "ts": "2026-09-05T10:00:00Z",
                "question": "Summarise the complaint about the flickering desk lamp.",
                "answer": '{"summary": "a lamp that flickers"}',
            },
            {
                "id": "r-2",
                "ts": "2026-09-05T10:05:00Z",
                "question": "Summarise the complaint about the missed delivery attempt.",
                "answer": "Sure! The courier did not ring the bell.",
            },
        ],
    )
    outcome = ingest(
        config,
        input_path=source,
        source_format="jsonl",
        mapping_reference=str(write_mapping(tmp_path)),
        window="jsonwin",
    )
    return config, outcome


def test_the_window_store_reads_its_records_back_as_records(tmp_path):
    config, outcome = _ingest_json_window(tmp_path)
    records = WindowStore(outcome.directory).read_records()
    assert [record.record_id for record in records] == ["r-1", "r-2"]
