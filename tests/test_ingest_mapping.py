"""A mapping file is configuration, and it is validated like configuration.

The three built-in mappings are loaded from the *committed* files rather than
from fixtures, so a test cannot keep passing against a mapping the repository no
longer ships.
"""

import pytest

from conftest import MAPPINGS_DIR
from loghog.errors import MappingError
from loghog.ingest.mapping import (
    BUILTIN_MAPPINGS,
    CANONICAL_FIELDS,
    REQUIRED_FIELDS,
    load_mapping,
    resolve_mapping,
)

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
"""


def write_mapping(tmp_path, text=MINIMAL, name="minimal.toml"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# --- the built-ins ----------------------------------------------------------


def test_the_three_built_in_mappings_are_the_documented_ones():
    assert set(BUILTIN_MAPPINGS) == {
        "regress_rollout_events",
        "prompton_events",
        "openai_chat_jsonl",
    }


@pytest.mark.parametrize("name", sorted(BUILTIN_MAPPINGS))
def test_every_built_in_mapping_is_committed_and_loads(name):
    mapping = load_mapping(MAPPINGS_DIR / f"{name}.toml")
    assert mapping.name == name
    assert mapping.description.strip()


@pytest.mark.parametrize("name", sorted(BUILTIN_MAPPINGS))
def test_every_built_in_mapping_records_its_own_hash(name):
    mapping = load_mapping(MAPPINGS_DIR / f"{name}.toml")
    assert len(mapping.sha256) == 64


def test_a_bare_name_resolves_against_the_mappings_directory():
    mapping = resolve_mapping("openai_chat_jsonl", mappings_dir=MAPPINGS_DIR)
    assert mapping.name == "openai_chat_jsonl"


def test_a_path_resolves_as_a_path():
    mapping = resolve_mapping(str(MAPPINGS_DIR / "openai_chat_jsonl.toml"), mappings_dir=None)
    assert mapping.name == "openai_chat_jsonl"


def test_an_unknown_bare_name_lists_what_is_available():
    with pytest.raises(MappingError, match="openai_chat_jsonl"):
        resolve_mapping("nope", mappings_dir=MAPPINGS_DIR)


def test_the_rollout_mapping_declares_a_sidecar_because_the_log_hashes_its_input():
    # regress-rollout's event log stores `input_sha256` and not the ticket. The
    # text has to be rejoined from the traffic file, and the mapping says so
    # rather than the operator finding out one bad line at a time.
    mapping = load_mapping(MAPPINGS_DIR / "regress_rollout_events.toml")
    assert mapping.sidecar is not None
    assert mapping.sidecar.target == "input_text"


def test_the_openai_mapping_reads_the_last_user_turn():
    mapping = load_mapping(MAPPINGS_DIR / "openai_chat_jsonl.toml")
    assert mapping.fields["input_text"].extractor == "openai_last_user_message"


# --- validation -------------------------------------------------------------


def test_the_canonical_fields_are_the_record_schema():
    assert frozenset(
        {
            "record_id",
            "ts_utc",
            "input_text",
            "output_text",
            "prompt_version",
            "arm",
            "latency_ms",
            "input_tokens",
            "output_tokens",
            "cost_micro_usd",
            "error",
            "feedback",
            "judge_verdicts",
        }
    ) == CANONICAL_FIELDS


def test_the_three_required_fields_are_the_ones_a_record_cannot_do_without():
    assert REQUIRED_FIELDS == ("record_id", "ts_utc", "input_text")


def test_a_missing_file_names_the_path(tmp_path):
    with pytest.raises(MappingError, match="ghost.toml"):
        load_mapping(tmp_path / "ghost.toml")


def test_unparseable_toml_is_a_mapping_error(tmp_path):
    with pytest.raises(MappingError):
        load_mapping(write_mapping(tmp_path, "[fields\n"))


def test_a_mapping_naming_a_field_the_record_does_not_have_is_refused(tmp_path):
    text = MINIMAL + '\nsession_id = { path = "sid" }\n'
    with pytest.raises(MappingError, match="session_id"):
        load_mapping(write_mapping(tmp_path, text))


def test_a_mapping_that_omits_a_required_field_is_refused(tmp_path):
    text = MINIMAL.replace('input_text = { path = "prompt" }\n', "")
    with pytest.raises(MappingError, match="input_text"):
        load_mapping(write_mapping(tmp_path, text))


def test_a_mapping_with_an_unknown_key_in_a_field_spec_is_refused(tmp_path):
    text = MINIMAL.replace('{ path = "id" }', '{ path = "id", pathh = "id" }')
    with pytest.raises(MappingError, match="pathh"):
        load_mapping(write_mapping(tmp_path, text))


def test_a_mapping_with_an_unknown_top_level_key_is_refused(tmp_path):
    with pytest.raises(MappingError, match="wat"):
        load_mapping(write_mapping(tmp_path, MINIMAL + '\n[wat]\nx = 1\n'))


def test_a_mapping_naming_an_unknown_extractor_is_refused(tmp_path):
    text = MINIMAL.replace('{ path = "prompt" }', '{ path = "prompt", extractor = "eval" }')
    with pytest.raises(MappingError, match="eval"):
        load_mapping(write_mapping(tmp_path, text))


def test_a_mapping_for_an_unsupported_source_format_is_refused(tmp_path):
    with pytest.raises(MappingError, match="parquet"):
        load_mapping(write_mapping(tmp_path, MINIMAL.replace('"jsonl"', '"parquet"')))


def test_a_mapping_from_a_future_schema_version_is_refused(tmp_path):
    # A mapping written for a later loader is not a mapping this one can be
    # trusted to read.
    with pytest.raises(MappingError, match="schema_version"):
        load_mapping(
            write_mapping(tmp_path, MINIMAL.replace("schema_version = 1", "schema_version = 2"))
        )


def test_a_field_spec_that_is_neither_a_string_nor_a_table_is_refused(tmp_path):
    with pytest.raises(MappingError):
        load_mapping(write_mapping(tmp_path, MINIMAL.replace('{ path = "id" }', "7")))


def test_a_bare_string_field_spec_is_shorthand_for_a_path(tmp_path):
    mapping = load_mapping(write_mapping(tmp_path, MINIMAL.replace('{ path = "id" }', '"id"')))
    assert mapping.fields["record_id"].path == "id"


def test_a_default_for_a_field_the_record_does_not_have_is_refused(tmp_path):
    text = MINIMAL + '\n[defaults]\nteam = "support"\n'
    with pytest.raises(MappingError, match="team"):
        load_mapping(write_mapping(tmp_path, text))


def test_a_default_supplies_a_field_with_no_path(tmp_path):
    text = MINIMAL + '\n[defaults]\narm = "control"\n'
    mapping = load_mapping(write_mapping(tmp_path, text))
    assert mapping.defaults["arm"] == "control"


def test_a_sidecar_whose_target_is_not_a_text_field_is_refused(tmp_path):
    text = MINIMAL + (
        '\n[sidecar]\nkey_field = "input_sha256"\ntext_field = "text"\ntarget = "latency_ms"\n'
    )
    with pytest.raises(MappingError, match="latency_ms"):
        load_mapping(write_mapping(tmp_path, text))


def test_a_sidecar_missing_a_key_is_refused(tmp_path):
    text = MINIMAL + '\n[sidecar]\nkey_field = "input_sha256"\n'
    with pytest.raises(MappingError, match="text_field"):
        load_mapping(write_mapping(tmp_path, text))


def test_the_timestamp_section_defaults_to_refusing_naive_timestamps(tmp_path):
    assert load_mapping(write_mapping(tmp_path)).naive_is_utc is False


def test_the_timestamp_section_can_declare_that_naive_means_utc(tmp_path):
    text = MINIMAL + "\n[timestamp]\nnaive_is_utc = true\n"
    assert load_mapping(write_mapping(tmp_path, text)).naive_is_utc is True


def test_a_mapping_with_no_name_is_refused(tmp_path):
    with pytest.raises(MappingError, match="name"):
        load_mapping(write_mapping(tmp_path, MINIMAL.replace('name = "minimal"\n', "")))
