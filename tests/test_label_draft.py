"""Drafting criteria: the prompt, and every way a reply is refused.

Model output is untrusted input. That sentence is the whole module, and these
tests are the list of things it refuses to believe — because a criterion that
reaches a goldens file becomes the definition of correct for every later
evaluation, and the cheapest place to stop a bad one is here.
"""

import json

import pytest
from regression_detect.providers.fake import FakeProvider

from loghog.label.draft import (
    DRAFT_PROMPT_SHA256,
    DRAFT_SYSTEM_PROMPT,
    DRY_RUN_MODEL_ID,
    MAX_CRITERIA,
    MIN_CRITERIA,
    SYNTHETIC_MARKER,
    DraftParseError,
    DraftTask,
    build_draft_user_message,
    is_negative,
    parse_draft,
    provider_drafter,
    synthetic_drafter,
)

GOOD = {
    "criteria": [
        "States that the parcel was left in a bin.",
        "Mentions that the driver did not ring the doorbell.",
        "Does not invent an order number the ticket does not contain.",
    ],
    "notes": "Catches summaries that drop the missed doorbell.",
}


def task(**overrides) -> DraftTask:
    fields = {
        "record_id": "r-001",
        "input_text": "The driver left the parcel in the recycling bin without ringing.",
        "output_text": "A parcel was left somewhere.",
        "signals": ("judge_failure", "negative_feedback"),
        "verdicts": (("names the parcel", False),),
    }
    fields.update(overrides)
    return DraftTask(**fields)


# --- the reply --------------------------------------------------------------


def test_a_good_reply_parses():
    draft = parse_draft(json.dumps(GOOD))
    assert len(draft.criteria) == 3
    assert draft.notes.startswith("Catches")


def test_a_single_markdown_fence_is_tolerated():
    fenced = "```json\n" + json.dumps(GOOD) + "\n```"
    assert parse_draft(fenced).criteria == parse_draft(json.dumps(GOOD)).criteria


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "not json at all",
        json.dumps([1, 2, 3]),
        json.dumps({"criteria": GOOD["criteria"]}),
        json.dumps({**GOOD, "extra": 1}),
        json.dumps({**GOOD, "criteria": "a string"}),
        json.dumps({**GOOD, "notes": 7}),
    ],
)
def test_a_reply_that_is_not_the_agreed_shape_is_refused(raw):
    with pytest.raises(DraftParseError):
        parse_draft(raw)


def test_a_non_string_reply_is_refused():
    with pytest.raises(DraftParseError):
        parse_draft(GOOD)


def test_too_few_and_too_many_criteria_are_both_refused():
    negative = "Does not invent anything."
    few = {"criteria": ["States a thing.", negative], "notes": "n"}
    many = {
        "criteria": [f"States thing {index}." for index in range(MAX_CRITERIA)] + [negative],
        "notes": "n",
    }
    assert len(few["criteria"]) < MIN_CRITERIA
    for payload in (few, many):
        with pytest.raises(DraftParseError):
            parse_draft(json.dumps(payload))


def test_a_blank_criterion_is_refused():
    with pytest.raises(DraftParseError):
        parse_draft(json.dumps({**GOOD, "criteria": ["States a thing.", "  ", "Does not lie."]}))


def test_a_draft_with_no_negative_criterion_is_refused():
    """The rule project 1's goldens README is blunt about."""
    cheerful = {
        "criteria": ["States the issue.", "Names the item.", "Is at most 3 sentences."],
        "notes": "n",
    }
    with pytest.raises(DraftParseError) as excinfo:
        parse_draft(json.dumps(cheerful))
    assert "negative" in str(excinfo.value).lower()


def test_a_criterion_that_quotes_a_redaction_token_is_refused():
    """A criterion may not demand that an answer reproduce a placeholder.

    The input reaching the drafter has been through stage 02, so it holds
    `[EMAIL_1]` where an address was. A criterion built around that token would
    be an acceptance test asserting that the system emits loghog's own
    redaction marker, which nothing has ever done.
    """
    payload = {
        "criteria": [
            "States that the account belongs to [EMAIL_1].",
            "Names the plan.",
            "Does not invent a date.",
        ],
        "notes": "n",
    }
    with pytest.raises(DraftParseError) as excinfo:
        parse_draft(json.dumps(payload))
    assert "redact" in str(excinfo.value).lower()


def test_is_negative_ignores_a_leading_tag():
    assert is_negative("Does not invent a date.")
    assert is_negative(f"{SYNTHETIC_MARKER} Does not invent a date.")
    assert not is_negative("States the issue.")


def test_criteria_whitespace_is_collapsed():
    payload = {
        "criteria": ["States   the\n issue.", "Names the item.", "Does not  lie."],
        "notes": "one\n  sentence",
    }
    draft = parse_draft(json.dumps(payload))
    assert draft.criteria[0] == "States the issue."
    assert draft.notes == "one sentence"


# --- the message ------------------------------------------------------------


def test_the_case_travels_in_the_user_message_and_never_in_the_system_prompt():
    message = build_draft_user_message(task())
    assert "recycling bin" in message
    assert "recycling bin" not in DRAFT_SYSTEM_PROMPT
    assert "<input>" in message and "</input>" in message
    assert "<output>" in message and "</output>" in message
    assert "judge_failure" in message


def test_a_failed_record_says_so_rather_than_being_omitted():
    message = build_draft_user_message(task(output_text=None))
    assert "no output" in message.lower()


def test_the_verdicts_travel_with_their_outcome():
    message = build_draft_user_message(task())
    assert "names the parcel" in message
    assert "failed" in message.lower()


def test_the_prompt_is_versioned_by_its_own_bytes():
    import hashlib

    assert hashlib.sha256(DRAFT_SYSTEM_PROMPT.encode()).hexdigest() == DRAFT_PROMPT_SHA256


# --- the drafters -----------------------------------------------------------


def test_the_synthetic_drafter_calls_nothing_and_says_so_in_every_line():
    outcome = synthetic_drafter()(task())
    assert outcome.error_type is None
    assert outcome.model_id == DRY_RUN_MODEL_ID
    assert all(line.startswith(SYNTHETIC_MARKER) for line in outcome.draft.criteria)
    assert outcome.draft.notes.startswith(SYNTHETIC_MARKER)


def test_the_synthetic_placeholders_are_identical_for_every_candidate():
    """A dry run that produced *different* placeholders per case would be one
    somebody could mistake for a reading of the cases."""
    drafter = synthetic_drafter()
    first = drafter(task(record_id="a", input_text="One thing."))
    second = drafter(task(record_id="b", input_text="A completely different thing."))
    assert first.draft.criteria == second.draft.criteria


def test_the_synthetic_placeholders_pass_the_real_validator():
    """Parsed through `parse_draft` like a real reply, so the constant cannot
    drift out of spec without a test noticing."""
    assert any(is_negative(text) for text in synthetic_drafter()(task()).draft.criteria)


def test_a_provider_drafter_makes_exactly_one_call():
    provider = FakeProvider(json.dumps(GOOD), model_id="fake-1")
    outcome = provider_drafter(provider)(task())
    assert len(provider.calls) == 1
    assert outcome.draft.criteria[0].startswith("States")
    assert outcome.model_id == "fake-1"
    assert provider.calls[0]["temperature"] == 0.0


def test_an_unparseable_reply_is_a_recorded_failure_not_an_exception():
    provider = FakeProvider("I would be delighted to help.", model_id="fake-1")
    outcome = provider_drafter(provider)(task())
    assert outcome.draft is None
    assert outcome.error_type == "DraftParseError"


def test_a_provider_failure_is_a_recorded_failure_not_an_exception():
    class Broken:
        model_id = "fake-broken"

        def complete(self, *, system, user, temperature):
            from regression_detect.providers.base import ProviderTransientError

            raise ProviderTransientError("429")

    outcome = provider_drafter(Broken())(task())
    assert outcome.draft is None
    assert outcome.error_type == "ProviderTransientError"


def test_a_draft_outcome_carries_exactly_one_of_a_draft_and_an_error():
    from loghog.label.draft import Draft, DraftError, DraftOutcome

    with pytest.raises(DraftError):
        DraftOutcome(draft=None, error_type=None, model_id="m")
    with pytest.raises(DraftError):
        DraftOutcome(
            draft=Draft(criteria=("a",), notes=""), error_type="X", model_id="m"
        )
