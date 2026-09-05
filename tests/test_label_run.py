"""Stage 06 end to end, with a drafter handed in rather than built.

The call count is the property worth testing hardest. One bounded call per
selected candidate is the whole design: a labelled dataset whose cost is
proportional to something other than the number of candidates is a dataset
nobody will rebuild.
"""

import json

import pytest

from conftest import load_test_config
from loghog.cluster.window import cluster_window
from loghog.errors import LabelError
from loghog.ingest.run import ingest
from loghog.label.draft import (
    DRAFT_PROMPT_SHA256,
    DRY_RUN_MODEL_ID,
    SYNTHETIC_MARKER,
    Draft,
    DraftOutcome,
    synthetic_drafter,
)
from loghog.label.run import (
    EXIT_NOTHING,
    EXIT_OK,
    EXIT_PARTIAL,
    LABEL_REPORT_NAME,
    LABELS_NAME,
    label_window,
    read_labels,
)
from loghog.score.run import score_window
from loghog.select.run import select_candidates

GOOD = Draft(
    criteria=(
        "States the problem the request describes.",
        "Names the item involved.",
        "Does not invent an order number.",
    ),
    notes="Catches summaries that drop the item.",
)


def counting_drafter(outcome_for=None):
    """A drafter that records every task it was handed."""
    seen = []

    def drafter(task):
        seen.append(task)
        if outcome_for is not None:
            return outcome_for(task)
        return DraftOutcome(draft=GOOD, error_type=None, model_id="fake-1")

    drafter.seen = seen
    return drafter


SUBJECTS = (
    "The delivery driver left my parcel in the recycling bin without ringing.",
    "My replacement kettle arrived with the lid already cracked across the hinge.",
    "The mobile app signs me out every time I rotate the phone to landscape.",
    "I was charged twice for one subscription renewal in the same minute.",
    "The warranty card in the box names a model I did not order at all.",
    "Your shop refuses my postcode at checkout and offers no way to correct it.",
)
"""Six subjects with nothing in common, so the cluster cap does not fold them
into one case. A fixture whose records were paraphrases of each other would be
testing stage 04 rather than this one."""


def prepared(tmp_path, *, count=6, verdicts=True):
    """A window that has been ingested, scored, clustered and selected."""
    config = load_test_config(tmp_path)
    rows = []
    for index in range(count):
        rows.append(
            {
                "id": f"chat-{index:03d}",
                "created": 1_788_000_000 + index,
                "messages": [
                    {"role": "user", "content": SUBJECTS[index % len(SUBJECTS)]},
                    {"role": "assistant", "content": f"A summary, number {index}."},
                ],
                "latency_ms": 300 + index,
                "feedback": "down" if index % 2 == 0 else "up",
            }
        )
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
    if verdicts:
        _add_verdicts(config)
    score_window(config, window="w")
    cluster_window(config, window="w")
    select_candidates(config, window="w")
    return config


def _add_verdicts(config):
    """Rewrite the window's records with one failed verdict on the first."""
    path = config.records_dir / "w" / "records.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    rows[0]["judge_verdicts"] = [{"criterion": "names the item", "passed": False}]
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8"
    )


# --- the bound --------------------------------------------------------------


def test_the_call_count_equals_the_candidate_count_exactly(tmp_path):
    config = prepared(tmp_path)
    drafter = counting_drafter()
    outcome = label_window(config, window="w", drafter=drafter, dry_run=False, min_interval_ms=0)
    assert len(drafter.seen) == outcome.considered
    assert outcome.calls == len(drafter.seen)
    assert outcome.drafted == outcome.considered


def test_a_dry_run_makes_no_network_call_at_all(tmp_path):
    """Asserted by handing in a drafter that raises if it is called."""
    config = prepared(tmp_path)

    def explode(task):
        raise AssertionError("a dry run called the provider")

    outcome = label_window(config, window="w", drafter=synthetic_drafter(), dry_run=True)
    assert outcome.dry_run
    assert outcome.model_id == DRY_RUN_MODEL_ID
    assert all(
        line.startswith(SYNTHETIC_MARKER) for label in outcome.labels for line in label.criteria
    )
    with pytest.raises(AssertionError):
        explode(None)


def test_the_budget_refuses_rather_than_truncating(tmp_path):
    config = prepared(tmp_path, count=6)
    substituted = load_test_config(tmp_path, [("max_calls = 120", "max_calls = 2")])
    drafter = counting_drafter()
    with pytest.raises(LabelError) as excinfo:
        label_window(substituted, window="w", drafter=drafter, dry_run=False, min_interval_ms=0)
    assert "max_calls" in str(excinfo.value)
    assert drafter.seen == []
    assert config.select.max_candidates >= 2


def test_the_verdicts_and_signals_reach_the_drafter(tmp_path):
    config = prepared(tmp_path)
    drafter = counting_drafter()
    label_window(config, window="w", drafter=drafter, dry_run=False, min_interval_ms=0)
    tasks = {task.record_id: task for task in drafter.seen}
    assert any(task.signals for task in tasks.values())
    judged = tasks.get("chat-000")
    assert judged is not None
    assert judged.verdicts == (("names the item", False),)


# --- what it writes ---------------------------------------------------------


def test_it_writes_one_label_per_candidate_and_a_report(tmp_path):
    config = prepared(tmp_path)
    outcome = label_window(
        config, window="w", drafter=counting_drafter(), dry_run=False, min_interval_ms=0
    )
    labels_path = config.selected_dir / "w" / LABELS_NAME
    report_path = config.selected_dir / "w" / LABEL_REPORT_NAME
    assert labels_path.is_file() and report_path.is_file()
    rows = [json.loads(line) for line in labels_path.read_text().splitlines() if line]
    assert len(rows) == outcome.considered
    assert rows[0]["prompt_sha256"] == DRAFT_PROMPT_SHA256
    assert rows[0]["draft_error"] is None


def test_a_failed_draft_is_recorded_with_a_null_criteria_list(tmp_path):
    """Never an empty list: absent and empty are different facts everywhere here."""
    config = prepared(tmp_path)

    def half(task):
        if task.record_id.endswith("0"):
            return DraftOutcome(draft=None, error_type="DraftParseError", model_id="fake-1")
        return DraftOutcome(draft=GOOD, error_type=None, model_id="fake-1")

    outcome = label_window(
        config, window="w", drafter=counting_drafter(half), dry_run=False, min_interval_ms=0
    )
    assert outcome.exit_code == EXIT_PARTIAL
    assert outcome.failed >= 1
    rows = {
        row["record_id"]: row
        for row in (
            json.loads(line)
            for line in (config.selected_dir / "w" / LABELS_NAME).read_text().splitlines()
            if line
        )
    }
    failed = rows["chat-000"]
    assert failed["criteria"] is None
    assert failed["draft_error"] == "DraftParseError"


def test_every_draft_failing_writes_nothing_and_exits_two(tmp_path):
    config = prepared(tmp_path)

    def always_fail(task):
        return DraftOutcome(draft=None, error_type="ProviderTransientError", model_id="fake-1")

    outcome = label_window(
        config,
        window="w",
        drafter=counting_drafter(always_fail),
        dry_run=False,
        min_interval_ms=0,
    )
    assert outcome.exit_code == EXIT_NOTHING
    assert outcome.drafted == 0
    assert outcome.by_error == {"ProviderTransientError": outcome.considered}


def test_the_report_carries_no_case_text(tmp_path):
    config = prepared(tmp_path)
    label_window(config, window="w", drafter=counting_drafter(), dry_run=False, min_interval_ms=0)
    report = (config.selected_dir / "w" / LABEL_REPORT_NAME).read_text(encoding="utf-8")
    assert "Complaint number" not in report
    assert "A summary of complaint" not in report


def test_a_dry_run_report_says_synthetic_on_its_first_line(tmp_path):
    config = prepared(tmp_path)
    label_window(config, window="w", drafter=synthetic_drafter(), dry_run=True)
    report = (config.selected_dir / "w" / LABEL_REPORT_NAME).read_text(encoding="utf-8")
    assert report.splitlines()[0].startswith("SYNTHETIC")


def test_a_second_run_writes_identical_bytes(tmp_path):
    config = prepared(tmp_path)
    label_window(config, window="w", drafter=counting_drafter(), dry_run=False, min_interval_ms=0)
    first = (config.selected_dir / "w" / LABELS_NAME).read_bytes()
    label_window(config, window="w", drafter=counting_drafter(), dry_run=False, min_interval_ms=0)
    assert (config.selected_dir / "w" / LABELS_NAME).read_bytes() == first


def test_labels_read_back(tmp_path):
    config = prepared(tmp_path)
    outcome = label_window(
        config, window="w", drafter=counting_drafter(), dry_run=False, min_interval_ms=0
    )
    read = read_labels(config.selected_dir / "w")
    assert {label.record_id for label in read} == {
        label.record_id for label in outcome.labels
    }
    assert read[0].criteria == GOOD.criteria


# --- refusals ---------------------------------------------------------------


def test_an_unselected_window_is_refused_by_name(tmp_path):
    config = load_test_config(tmp_path)
    with pytest.raises(LabelError) as excinfo:
        label_window(
            config, window="nope", drafter=counting_drafter(), dry_run=False, min_interval_ms=0
        )
    assert "loghog select" in str(excinfo.value)


def test_an_empty_shortlist_is_refused_rather_than_labelled(tmp_path):
    config = prepared(tmp_path)
    (config.selected_dir / "w" / "candidates.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(LabelError):
        label_window(
            config, window="w", drafter=counting_drafter(), dry_run=False, min_interval_ms=0
        )


def test_a_candidate_naming_a_record_the_window_does_not_hold_is_refused(tmp_path):
    config = prepared(tmp_path)
    path = config.selected_dir / "w" / "candidates.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines() if line]
    rows[0]["record_id"] = "ghost"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    with pytest.raises(LabelError) as excinfo:
        label_window(
            config, window="w", drafter=counting_drafter(), dry_run=False, min_interval_ms=0
        )
    assert "ghost" in str(excinfo.value)


def test_a_record_with_no_output_is_still_labelled(tmp_path):
    """A request that failed is a case worth having criteria for.

    The drafter is told so in words — `(no output — the call failed …)` — rather
    than being handed a blank, because "the system produced nothing" is a fact
    about this case and the strongest one there is.
    """
    config = load_test_config(tmp_path)
    rows = [
        {
            "id": "chat-000",
            "created": 1_788_000_000,
            "messages": [{"role": "user", "content": "The lamp arrived broken in half."}],
            "error": "upstream timeout",
        },
        {
            "id": "chat-001",
            "created": 1_788_000_100,
            "messages": [
                {"role": "user", "content": "A totally unrelated question about billing."},
                {"role": "assistant", "content": "The customer asks about billing."},
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
    drafter = counting_drafter()
    outcome = label_window(config, window="w", drafter=drafter, dry_run=False, min_interval_ms=0)
    assert outcome.exit_code == EXIT_OK
    assert any(task.output_text is None for task in drafter.seen)


# --- pacing -----------------------------------------------------------------


def test_the_configured_interval_is_what_paces_a_live_run(tmp_path, monkeypatch):
    """The gap comes from `[label] min_interval_ms`, and reaches project 1's helper."""
    config = prepared(tmp_path)
    seen = []

    def spy(previous_start, min_interval_ms):
        seen.append(min_interval_ms)
        return 0.0

    monkeypatch.setattr("loghog.label.run.pace", spy)
    label_window(config, window="w", drafter=counting_drafter(), dry_run=False)
    assert seen and set(seen) == {config.label.min_interval_ms}
    assert config.label.min_interval_ms > 0


def test_a_dry_run_paces_at_zero_whatever_it_was_told(tmp_path, monkeypatch):
    """Nothing is called, so there is no quota to spread a burst across."""
    config = prepared(tmp_path)
    seen = []

    def spy(previous_start, min_interval_ms):
        seen.append(min_interval_ms)
        return 0.0

    monkeypatch.setattr("loghog.label.run.pace", spy)
    label_window(
        config, window="w", drafter=synthetic_drafter(), dry_run=True, min_interval_ms=9999
    )
    assert set(seen) == {0}


def test_a_negative_interval_is_refused_by_project_ones_validator(tmp_path):
    config = prepared(tmp_path)
    with pytest.raises(ValueError):
        label_window(
            config, window="w", drafter=counting_drafter(), dry_run=False, min_interval_ms=-1
        )
