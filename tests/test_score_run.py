"""Scoring a whole window: what it writes, what it refuses, and what it admits.

The two files it writes have different jobs. `scores.jsonl` is for stages 04 and
05 and holds one object per record. `score.md` is for a person, and its most
important section is the one listing the signals that could **not** be
evaluated — because a report that silently printed zero for a signal the window
cannot support would be worse than not having the signal at all.
"""

import json

import pytest

from conftest import SAMPLES_DIR, load_test_config
from loghog.errors import ScoreError
from loghog.ingest.run import ingest
from loghog.score.run import EXIT_OK, EXIT_PARTIAL, score_window
from loghog.window.artifacts import read_scores
from loghog.window.store import WindowStore

SAMPLE = SAMPLES_DIR / "support_chat.synthetic.jsonl"


def ingested(tmp_path, *, substitutions=()):
    config = load_test_config(tmp_path, substitutions)
    ingest(
        config,
        input_path=SAMPLE,
        source_format="jsonl",
        mapping_reference="openai_chat_jsonl",
        window="demo",
        synthetic=True,
    )
    return config


def scored(tmp_path, *, substitutions=(), **overrides):
    config = ingested(tmp_path, substitutions=substitutions)
    return config, score_window(config, window="demo", **overrides)


def test_scoring_writes_one_line_per_record(tmp_path):
    config, outcome = scored(tmp_path)
    store = WindowStore(config.records_dir / "demo")
    lines = store.scores_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == outcome.scored
    assert outcome.scored == 9


def test_every_scored_line_is_a_record_id_a_score_and_its_signals(tmp_path):
    config, _ = scored(tmp_path)
    store = WindowStore(config.records_dir / "demo")
    for line in store.scores_path.read_text(encoding="utf-8").splitlines():
        payload = json.loads(line)
        assert sorted(payload) == ["record_id", "score", "signals"]
        assert payload["score"] == sum(signal["weight"] for signal in payload["signals"])


def test_the_scores_read_back_as_the_same_numbers(tmp_path):
    config, outcome = scored(tmp_path)
    store = WindowStore(config.records_dir / "demo")
    assert read_scores(store) == {entry.record_id: entry.score for entry in outcome.scores}


def test_the_sample_has_at_least_one_failed_call_to_find(tmp_path):
    # `chat-009` is the request that got no reply and named an error.
    _, outcome = scored(tmp_path)
    by_id = {entry.record_id: entry for entry in outcome.scores}
    assert "error" in {signal.name for signal in by_id["chat-009"].signals}


def test_scoring_the_same_window_twice_gives_identical_files(tmp_path):
    config, _ = scored(tmp_path)
    store = WindowStore(config.records_dir / "demo")
    first = store.scores_path.read_text(encoding="utf-8")
    score_window(config, window="demo")
    assert store.scores_path.read_text(encoding="utf-8") == first


def test_the_report_names_the_weights_it_used(tmp_path):
    config, _ = scored(tmp_path)
    report = (config.records_dir / "demo" / "score.md").read_text(encoding="utf-8")
    assert "judge_failure" in report
    assert "## Weights" in report


def test_the_report_lists_what_could_not_be_evaluated(tmp_path):
    config, _ = scored(tmp_path)
    report = (config.records_dir / "demo" / "score.md").read_text(encoding="utf-8")
    assert "Not evaluated" in report
    assert "novelty" in report


def test_the_report_quotes_no_record_text(tmp_path):
    config, _ = scored(tmp_path)
    report = (config.records_dir / "demo" / "score.md").read_text(encoding="utf-8")
    for fragment in ("lamp", "Dr Pepper", "refund", "flickers"):
        assert fragment not in report


def test_a_window_ingested_with_dedupe_on_exits_partial_and_says_why(tmp_path):
    # The committed configuration deduplicates, and deduplication is on the
    # input — so two prompt versions answering one question are already one
    # record and the disagreement signal cannot see anything. Exit 1.
    _, outcome = scored(tmp_path)
    assert outcome.exit_code == EXIT_PARTIAL
    blocked = {entry.signal for entry in outcome.context.not_evaluated if entry.blocking}
    assert blocked == {"version_disagreement"}


def test_a_window_ingested_without_dedupe_scores_cleanly(tmp_path):
    _, outcome = scored(tmp_path, substitutions=[("dedupe = true", "dedupe = false")])
    assert outcome.exit_code == EXIT_OK


def test_a_missing_window_is_refused_with_the_command_that_fixes_it(tmp_path):
    config = load_test_config(tmp_path)
    with pytest.raises(ScoreError, match="loghog ingest"):
        score_window(config, window="never-ingested")


def test_goldens_switch_the_novelty_signal_on(tmp_path):
    config, outcome = scored(tmp_path, golden_inputs=["something about a tax return"])
    unevaluated = {entry.signal for entry in outcome.context.not_evaluated}
    assert "novelty" not in unevaluated
    assert any("novelty" in {s.name for s in entry.signals} for entry in outcome.scores)


def test_the_scores_file_is_written_with_the_same_permissions_as_the_records(tmp_path):
    config, _ = scored(tmp_path)
    store = WindowStore(config.records_dir / "demo")
    assert store.scores_path.stat().st_mode & 0o777 == 0o600


def test_rescoring_replaces_rather_than_appends(tmp_path):
    config, outcome = scored(tmp_path)
    store = WindowStore(config.records_dir / "demo")
    score_window(config, window="demo")
    lines = store.scores_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == outcome.scored


def test_the_outcome_counts_how_many_records_fired_each_signal(tmp_path):
    _, outcome = scored(tmp_path)
    assert outcome.by_signal["error"] == 1
    assert set(outcome.by_signal) <= set(outcome.context.settings.weights)
