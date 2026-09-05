"""Named extractors, from a fixed registry.

A mapping file names an extractor; it never supplies code. The registry is a
dict of eight-line functions and nothing in this package will `eval` a string
out of a configuration file — a mapping is a file somebody edits in a hurry,
and the blast radius of a typo in one should be a typed error rather than
arbitrary execution.
"""

import pytest

from loghog.errors import MappingError
from loghog.ingest.extractors import EXTRACTOR_NAMES, extractor_for
from loghog.ingest.paths import MISSING

MESSAGES = [
    {"role": "system", "content": "You are a support assistant."},
    {"role": "user", "content": "my lamp flickers"},
    {"role": "assistant", "content": "Sorry to hear that."},
]


def run(name, value):
    return extractor_for(name)(value)


def test_the_registry_is_the_documented_set():
    assert set(EXTRACTOR_NAMES) == {
        "identity",
        "openai_last_user_message",
        "openai_assistant_message",
        "join_text",
    }


def test_an_unknown_extractor_is_a_mapping_error_listing_the_known_ones():
    with pytest.raises(MappingError, match="identity"):
        extractor_for("exec_this")


def test_identity_returns_what_it_was_given():
    assert run("identity", "text") == "text"


def test_the_last_user_message_is_the_input():
    assert run("openai_last_user_message", MESSAGES) == "my lamp flickers"


def test_the_last_user_message_is_the_last_one_not_the_first():
    messages = MESSAGES + [{"role": "user", "content": "and now it is worse"}]
    assert run("openai_last_user_message", messages) == "and now it is worse"


def test_the_assistant_message_is_the_output():
    assert run("openai_assistant_message", MESSAGES) == "Sorry to hear that."


def test_content_supplied_as_typed_parts_is_joined():
    # The multimodal shape: content is a list of parts rather than a string.
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "here is the error"},
                {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}},
                {"type": "text", "text": "on the second screen"},
            ],
        }
    ]
    assert run("openai_last_user_message", messages) == "here is the error\non the second screen"


def test_a_conversation_with_no_user_turn_is_missing():
    assert run("openai_last_user_message", [{"role": "system", "content": "x"}]) is MISSING


def test_a_conversation_with_no_assistant_turn_is_missing():
    # A logged request that never got a reply. Absent, not empty — the record
    # layer then insists on an error instead.
    assert run("openai_assistant_message", MESSAGES[:2]) is MISSING


def test_something_that_is_not_a_list_of_messages_is_missing():
    assert run("openai_last_user_message", "not messages") is MISSING


def test_a_message_that_is_not_an_object_is_skipped_not_fatal():
    assert run("openai_last_user_message", ["nope", MESSAGES[1]]) == "my lamp flickers"


def test_missing_stays_missing_through_every_extractor():
    for name in EXTRACTOR_NAMES:
        assert extractor_for(name)(MISSING) is MISSING


def test_join_text_joins_a_list_of_strings():
    assert run("join_text", ["one", "two"]) == "one\ntwo"


def test_join_text_leaves_a_plain_string_alone():
    assert run("join_text", "one") == "one"


def test_join_text_skips_entries_that_are_not_strings():
    assert run("join_text", ["one", 2, "three"]) == "one\nthree"


def test_join_text_of_an_empty_list_is_missing():
    assert run("join_text", []) is MISSING
