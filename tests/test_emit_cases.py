"""Rendering a drafted case as project 1's golden-case YAML.

The contract is not "valid YAML". It is that
`regression_detect.goldens.load_goldens` accepts the file — so the tests load
what this module writes with that exact function rather than with a schema
restated here, which is the only version of the check that cannot drift.
"""

import pytest
import yaml
from regression_detect.goldens import load_goldens

from loghog.emit.cases import (
    LOGHOG_TAG,
    EmitCase,
    case_id_for,
    case_notes,
    render_cases_yaml,
    render_mapping_scalar,
    render_sequence_item,
    slug,
)
from loghog.errors import EmitError

CRITERIA = (
    "States that the parcel was left in a bin.",
    "Names the missed doorbell.",
    "Does not invent an order number.",
)


def case(**overrides) -> EmitCase:
    fields = {
        "case_id": "loghog_w_chat_001",
        "record_id": "chat-001",
        "window": "w",
        "input_text": "The driver left the parcel in the recycling bin without ringing.",
        "output_text": "A parcel was left somewhere.",
        "stratum": "judge_failure",
        "score": 9,
        "signals": ("judge_failure", "negative_feedback"),
        "criteria": CRITERIA,
        "notes": "Catches summaries that drop the doorbell.",
        "model_id": "fake-1",
        "dry_run": True,
    }
    fields.update(overrides)
    return EmitCase(**fields)


# --- ids --------------------------------------------------------------------


def test_the_id_is_snake_case_and_project_one_accepts_it(tmp_path):
    case_id = case_id_for(window="2026-09-04", record_id="chat-001")
    assert case_id == "loghog_2026_09_04_chat_001"
    path = tmp_path / "cases.yaml"
    path.write_text(render_cases_yaml([case(case_id=case_id)], window="w", dry_run=True))
    assert load_goldens(path)[0].id == case_id


def test_slugging_something_with_nothing_in_it_is_refused():
    with pytest.raises(EmitError):
        slug("!!!")


def test_the_id_is_stable_across_runs():
    assert case_id_for(window="w", record_id="r-1") == case_id_for(window="w", record_id="r-1")


# --- the awkward scalars ----------------------------------------------------

AWKWARD = [
    "plain text",
    "text: with a colon and space",
    "  leading and trailing spaces  ",
    "a line\nand another line",
    "trailing newline\n",
    "```\nthree backticks\n```",
    "- looks like a list item",
    "#not a comment",
    "emoji 🐗 and accents éàü",
    '"quoted already"',
    "tab\there",
    "yes",
    "null",
    "1234567812345678",
    "[EMAIL_1] wrote in about [CARD_2]",
]


@pytest.mark.parametrize("text", AWKWARD)
def test_every_awkward_input_survives_the_round_trip(text, tmp_path):
    rendered = render_cases_yaml([case(input_text=text)], window="w", dry_run=True)
    path = tmp_path / "cases.yaml"
    path.write_text(rendered, encoding="utf-8")
    # Exact equality, not a stripped comparison. `load_goldens` does not strip
    # `input`, so anything short of this would let a leading space vanish and
    # the test would still pass.
    assert load_goldens(path)[0].input == text


@pytest.mark.parametrize("text", AWKWARD)
def test_a_criterion_containing_anything_still_parses_back(text):
    line = render_sequence_item(text, 0)
    assert yaml.safe_load(line) == [text]


@pytest.mark.parametrize("text", AWKWARD)
def test_a_mapping_scalar_round_trips(text):
    rendered = "\n".join(render_mapping_scalar("input", text, 0))
    assert yaml.safe_load(rendered) == {"input": text}


# --- the case ---------------------------------------------------------------


def test_the_tags_are_loghog_first_then_the_signals(tmp_path):
    path = tmp_path / "cases.yaml"
    path.write_text(render_cases_yaml([case()], window="w", dry_run=True))
    tags = load_goldens(path)[0].tags
    assert tags[0] == LOGHOG_TAG
    assert tags[1:] == ("judge_failure", "negative_feedback")


def test_the_notes_carry_the_provenance_a_reviewer_needs():
    notes = case_notes(case())
    assert "chat-001" in notes
    assert "judge_failure" in notes
    assert "9" in notes
    assert "NOT REVIEWED" in notes


def test_a_case_with_no_criteria_is_refused_rather_than_invented():
    with pytest.raises(EmitError) as excinfo:
        render_cases_yaml([case(criteria=())], window="w", dry_run=True)
    assert "criteria" in str(excinfo.value)


def test_an_empty_dataset_is_refused_because_project_one_refuses_it(tmp_path):
    with pytest.raises(EmitError):
        render_cases_yaml([], window="w", dry_run=True)


def test_a_dry_run_file_says_synthetic_on_its_first_line():
    text = render_cases_yaml([case()], window="w", dry_run=True)
    assert text.splitlines()[0].startswith("# SYNTHETIC")


def test_a_live_file_does_not_claim_to_be_synthetic():
    text = render_cases_yaml([case(dry_run=False)], window="w", dry_run=False)
    assert "SYNTHETIC" not in text
    assert "DRAFTS" in text


def test_the_header_names_the_promote_command():
    text = render_cases_yaml([case()], window="w", dry_run=True)
    assert "loghog promote" in text
    assert "--reviewed-by" in text


def test_two_renderings_of_one_input_are_byte_identical():
    first = render_cases_yaml([case()], window="w", dry_run=True)
    assert first == render_cases_yaml([case()], window="w", dry_run=True)


def test_a_rendering_that_does_not_parse_back_is_refused(monkeypatch):
    """The verification is a real gate, not a comment."""
    monkeypatch.setattr(
        "loghog.emit.cases.render_mapping_scalar",
        lambda key, value, indent: [f"{' ' * indent}{key}: mangled"],
    )
    with pytest.raises(EmitError) as excinfo:
        render_cases_yaml([case()], window="w", dry_run=True)
    assert "survive" in str(excinfo.value) or "rendering" in str(excinfo.value)
