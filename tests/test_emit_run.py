"""Stage 07 end to end: labelled shortlist in, drafts and a review document out.

The load-bearing assertion in this file is that the emitted YAML loads with
`regression_detect.goldens.load_goldens` — project 1's own function, called
here, rather than a schema restated in a test.
"""

import json

import pytest
from regression_detect.goldens import load_goldens

from conftest import load_test_config
from loghog.cluster.window import cluster_window
from loghog.emit.run import (
    EXIT_NOTHING,
    EXIT_OK,
    EXIT_PARTIAL,
    candidates_path_for,
    emit_window,
    review_path_for,
)
from loghog.errors import EmitError, LabelError
from loghog.ingest.run import ingest
from loghog.label.draft import Draft, DraftOutcome, synthetic_drafter
from loghog.label.run import label_window
from loghog.score.run import score_window
from loghog.select.run import select_candidates

SUBJECTS = (
    "The delivery driver left my parcel in the recycling bin without ringing.",
    "My replacement kettle arrived with the lid already cracked across the hinge.",
    "The mobile app signs me out every time I rotate the phone to landscape.",
    "I was charged twice for one subscription renewal in the same minute.",
)

GOOD = Draft(
    criteria=(
        "States the problem the request describes.",
        "Names the item involved.",
        "Does not invent an order number.",
    ),
    notes="Catches summaries that drop the item.",
)


def prepared(tmp_path, *, drafter=None, count=4):
    config = load_test_config(tmp_path)
    rows = [
        {
            "id": f"chat-{index:03d}",
            "created": 1_788_000_000 + index,
            "messages": [
                {"role": "user", "content": SUBJECTS[index % len(SUBJECTS)]},
                {"role": "assistant", "content": f"A summary, number {index}."},
            ],
            "feedback": "down" if index % 2 == 0 else "up",
        }
        for index in range(count)
    ]
    source = tmp_path / "log.jsonl"
    source.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    ingest(
        config,
        input_path=source,
        source_format="jsonl",
        mapping_reference="openai_chat_jsonl",
        window="w",
        synthetic=True,
    )
    score_window(config, window="w")
    cluster_window(config, window="w")
    select_candidates(config, window="w")
    if drafter is None:
        drafter = lambda task: DraftOutcome(draft=GOOD, error_type=None, model_id="fake-1")  # noqa: E731
        label_window(config, window="w", drafter=drafter, dry_run=False, min_interval_ms=0)
    else:
        label_window(config, window="w", drafter=drafter, dry_run=True)
    return config


# --- the schema -------------------------------------------------------------


def test_the_emitted_file_loads_with_project_ones_own_loader(tmp_path):
    config = prepared(tmp_path)
    outcome = emit_window(config, window="w")
    cases = load_goldens(outcome.candidates_path)
    assert len(cases) == outcome.emitted
    assert all(case.id.startswith("loghog_w_") for case in cases)
    assert all(case.tags[0] == "loghog" for case in cases)
    assert all(case.criteria for case in cases)


def test_the_notes_carry_the_score_the_signals_and_the_record_id(tmp_path):
    config = prepared(tmp_path)
    outcome = emit_window(config, window="w")
    case = load_goldens(outcome.candidates_path)[0]
    assert "record chat-" in case.notes
    assert "score" in case.notes.lower()
    assert "Signals:" in case.notes


def test_the_input_in_the_emitted_case_is_the_redacted_one(tmp_path):
    """The whole reason this file may leave the machine."""
    config = load_test_config(tmp_path)
    rows = [
        {
            "id": "chat-000",
            "created": 1_788_000_000,
            "messages": [
                {
                    "role": "user",
                    "content": "Write to sam.doe@example.com about the cracked kettle lid.",
                },
                {"role": "assistant", "content": "A summary."},
            ],
        },
        {
            "id": "chat-001",
            "created": 1_788_000_100,
            "messages": [
                {"role": "user", "content": "The app signs me out when I rotate the phone."},
                {"role": "assistant", "content": "Another summary."},
            ],
        },
    ]
    source = tmp_path / "log.jsonl"
    source.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    ingest(
        config,
        input_path=source,
        source_format="jsonl",
        mapping_reference="openai_chat_jsonl",
        window="w",
        synthetic=True,
    )
    score_window(config, window="w")
    cluster_window(config, window="w")
    select_candidates(config, window="w")
    label_window(config, window="w", drafter=synthetic_drafter(), dry_run=True)
    outcome = emit_window(config, window="w")
    text = outcome.candidates_path.read_text(encoding="utf-8")
    assert "sam.doe@example.com" not in text
    assert "[EMAIL_1]" in text
    assert "sam.doe@example.com" not in outcome.review_path.read_text(encoding="utf-8")


# --- the review document ----------------------------------------------------


def test_the_review_document_has_a_box_per_criterion_and_a_verdict_line(tmp_path):
    config = prepared(tmp_path)
    outcome = emit_window(config, window="w")
    review = outcome.review_path.read_text(encoding="utf-8")
    assert review.count("- [ ]") >= 3 * outcome.emitted
    assert review.count("Accept / Edit / Reject") == outcome.emitted
    assert "loghog promote" in review


def test_the_review_document_shows_the_case_because_that_is_what_review_means(tmp_path):
    config = prepared(tmp_path)
    outcome = emit_window(config, window="w")
    review = outcome.review_path.read_text(encoding="utf-8")
    assert "recycling bin" in review or "kettle" in review


def test_a_dry_run_says_synthetic_on_the_first_line_of_both_files(tmp_path):
    config = prepared(tmp_path, drafter=synthetic_drafter())
    outcome = emit_window(config, window="w")
    assert outcome.candidates_path.read_text().splitlines()[0].startswith("# SYNTHETIC")
    assert outcome.review_path.read_text().splitlines()[0].startswith("SYNTHETIC")
    assert outcome.dry_run


def test_a_live_run_carries_no_synthetic_banner(tmp_path):
    config = prepared(tmp_path)
    outcome = emit_window(config, window="w")
    assert "SYNTHETIC" not in outcome.candidates_path.read_text()
    assert not outcome.dry_run


# --- what it refuses --------------------------------------------------------


def test_a_candidate_whose_draft_failed_is_left_out_and_counted(tmp_path):
    def half(task):
        if task.record_id == "chat-000":
            return DraftOutcome(draft=None, error_type="DraftParseError", model_id="fake-1")
        return DraftOutcome(draft=GOOD, error_type=None, model_id="fake-1")

    config = load_test_config(tmp_path)
    prepared_config = prepared(tmp_path)
    assert prepared_config.root == config.root
    label_window(prepared_config, window="w", drafter=half, dry_run=False, min_interval_ms=0)
    outcome = emit_window(prepared_config, window="w")
    assert outcome.exit_code == EXIT_PARTIAL
    assert outcome.skipped_count == 1
    ids = {case.id for case in load_goldens(outcome.candidates_path)}
    assert "loghog_w_chat_000" not in ids
    review = outcome.review_path.read_text(encoding="utf-8")
    assert "chat-000" in review
    assert "DraftParseError" in review


def test_every_draft_having_failed_writes_nothing_and_exits_two(tmp_path):
    config = prepared(tmp_path)

    def always_fail(task):
        return DraftOutcome(draft=None, error_type="ProviderTransientError", model_id="fake-1")

    label_window(config, window="w", drafter=always_fail, dry_run=False, min_interval_ms=0)
    outcome = emit_window(config, window="w")
    assert outcome.exit_code == EXIT_NOTHING
    assert outcome.emitted == 0
    assert not outcome.candidates_path.exists()
    assert outcome.review_path.is_file()


def test_an_unlabelled_window_is_refused_by_name(tmp_path):
    """`LabelError`, not `EmitError`, and that is the right way round.

    The type names the artefact that is missing — the labels — and the message
    names the command that produces it. An `EmitError` here would say the
    emission failed, when in fact it never had anything to emit from.
    """
    config = load_test_config(tmp_path)
    with pytest.raises(LabelError) as excinfo:
        emit_window(config, window="nope")
    assert "loghog label" in str(excinfo.value)


def test_a_label_naming_a_record_the_shortlist_does_not_hold_is_refused(tmp_path):
    config = prepared(tmp_path)
    path = config.selected_dir / "w" / "labels.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines() if line]
    rows[0]["record_id"] = "ghost"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    with pytest.raises(EmitError) as excinfo:
        emit_window(config, window="w")
    assert "ghost" in str(excinfo.value)


def test_the_paths_are_named_by_the_window(tmp_path):
    config = load_test_config(tmp_path)
    assert candidates_path_for(config, "2026-09-04").name == "candidates-2026-09-04.yaml"
    assert review_path_for(config, "2026-09-04").name == "review-2026-09-04.md"


def test_a_second_emit_writes_identical_bytes(tmp_path):
    config = prepared(tmp_path)
    first = emit_window(config, window="w")
    before = first.candidates_path.read_bytes()
    second = emit_window(config, window="w")
    assert second.candidates_path.read_bytes() == before
    assert second.exit_code == EXIT_OK


def test_the_review_document_is_readable_markdown(tmp_path):
    """Blank lines between blocks, because markdown is whitespace-sensitive.

    The first version filtered empty strings out of the section builder to drop
    the drafter's note when there was none, and took every blank line with them
    — so headings, blockquotes and checkbox lists ran together and half the
    document rendered as one paragraph. It looked fine in a terminal, which is
    exactly why it survived until somebody opened the committed example.
    """
    config = prepared(tmp_path)
    outcome = emit_window(config, window="w")
    review = outcome.review_path.read_text(encoding="utf-8")
    lines = review.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("## "):
            assert lines[index + 1] == "", f"no blank line after {line!r}"
        if line.startswith("> ") and index + 1 < len(lines):
            following = lines[index + 1]
            assert following == "" or following.startswith("> "), (
                f"a blockquote is glued to {following!r}"
            )
        if line.startswith("**") and index + 1 < len(lines):
            assert lines[index + 1] == "", f"no blank line after {line!r}"
    assert "\n\n- [ ] " in review
