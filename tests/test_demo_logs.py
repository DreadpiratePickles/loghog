"""The two committed demo windows: what is in them, and what must come out.

These are fixtures with a job. The lifecycle in `docs/examples/` is recorded
against them, the CI job runs the whole pipeline over them, and the README quotes
their numbers — so a change to either file that quietly removed a planted card
number or an injection attempt would make three other things wrong at once, and
none of them would fail.
"""

import json

import pytest

from conftest import REPO_ROOT, load_test_config
from loghog.cluster.window import cluster_window
from loghog.drift.run import drift_report
from loghog.ingest.run import ingest
from loghog.score.run import score_window

LOGS = REPO_ROOT / "logs"
WINDOW_A = LOGS / "demo_window_a.jsonl"
WINDOW_B = LOGS / "demo_window_b.jsonl"

PLANTED = (
    "susan.calvin@example.com",
    "kim.reyes@example.com",
    "4242 4242 4242 4242",
    "4111-1111-1111-1111",
    "123-45-6789",
    "GB33BUKB20201555555555",
    "192.168.1.14",
    "+44 7700 900123",
    "221B Baker Street",
    "Dr Susan Calvin",
    "Mr Elijah Baley",
)

MUST_SURVIVE = "1234567812345678"
"""Sixteen digits that fail Luhn. It is an order reference, not a card, and a
redactor that blanks it has removed the thing the ticket was about."""


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_the_directory_says_synthetic_on_its_own_first_line():
    assert (LOGS / "README.md").read_text(encoding="utf-8").splitlines()[0].startswith(
        "SYNTHETIC"
    )


@pytest.mark.parametrize("path", [WINDOW_A, WINDOW_B])
def test_each_window_holds_exactly_a_hundred_and_twenty_records(path):
    assert len(rows(path)) == 120


@pytest.mark.parametrize("path", [WINDOW_A, WINDOW_B])
def test_every_line_is_the_generic_chat_shape(path):
    for row in rows(path):
        assert set(row) <= {"id", "created", "model", "messages", "usage", "latency_ms",
                            "error", "feedback"}
        assert row["messages"][0]["role"] == "system"
        assert row["messages"][1]["role"] == "user"
        assert ("error" in row) != any(m["role"] == "assistant" for m in row["messages"])


@pytest.mark.parametrize("path", [WINDOW_A, WINDOW_B])
def test_every_class_of_personal_data_is_planted_in_both_windows(path):
    text = path.read_text(encoding="utf-8")
    for value in PLANTED:
        assert value in text, f"{path.name} no longer plants {value!r}"
    assert MUST_SURVIVE in text


@pytest.mark.parametrize("path", [WINDOW_A, WINDOW_B])
def test_the_injections_and_refusals_are_there(path):
    from loghog.score.patterns import matched_injection, matched_refusal

    injections, refusals = set(), set()
    for row in rows(path):
        user = row["messages"][1]["content"]
        injections.add(matched_injection(user))
        for message in row["messages"]:
            if message["role"] == "assistant":
                refusals.add(matched_refusal(message["content"]))
    assert len(injections - {None}) >= 2
    assert len(refusals - {None}) >= 2


def test_the_two_windows_share_subjects_and_each_has_its_own():
    users_a = {row["messages"][1]["content"][:40] for row in rows(WINDOW_A)}
    users_b = {row["messages"][1]["content"][:40] for row in rows(WINDOW_B)}
    assert users_a & users_b
    assert users_a - users_b
    assert users_b - users_a


# --- what the pipeline makes of them ----------------------------------------


def ingested(tmp_path, path, window, config):
    ingest(
        config,
        input_path=path,
        source_format="jsonl",
        mapping_reference="openai_chat_jsonl",
        window=window,
        synthetic=True,
    )
    score_window(config, window=window)
    cluster_window(config, window=window)


def test_no_planted_value_survives_into_a_window(tmp_path):
    config = load_test_config(tmp_path, [("dedupe = true", "dedupe = false")])
    ingested(tmp_path, WINDOW_A, "a", config)
    records = (config.records_dir / "a" / "records.jsonl").read_text(encoding="utf-8")
    for value in PLANTED:
        assert value not in records, f"redaction let {value!r} through"
    assert MUST_SURVIVE in records
    assert "[EMAIL_1]" in records


def test_the_later_window_has_the_worse_week_and_drift_says_so(tmp_path):
    config = load_test_config(tmp_path, [("dedupe = true", "dedupe = false")])
    ingested(tmp_path, WINDOW_A, "a", config)
    ingested(tmp_path, WINDOW_B, "b", config)
    outcome = drift_report(config, earlier="a", later="b")
    errors = outcome.rates["error"]
    assert errors.later_rate > errors.earlier_rate
    assert errors.separated
    assert outcome.novelty.new_clusters > 0
    assert outcome.synthetic


def test_both_windows_are_big_enough_for_the_outlier_signals(tmp_path):
    """A p95 over nine records is not a p95, and stage 03 refuses to pretend."""
    config = load_test_config(tmp_path, [("dedupe = true", "dedupe = false")])
    ingested(tmp_path, WINDOW_A, "a", config)
    outcome = score_window(config, window="a")
    skipped = {entry.signal for entry in outcome.context.not_evaluated}
    assert "latency_outlier" not in skipped
    assert "length_outlier" not in skipped


def test_nine_of_the_thirteen_signals_fire_on_the_later_window(tmp_path):
    """The other four need a log format this one deliberately is not."""
    config = load_test_config(tmp_path, [("dedupe = true", "dedupe = false")])
    ingested(tmp_path, WINDOW_B, "b", config)
    outcome = score_window(config, window="b")
    fired = {name for name, count in outcome.by_signal.items() if count}
    assert fired == {
        "error",
        "negative_feedback",
        "feedback_conflict",
        "injection_pattern",
        "refusal_pattern",
        "latency_outlier",
        "length_outlier",
        "non_ascii_ratio",
        "tiny_input",
    }
