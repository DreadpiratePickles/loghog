"""Reaching into a nested payload, and saying so when the value is not there.

Absent is a first-class answer. A path that resolves to nothing returns the
MISSING sentinel rather than None, because a log line whose `feedback` is
literally `null` and one that has no `feedback` key are different facts and the
mapping layer is where that distinction survives.
"""

import pytest

from loghog.errors import MappingError
from loghog.ingest.paths import MISSING, extract_path

PAYLOAD = {
    "id": "abc",
    "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    "messages": [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "second"},
    ],
    "meta": {"tags": ["a", "b"], "empty": None},
    "0": "a key that looks like an index",
}


def test_a_top_level_key():
    assert extract_path(PAYLOAD, "id") == "abc"


def test_a_nested_key():
    assert extract_path(PAYLOAD, "usage.prompt_tokens") == 100


def test_a_list_index():
    assert extract_path(PAYLOAD, "messages.0.role") == "user"


def test_a_negative_index_counts_from_the_end():
    assert extract_path(PAYLOAD, "messages.-1.content") == "second"


def test_a_missing_key_is_missing_not_none():
    assert extract_path(PAYLOAD, "nope") is MISSING


def test_a_key_whose_value_is_null_comes_back_as_none_not_missing():
    # The distinction the sentinel exists for.
    assert extract_path(PAYLOAD, "meta.empty") is None


def test_an_index_past_the_end_is_missing():
    assert extract_path(PAYLOAD, "messages.7.role") is MISSING


def test_indexing_something_that_is_not_a_list_is_missing():
    assert extract_path(PAYLOAD, "id.0") is MISSING


def test_a_key_on_something_that_is_not_an_object_is_missing():
    assert extract_path(PAYLOAD, "usage.prompt_tokens.nope") is MISSING


def test_a_dictionary_key_wins_over_a_list_index_when_both_could_apply():
    # `{"0": ...}` is a key, and reading it as an index would be a silent
    # mis-read of a payload that is perfectly well formed.
    assert extract_path(PAYLOAD, "0") == "a key that looks like an index"


def test_the_whole_payload_is_reachable_with_a_bare_dot():
    assert extract_path(PAYLOAD, ".") is PAYLOAD


def test_an_empty_path_is_a_mapping_error_not_a_missing_value():
    # An empty path is a mistake in a file a human wrote, not a log line that
    # happens to be short of a field.
    with pytest.raises(MappingError):
        extract_path(PAYLOAD, "")


def test_a_path_with_an_empty_segment_is_refused():
    with pytest.raises(MappingError):
        extract_path(PAYLOAD, "usage..prompt_tokens")


def test_a_path_that_is_not_a_string_is_refused():
    with pytest.raises(MappingError):
        extract_path(PAYLOAD, 7)


def test_reaching_into_a_payload_that_is_not_an_object_is_missing():
    assert extract_path("a string", "id") is MISSING


def test_the_sentinel_is_falsey_and_reprs_readably():
    assert not MISSING
    assert "MISSING" in repr(MISSING)
