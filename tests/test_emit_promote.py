"""`loghog promote`: the one place a drafted case becomes a golden case.

Everything upstream is a proposal. These tests are the list of things this
refuses, because adopting a criterion written by a model, from customer text,
that nobody read, would let the system quietly define what "correct" means for
every later evaluation of the thing it was mined from.
"""

import pytest
from regression_detect.goldens import load_goldens

from loghog.emit.cases import EmitCase, render_cases_yaml
from loghog.emit.promote import REVIEWED_PREFIX, parse_ids, promote
from loghog.errors import PromoteError

TS = "2026-09-05T12:00:00Z"

EXISTING = """\
# Golden cases for the support summariser.
#
# Categories: happy path, edge cases, adversarial. Read this before adding one.

- id: lamp_flickers
  tags: [happy_path]
  input: The lamp flickers above half brightness.
  criteria:
    - Names the lamp
    - Does not invent a model number
  notes: |-
    The oldest case. Half of this file is comments and they must survive.
"""


def case(index: int, **overrides) -> EmitCase:
    fields = {
        "case_id": f"loghog_w_chat_{index:03d}",
        "record_id": f"chat-{index:03d}",
        "window": "w",
        "input_text": f"Complaint {index}: the driver left it in the bin.",
        "output_text": "A summary.",
        "stratum": "judge_failure",
        "score": 9,
        "signals": ("judge_failure",),
        "criteria": (
            "States the problem.",
            "Names the item.",
            "Does not invent an order number.",
        ),
        "notes": "Catches dropped detail.",
        "model_id": "fake-1",
        "dry_run": False,
    }
    fields.update(overrides)
    return EmitCase(**fields)


def files(tmp_path, *, count=3, existing=EXISTING):
    candidates = tmp_path / "candidates-w.yaml"
    candidates.write_text(
        render_cases_yaml([case(index) for index in range(count)], window="w", dry_run=False),
        encoding="utf-8",
    )
    goldens = tmp_path / "goldens.yaml"
    if existing is not None:
        goldens.write_text(existing, encoding="utf-8")
    return candidates, goldens


# --- ids --------------------------------------------------------------------


def test_ids_are_split_in_order_and_a_repeat_is_refused():
    assert parse_ids("b, a ,c") == ("b", "a", "c")
    with pytest.raises(PromoteError):
        parse_ids("a,a")
    with pytest.raises(PromoteError):
        parse_ids("  , ")


# --- the gate ---------------------------------------------------------------


def test_promotion_appends_only_the_named_ids(tmp_path):
    candidates, goldens = files(tmp_path)
    result = promote(
        candidates_path=candidates,
        case_ids=["loghog_w_chat_001"],
        into=goldens,
        reviewed_by="Bobby",
        ts_utc=TS,
    )
    cases = load_goldens(goldens)
    assert [entry.id for entry in cases] == ["lamp_flickers", "loghog_w_chat_001"]
    assert result.total_cases == 2
    assert result.promoted == ("loghog_w_chat_001",)


def test_the_comments_in_the_target_survive(tmp_path):
    """Half a goldens file is comments; a PyYAML round trip deletes all of them."""
    candidates, goldens = files(tmp_path)
    promote(
        candidates_path=candidates,
        case_ids=["loghog_w_chat_000"],
        into=goldens,
        reviewed_by="Bobby",
        ts_utc=TS,
    )
    text = goldens.read_text(encoding="utf-8")
    assert "Categories: happy path, edge cases, adversarial" in text
    assert "The oldest case." in text


def test_the_reviewer_is_recorded_in_the_notes(tmp_path):
    candidates, goldens = files(tmp_path)
    promote(
        candidates_path=candidates,
        case_ids=["loghog_w_chat_000"],
        into=goldens,
        reviewed_by="Bobby Meher",
        ts_utc=TS,
    )
    promoted = {entry.id: entry for entry in load_goldens(goldens)}["loghog_w_chat_000"]
    assert REVIEWED_PREFIX in promoted.notes
    assert "Bobby Meher" in promoted.notes
    assert TS in promoted.notes


def test_promotion_without_a_reviewer_is_refused(tmp_path):
    candidates, goldens = files(tmp_path)
    before = goldens.read_text(encoding="utf-8")
    for name in ("", "   ", None):
        with pytest.raises(PromoteError, match="reviewed-by"):
            promote(
                candidates_path=candidates,
                case_ids=["loghog_w_chat_000"],
                into=goldens,
                reviewed_by=name,
                ts_utc=TS,
            )
    assert goldens.read_text(encoding="utf-8") == before


def test_an_unknown_id_is_refused_and_the_target_is_untouched(tmp_path):
    candidates, goldens = files(tmp_path)
    before = goldens.read_text(encoding="utf-8")
    with pytest.raises(PromoteError) as excinfo:
        promote(
            candidates_path=candidates,
            case_ids=["not_a_case"],
            into=goldens,
            reviewed_by="Bobby",
            ts_utc=TS,
        )
    assert "not_a_case" in str(excinfo.value)
    assert goldens.read_text(encoding="utf-8") == before


def test_an_id_the_target_already_holds_is_refused(tmp_path):
    candidates, goldens = files(tmp_path)
    promote(
        candidates_path=candidates,
        case_ids=["loghog_w_chat_000"],
        into=goldens,
        reviewed_by="Bobby",
        ts_utc=TS,
    )
    before = goldens.read_text(encoding="utf-8")
    with pytest.raises(PromoteError, match="stable"):
        promote(
            candidates_path=candidates,
            case_ids=["loghog_w_chat_000"],
            into=goldens,
            reviewed_by="Bobby",
            ts_utc=TS,
        )
    assert goldens.read_text(encoding="utf-8") == before


def test_no_case_named_is_refused(tmp_path):
    candidates, goldens = files(tmp_path)
    with pytest.raises(PromoteError, match="not a review"):
        promote(
            candidates_path=candidates,
            case_ids=[],
            into=goldens,
            reviewed_by="Bobby",
            ts_utc=TS,
        )


def test_a_candidates_file_project_one_cannot_read_is_refused(tmp_path):
    candidates = tmp_path / "candidates-w.yaml"
    candidates.write_text("not: a list of cases\n", encoding="utf-8")
    goldens = tmp_path / "goldens.yaml"
    goldens.write_text(EXISTING, encoding="utf-8")
    with pytest.raises(PromoteError):
        promote(
            candidates_path=candidates,
            case_ids=["a"],
            into=goldens,
            reviewed_by="Bobby",
            ts_utc=TS,
        )


def test_a_target_that_does_not_exist_yet_is_created_with_a_header(tmp_path):
    candidates, goldens = files(tmp_path, existing=None)
    assert not goldens.exists()
    promote(
        candidates_path=candidates,
        case_ids=["loghog_w_chat_000"],
        into=goldens,
        reviewed_by="Bobby",
        ts_utc=TS,
    )
    text = goldens.read_text(encoding="utf-8")
    assert text.startswith("# Golden cases")
    assert "Bobby" in text
    assert len(load_goldens(goldens)) == 1


def test_a_promotion_that_would_break_the_target_writes_nothing(tmp_path, monkeypatch):
    candidates, goldens = files(tmp_path)
    before = goldens.read_text(encoding="utf-8")
    monkeypatch.setattr(
        "loghog.emit.promote.render_promoted_case",
        lambda case, reviewed_by, ts_utc: ["- id: NOT-SNAKE-CASE"],
    )
    with pytest.raises(PromoteError) as excinfo:
        promote(
            candidates_path=candidates,
            case_ids=["loghog_w_chat_000"],
            into=goldens,
            reviewed_by="Bobby",
            ts_utc=TS,
        )
    assert "Nothing was written" in str(excinfo.value)
    assert goldens.read_text(encoding="utf-8") == before


def test_several_ids_promote_in_the_order_they_were_named(tmp_path):
    candidates, goldens = files(tmp_path)
    promote(
        candidates_path=candidates,
        case_ids=["loghog_w_chat_002", "loghog_w_chat_000"],
        into=goldens,
        reviewed_by="Bobby",
        ts_utc=TS,
    )
    assert [entry.id for entry in load_goldens(goldens)] == [
        "lamp_flickers",
        "loghog_w_chat_002",
        "loghog_w_chat_000",
    ]


def test_an_awkward_input_survives_promotion(tmp_path):
    awkward = "text: with a colon\nand a second line\n  and an indent"
    candidates = tmp_path / "candidates-w.yaml"
    candidates.write_text(
        render_cases_yaml([case(0, input_text=awkward)], window="w", dry_run=False),
        encoding="utf-8",
    )
    goldens = tmp_path / "goldens.yaml"
    promote(
        candidates_path=candidates,
        case_ids=["loghog_w_chat_000"],
        into=goldens,
        reviewed_by="Bobby",
        ts_utc=TS,
    )
    assert load_goldens(goldens)[0].input == awkward


# --- the placeholders -------------------------------------------------------


def test_a_dry_run_placeholder_case_cannot_be_promoted(tmp_path):
    """The candidates file says "do not promote them". This is what makes that true.

    A tool that prints a warning and then does the thing anyway has taught its
    operator that the warnings are decorative. `[SYNTHETIC]` criteria are a
    fixed list identical for every case; adopting one would put four sentences
    nobody wrote into somebody's definition of correct.
    """
    from loghog.label.draft import SYNTHETIC_CRITERIA

    placeholder = case(0, criteria=tuple(SYNTHETIC_CRITERIA[:3]), dry_run=True)
    candidates = tmp_path / "candidates-w.yaml"
    candidates.write_text(
        render_cases_yaml([placeholder], window="w", dry_run=True), encoding="utf-8"
    )
    goldens = tmp_path / "goldens.yaml"
    goldens.write_text(EXISTING, encoding="utf-8")
    before = goldens.read_text(encoding="utf-8")
    with pytest.raises(PromoteError) as excinfo:
        promote(
            candidates_path=candidates,
            case_ids=["loghog_w_chat_000"],
            into=goldens,
            reviewed_by="Bobby",
            ts_utc=TS,
        )
    message = str(excinfo.value)
    assert "loghog_w_chat_000" in message
    assert "--dry-run" in message
    assert goldens.read_text(encoding="utf-8") == before


def test_the_refusal_is_per_case_not_per_file(tmp_path):
    """A real case in a file that also holds a placeholder still promotes."""
    from loghog.label.draft import SYNTHETIC_CRITERIA

    cases = [case(0), case(1, criteria=tuple(SYNTHETIC_CRITERIA[:3]), dry_run=True)]
    candidates = tmp_path / "candidates-w.yaml"
    candidates.write_text(
        render_cases_yaml(cases, window="w", dry_run=False), encoding="utf-8"
    )
    goldens = tmp_path / "goldens.yaml"
    goldens.write_text(EXISTING, encoding="utf-8")
    result = promote(
        candidates_path=candidates,
        case_ids=["loghog_w_chat_000"],
        into=goldens,
        reviewed_by="Bobby",
        ts_utc=TS,
    )
    assert result.promoted == ("loghog_w_chat_000",)


def test_a_case_whose_notes_admit_to_a_dry_run_is_refused_too(tmp_path):
    """The marker is looked for in the notes as well as in the criteria.

    Somebody who edits the placeholder criteria by hand and leaves the notes
    alone has reviewed the criteria, which is most of a review — but the file
    still says nothing read this record, and that sentence is either true or it
    should not be there.
    """
    edited = case(
        0,
        criteria=("States the problem.", "Names the item.", "Does not invent a date."),
        dry_run=True,
    )
    candidates = tmp_path / "candidates-w.yaml"
    candidates.write_text(
        render_cases_yaml([edited], window="w", dry_run=False), encoding="utf-8"
    )
    goldens = tmp_path / "goldens.yaml"
    goldens.write_text(EXISTING, encoding="utf-8")
    with pytest.raises(PromoteError, match="dry-run"):
        promote(
            candidates_path=candidates,
            case_ids=["loghog_w_chat_000"],
            into=goldens,
            reviewed_by="Bobby",
            ts_utc=TS,
        )
