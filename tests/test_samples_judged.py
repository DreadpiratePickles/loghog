"""The committed judged sample, end to end through all four Phase B commands.

Thirteen invented events written to fire twelve of the thirteen signals, so that
the suite and the CI job prove the stage rather than proving an empty table. The
thirteenth is `novelty`, which needs a goldens file and gets one here.

If the sample changes, these numbers change with it. That is the point: a
signal that quietly stopped firing would otherwise cost nothing and be noticed
by nobody.
"""

import pytest

from conftest import SAMPLES_DIR, load_test_config
from loghog.cluster.window import cluster_window
from loghog.drift.run import drift_report
from loghog.ingest.run import EXIT_OK, ingest
from loghog.score.run import score_window
from loghog.select.run import select_candidates

SAMPLE = SAMPLES_DIR / "judged_summaries.synthetic.jsonl"
MAPPING = SAMPLES_DIR / "judged_summaries.toml"
CHAT = SAMPLES_DIR / "support_chat.synthetic.jsonl"

GOLDEN_INPUT = "The delivery driver left the parcel in the recycling bin without ringing."


@pytest.fixture
def judged(tmp_path):
    """The sample ingested with dedupe off, which is what the disagreement needs."""
    config = load_test_config(tmp_path, [("dedupe = true", "dedupe = false")])
    outcome = ingest(
        config, input_path=SAMPLE, source_format="jsonl", mapping_reference=str(MAPPING),
        window="judged", synthetic=True,
    )
    return config, outcome


def test_every_line_of_the_sample_is_accounted_for(judged):
    _, outcome = judged
    counts = outcome.manifest.counts
    assert counts.lines_read == counts.rows + counts.blank_lines + counts.unparsed
    assert counts.rows == counts.records_written + counts.duplicates_dropped + counts.invalid
    assert (counts.lines_read, counts.records_written, counts.blank_lines) == (14, 13, 1)


def test_the_sample_ingests_cleanly(judged):
    _, outcome = judged
    assert outcome.exit_code == EXIT_OK


def test_the_address_in_the_sample_is_redacted_before_it_is_written(judged):
    config, outcome = judged
    text = (outcome.directory / "records.jsonl").read_text(encoding="utf-8")
    assert "sam.doe@example.com" not in text
    assert "[EMAIL_1]" in text


def test_the_manifest_records_that_this_mapping_expects_json(judged):
    _, outcome = judged
    assert outcome.manifest.sources[0].expect_output_json is True


def test_twelve_of_the_thirteen_signals_fire_on_the_sample(judged):
    config, _ = judged
    outcome = score_window(config, window="judged")
    assert outcome.by_signal == {
        "error": 1,
        "judge_failure": 2,
        "negative_feedback": 1,
        "feedback_conflict": 1,
        "version_disagreement": 2,
        "injection_pattern": 1,
        "refusal_pattern": 1,
        "format_violation": 2,
        "latency_outlier": 1,
        "length_outlier": 3,
        "non_ascii_ratio": 1,
        "tiny_input": 1,
    }


def test_the_thirteenth_signal_needs_a_goldens_file_and_then_fires(judged):
    config, _ = judged
    outcome = score_window(config, window="judged", golden_inputs=[GOLDEN_INPUT])
    assert outcome.by_signal["novelty"] == 11
    assert outcome.context.not_evaluated == ()


def test_the_two_prompt_versions_disagree_on_one_input(judged):
    config, _ = judged
    outcome = score_window(config, window="judged")
    disagreeing = {
        entry.record_id
        for entry in outcome.scores
        if "version_disagreement" in {signal.name for signal in entry.signals}
    }
    assert disagreeing == {"js-002", "js-012"}


def test_the_paraphrased_delivery_complaint_clusters_with_its_twin(judged):
    config, _ = judged
    score_window(config, window="judged")
    outcome = cluster_window(config, window="judged")
    pairs = {cluster.member_ids for cluster in outcome.clusters if cluster.size > 1}
    assert ("js-001", "js-010") in pairs


def test_the_shortlist_is_one_case_per_cluster_and_spread_across_strata(judged):
    config, _ = judged
    score_window(config, window="judged")
    cluster_window(config, window="judged")
    outcome = select_candidates(config, window="judged")
    assert outcome.selected_count == 10
    assert outcome.dropped == {"cluster_cap": 3}
    strata = {entry.stratum for entry in outcome.selected}
    assert len(strata) >= 8


def test_the_sample_can_be_compared_with_the_chat_sample(judged):
    config, _ = judged
    score_window(config, window="judged")
    cluster_window(config, window="judged")
    ingest(
        config, input_path=CHAT, source_format="jsonl",
        mapping_reference="openai_chat_jsonl", window="chat", synthetic=True,
    )
    score_window(config, window="chat")
    cluster_window(config, window="chat")
    outcome = drift_report(config, earlier="chat", later="judged")
    # Two different sets of invented complaints: nothing in one looks like the
    # other, so every cluster in the later window is new.
    assert outcome.novelty.share == 1.0
    assert outcome.signal_rates["judge_failure"].delta > 0
