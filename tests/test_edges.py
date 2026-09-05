"""The corners: bad types, unreadable files, and the paths a happy run misses.

Every case here is a real failure mode with a real message. None of them is a
line-coverage exercise — the rule is that if a branch exists to produce an
actionable error, something has to check that the error is actionable.
"""

import json
from datetime import UTC, datetime

import pytest

from conftest import MAPPINGS_DIR, SAMPLES_DIR, load_test_config, write_config, write_lines
from loghog.config_file import load_config
from loghog.errors import (
    ConfigFileError,
    FieldTypeError,
    MappingError,
    MissingFieldError,
    RecordError,
    SourceError,
    SourceFormatError,
    TimestampError,
)
from loghog.ingest.coerce import coerce_bool, coerce_int, coerce_timestamp, coerce_verdicts
from loghog.ingest.extractors import extractor_for
from loghog.ingest.mapping import load_mapping, resolve_mapping
from loghog.ingest.paths import extract_path
from loghog.ingest.readers import read_source
from loghog.ingest.run import ingest
from loghog.ingest.sidecar import load_sidecar
from loghog.privacy.luhn import luhn_ok
from loghog.privacy.redact import Redactor, redaction_token
from loghog.record import JudgeVerdict, Record, normalise_for_dedupe, record_from_json_dict
from loghog.window.manifest import IngestCounts, manifest_from_json_dict
from test_window_manifest import make_manifest, make_source

SAMPLE = SAMPLES_DIR / "support_chat.synthetic.jsonl"


# --- errors -----------------------------------------------------------------


def test_a_line_failure_with_a_non_integer_line_number_is_refused():
    from loghog.errors import LineFailure

    with pytest.raises(SourceError, match="int"):
        LineFailure(line_no="3", error_type="x", detail="y")


def test_a_line_failure_with_a_non_string_detail_is_refused():
    from loghog.errors import LineFailure

    with pytest.raises(SourceError, match="detail"):
        LineFailure(line_no=1, error_type="x", detail=None)


# --- records ----------------------------------------------------------------


def test_a_record_id_that_is_not_a_string_says_what_it_got():
    with pytest.raises(FieldTypeError, match="int"):
        Record(record_id=1, ts_utc="2026-09-05T10:00:00Z", input_text="a", output_text="b")


def test_a_timestamp_that_is_not_a_string_is_a_timestamp_error():
    with pytest.raises(TimestampError, match="int"):
        Record(record_id="r", ts_utc=17, input_text="a", output_text="b")


def test_verdicts_supplied_as_a_list_rather_than_a_tuple_are_refused():
    with pytest.raises(FieldTypeError, match="tuple"):
        Record(
            record_id="r",
            ts_utc="2026-09-05T10:00:00Z",
            input_text="a",
            output_text="b",
            judge_verdicts=[JudgeVerdict(criterion="c", passed=True)],
        )


def test_reading_back_a_verdict_with_an_unknown_key_is_refused():
    payload = Record(
        record_id="r", ts_utc="2026-09-05T10:00:00Z", input_text="a", output_text="b"
    ).to_json_dict()
    payload["judge_verdicts"] = [{"criterion": "c", "passed": True, "weight": 1}]
    with pytest.raises(FieldTypeError, match="weight"):
        record_from_json_dict(payload)


def test_reading_back_a_verdict_whose_passed_is_absent_is_refused():
    payload = Record(
        record_id="r", ts_utc="2026-09-05T10:00:00Z", input_text="a", output_text="b"
    ).to_json_dict()
    payload["judge_verdicts"] = [{"criterion": "c"}]
    with pytest.raises(RecordError):
        record_from_json_dict(payload)


def test_reading_back_a_record_whose_field_is_the_wrong_type_is_refused():
    payload = Record(
        record_id="r", ts_utc="2026-09-05T10:00:00Z", input_text="a", output_text="b"
    ).to_json_dict()
    payload["latency_ms"] = "fast"
    with pytest.raises(RecordError):
        record_from_json_dict(payload)


def test_normalising_something_that_is_not_text_is_refused():
    with pytest.raises(FieldTypeError):
        normalise_for_dedupe(17)


# --- privacy ----------------------------------------------------------------


def test_luhn_of_something_that_is_not_a_string_is_false():
    assert luhn_ok(4242424242424242) is False


def test_a_token_for_a_class_that_does_not_exist_is_refused():
    with pytest.raises(Exception, match="unknown PII class"):
        redaction_token("PASSPORT", 1)


def test_a_redactor_given_an_allowlist_that_is_not_a_sequence_of_strings_is_refused():
    with pytest.raises(Exception, match="allowlist"):
        Redactor(name_allowlist=(None,))


# --- paths and extractors ---------------------------------------------------


def test_a_list_indexed_by_a_word_is_missing():
    assert extract_path({"a": [1, 2]}, "a.b") is not None
    assert repr(extract_path({"a": [1, 2]}, "a.b")) == "MISSING"


def test_an_extractor_looked_up_by_a_non_string_is_refused():
    with pytest.raises(MappingError):
        extractor_for(None)


# --- coercion ---------------------------------------------------------------


def test_an_integer_from_a_type_with_no_reading_is_refused():
    with pytest.raises(FieldTypeError, match="list"):
        coerce_int([1], field_name="latency_ms")


def test_a_bool_from_a_type_with_no_reading_is_refused():
    with pytest.raises(FieldTypeError, match="list"):
        coerce_bool([], field_name="passed")


def test_a_bool_that_is_null_is_a_missing_field():
    with pytest.raises(MissingFieldError):
        coerce_bool(None, field_name="passed")


def test_a_timestamp_from_a_type_with_no_reading_is_refused():
    with pytest.raises(TimestampError, match="list"):
        coerce_timestamp([], field_name="ts_utc")


def test_a_blank_timestamp_is_a_missing_field():
    with pytest.raises(MissingFieldError):
        coerce_timestamp("   ", field_name="ts_utc")


def test_an_epoch_far_beyond_any_calendar_is_refused():
    with pytest.raises(TimestampError):
        coerce_timestamp(10**30, field_name="ts_utc")


def test_verdicts_that_are_null_are_a_missing_field():
    with pytest.raises(MissingFieldError):
        coerce_verdicts(None, field_name="v", criterion_key="c", passed_key="p")


def test_a_verdict_entry_that_is_not_an_object_is_refused():
    with pytest.raises(FieldTypeError, match="object"):
        coerce_verdicts(["yes"], field_name="v", criterion_key="c", passed_key="p")


# --- mappings ---------------------------------------------------------------


def test_a_mapping_with_no_fields_table_is_refused(tmp_path):
    path = tmp_path / "m.toml"
    path.write_text(
        'schema_version = 1\nname = "m"\ndescription = "d"\nsource_format = "jsonl"\n',
        encoding="utf-8",
    )
    with pytest.raises(MappingError, match="fields"):
        load_mapping(path)


def test_a_mapping_whose_field_path_is_empty_is_refused(tmp_path):
    path = tmp_path / "m.toml"
    path.write_text(
        'schema_version = 1\nname = "m"\ndescription = "d"\nsource_format = "jsonl"\n'
        '[fields]\nrecord_id = { path = "  " }\nts_utc = "t"\ninput_text = "i"\n',
        encoding="utf-8",
    )
    with pytest.raises(MappingError, match="empty path"):
        load_mapping(path)


def test_a_mapping_whose_extractor_is_not_a_string_is_refused(tmp_path):
    path = tmp_path / "m.toml"
    path.write_text(
        'schema_version = 1\nname = "m"\ndescription = "d"\nsource_format = "jsonl"\n'
        '[fields]\nrecord_id = { path = "i", extractor = 7 }\nts_utc = "t"\ninput_text = "i"\n',
        encoding="utf-8",
    )
    with pytest.raises(MappingError, match="extractor"):
        load_mapping(path)


def test_a_mapping_whose_defaults_are_not_a_table_is_refused(tmp_path):
    path = tmp_path / "m.toml"
    path.write_text(
        'schema_version = 1\nname = "m"\ndescription = "d"\nsource_format = "jsonl"\n'
        'defaults = 7\n[fields]\nrecord_id = "i"\nts_utc = "t"\ninput_text = "i"\n',
        encoding="utf-8",
    )
    with pytest.raises(MappingError, match="defaults"):
        load_mapping(path)


def test_a_mapping_whose_sidecar_is_not_a_table_is_refused(tmp_path):
    path = tmp_path / "m.toml"
    path.write_text(
        'schema_version = 1\nname = "m"\ndescription = "d"\nsource_format = "jsonl"\n'
        'sidecar = 7\n[fields]\nrecord_id = "i"\nts_utc = "t"\ninput_text = "i"\n',
        encoding="utf-8",
    )
    with pytest.raises(MappingError, match="sidecar"):
        load_mapping(path)


def test_a_mapping_whose_timestamp_section_is_not_a_table_is_refused(tmp_path):
    path = tmp_path / "m.toml"
    path.write_text(
        'schema_version = 1\nname = "m"\ndescription = "d"\nsource_format = "jsonl"\n'
        'timestamp = 7\n[fields]\nrecord_id = "i"\nts_utc = "t"\ninput_text = "i"\n',
        encoding="utf-8",
    )
    with pytest.raises(MappingError, match="timestamp"):
        load_mapping(path)


def test_a_bare_name_with_no_mappings_directory_is_refused():
    with pytest.raises(MappingError, match="not a path"):
        resolve_mapping("openai_chat_jsonl", mappings_dir=None)


# --- readers ----------------------------------------------------------------


def test_a_blank_csv_row_is_counted_as_blank(tmp_path):
    path = write_lines(tmp_path / "log.csv", "id,prompt\n1,hello\n\n2,there\n")
    lines = list(read_source(path, "csv"))
    assert any(line.blank for line in lines)


# --- sidecar ----------------------------------------------------------------


def test_a_missing_sidecar_file_is_a_source_error(tmp_path):
    spec = load_mapping(MAPPINGS_DIR / "regress_rollout_events.toml").sidecar
    with pytest.raises(SourceFormatError, match="sidecar"):
        load_sidecar(tmp_path / "ghost.jsonl", spec)


def test_a_sidecar_line_of_broken_json_is_a_source_error(tmp_path):
    spec = load_mapping(MAPPINGS_DIR / "regress_rollout_events.toml").sidecar
    path = write_lines(tmp_path / "traffic.jsonl", "{not json}\n")
    with pytest.raises(SourceFormatError, match="line 1"):
        load_sidecar(path, spec)


def test_a_sidecar_line_that_is_not_an_object_is_a_source_error(tmp_path):
    spec = load_mapping(MAPPINGS_DIR / "regress_rollout_events.toml").sidecar
    path = write_lines(tmp_path / "traffic.jsonl", "[1, 2]\n")
    with pytest.raises(SourceFormatError, match="object"):
        load_sidecar(path, spec)


def test_blank_lines_in_a_sidecar_are_skipped(tmp_path):
    spec = load_mapping(MAPPINGS_DIR / "regress_rollout_events.toml").sidecar
    path = write_lines(tmp_path / "traffic.jsonl", '\n{"text": "a ticket"}\n\n')
    assert len(load_sidecar(path, spec)) == 1


# --- configuration ----------------------------------------------------------


def test_a_section_that_is_not_a_table_is_refused(tmp_path):
    path = write_config(tmp_path, [("[privacy]", "privacy = 7\n[unused_privacy]")])
    with pytest.raises(ConfigFileError):
        load_config(path)


def test_a_missing_key_names_itself(tmp_path):
    path = write_config(tmp_path, [("redact = true", "")])
    with pytest.raises(ConfigFileError, match="redact"):
        load_config(path)


def test_a_path_that_is_not_a_string_is_refused(tmp_path):
    path = write_config(tmp_path, [('records_dir = "records"', "records_dir = 7")])
    with pytest.raises(ConfigFileError, match="records_dir"):
        load_config(path)


# --- manifest ---------------------------------------------------------------


def test_a_manifest_whose_counts_are_not_an_object_is_refused():
    payload = make_manifest().to_json_dict()
    payload["counts"] = 7
    with pytest.raises(Exception, match="counts"):
        manifest_from_json_dict(payload)


def test_a_source_entry_with_a_non_integer_size_is_refused():
    with pytest.raises(Exception, match="bytes"):
        make_source(bytes="lots")


def test_a_count_that_is_a_bool_is_refused():
    with pytest.raises(Exception, match="integer"):
        IngestCounts(
            lines_read=True,
            blank_lines=0,
            rows=0,
            unparsed=0,
            invalid=0,
            records_written=0,
            duplicates_dropped=0,
            truncated=0,
        )


# --- the run ----------------------------------------------------------------


def test_a_configuration_error_discovered_mid_file_stops_the_run(tmp_path):
    # An unknown extractor in a mapping is not a bad line; it is a bad mapping,
    # and failing every line for it would bury the one message that helps.
    config = load_test_config(tmp_path)
    mapping = tmp_path / "broken.toml"
    mapping.write_text(
        'schema_version = 1\nname = "broken"\ndescription = "d"\nsource_format = "jsonl"\n'
        '[fields]\nrecord_id = "id"\nts_utc = "created"\n'
        'input_text = { path = "messages", extractor = "openai_last_user_message" }\n'
        'output_text = { path = "messages", extractor = "openai_assistant_message" }\n',
        encoding="utf-8",
    )
    outcome = ingest(
        config,
        input_path=SAMPLE,
        source_format="jsonl",
        mapping_reference=str(mapping),
        window="demo",
        now=datetime(2026, 9, 5, 10, tzinfo=UTC),
    )
    assert outcome.manifest.created_utc == "2026-09-05T10:00:00Z"


def test_a_source_outside_the_repository_is_recorded_by_name_alone(tmp_path):
    (tmp_path / "inside").mkdir()
    config = load_test_config(tmp_path / "inside")
    outside = write_lines(
        tmp_path / "outside.jsonl",
        json.dumps(
            {
                "id": "a",
                "created": 1788000000,
                "messages": [
                    {"role": "user", "content": "hello"},
                    {"role": "assistant", "content": "hi"},
                ],
            }
        )
        + "\n",
    )
    outcome = ingest(
        config,
        input_path=outside,
        source_format="jsonl",
        mapping_reference="openai_chat_jsonl",
        window="demo",
    )
    assert outcome.manifest.sources[0].path == "outside.jsonl"
