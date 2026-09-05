"""Stage 08: is the dataset still about the system it came from?

The two figures that matter pull in opposite directions and share one threshold
on purpose. Coverage asks whether traffic has a case near it; staleness asks
whether a case has traffic near it. Two thresholds would let one report say a
cluster is covered by a case that is itself stale against that cluster, which is
not a finding.
"""

import json

import pytest
from regression_detect.compare import fisher_exact_one_sided, wilson_interval

from conftest import load_test_config
from loghog.cluster.window import cluster_window
from loghog.errors import HealthError
from loghog.health.run import health_report, json_path_for, markdown_path_for
from loghog.ingest.run import ingest
from loghog.score.run import score_window

SUBJECTS = (
    "The delivery driver left my parcel in the recycling bin without ringing.",
    "My replacement kettle arrived with the lid already cracked across the hinge.",
    "The mobile app signs me out every time I rotate the phone to landscape.",
    "I was charged twice for one subscription renewal in the same minute.",
    "The warranty card in the box names a model I did not order at all.",
)


def goldens_yaml(inputs, path):
    lines = []
    for index, text in enumerate(inputs):
        lines += [
            f"- id: case_{index}",
            "  tags: [hand_written]",
            f"  input: {json.dumps(text)}",
            "  criteria:",
            "    - Names the item",
        ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def windowed(tmp_path, *, subjects=SUBJECTS, feedback=True):
    config = load_test_config(tmp_path)
    rows = [
        {
            "id": f"chat-{index:03d}",
            "created": 1_788_000_000 + index,
            "messages": [
                {"role": "user", "content": text},
                {"role": "assistant", "content": f"A summary, number {index}."},
            ],
            **({"feedback": "down"} if feedback and index == 0 else {}),
        }
        for index, text in enumerate(subjects)
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
    return config


# --- coverage ---------------------------------------------------------------


def test_a_dataset_that_covers_everything_reports_one_with_an_interval_that_includes_it(
    tmp_path,
):
    config = windowed(tmp_path)
    goldens = goldens_yaml(SUBJECTS, tmp_path / "goldens.yaml")
    outcome = health_report(config, window="w", goldens_path=goldens)
    assert outcome.coverage.share == 1.0
    low, high = outcome.coverage.interval
    assert low <= 1.0 <= high
    assert outcome.coverage.interval == wilson_interval(
        outcome.coverage.covered, outcome.coverage.total
    )


def test_a_dataset_that_covers_nothing_reports_zero_and_does_not_divide_by_zero(tmp_path):
    config = windowed(tmp_path)
    goldens = goldens_yaml(
        ["Something about astrophysics that no ticket here mentions."],
        tmp_path / "goldens.yaml",
    )
    outcome = health_report(config, window="w", goldens_path=goldens)
    assert outcome.coverage.share == 0.0
    assert outcome.coverage.covered == 0
    assert outcome.coverage.total > 0


def test_partial_coverage_is_counted_per_cluster(tmp_path):
    config = windowed(tmp_path)
    goldens = goldens_yaml(SUBJECTS[:2], tmp_path / "goldens.yaml")
    outcome = health_report(config, window="w", goldens_path=goldens)
    assert 0.0 < outcome.coverage.share < 1.0
    assert outcome.coverage.covered == 2


# --- staleness --------------------------------------------------------------


def test_a_case_with_no_traffic_near_it_is_stale(tmp_path):
    config = windowed(tmp_path)
    goldens = goldens_yaml(
        [SUBJECTS[0], "A question about the tax treatment of a company car."],
        tmp_path / "goldens.yaml",
    )
    outcome = health_report(config, window="w", goldens_path=goldens)
    assert outcome.staleness.stale == 1
    assert outcome.staleness.total == 2
    assert [entry.case_id for entry in outcome.staleness.entries] == ["case_1"]


def test_staleness_and_coverage_share_one_threshold(tmp_path):
    config = windowed(tmp_path)
    goldens = goldens_yaml(SUBJECTS, tmp_path / "goldens.yaml")
    outcome = health_report(config, window="w", goldens_path=goldens)
    assert outcome.threshold == config.health.neighbour_jaccard
    assert outcome.staleness.stale == 0
    assert outcome.coverage.covered == outcome.coverage.total


# --- gaps and recommendations -----------------------------------------------


def test_the_gap_list_is_ordered_by_cluster_size_and_is_deterministic(tmp_path):
    subjects = (
        *SUBJECTS,
        "The delivery driver left my parcel in the recycling bin without ringing at all.",
    )
    config = windowed(tmp_path, subjects=subjects)
    goldens = goldens_yaml(["Nothing like any of this traffic whatsoever."], tmp_path / "g.yaml")
    first = health_report(config, window="w", goldens_path=goldens)
    second = health_report(config, window="w", goldens_path=goldens)
    sizes = [entry.size for entry in first.recommendations]
    assert sizes == sorted(sizes, reverse=True)
    assert [entry.cluster_id for entry in first.recommendations] == [
        entry.cluster_id for entry in second.recommendations
    ]


def test_the_recommendation_list_is_capped(tmp_path):
    config = load_test_config(tmp_path, [("max_recommendations = 10", "max_recommendations = 2")])
    windowed(tmp_path)
    goldens = goldens_yaml(["Nothing like this traffic."], tmp_path / "g.yaml")
    outcome = health_report(config, window="w", goldens_path=goldens)
    assert len(outcome.recommendations) == 2
    assert outcome.uncovered_clusters > 2


def test_a_signal_present_in_the_traffic_and_absent_from_the_dataset_is_a_gap(tmp_path):
    config = windowed(tmp_path)
    goldens = goldens_yaml(["Nothing like this traffic."], tmp_path / "g.yaml")
    outcome = health_report(config, window="w", goldens_path=goldens)
    gaps = {entry.signal: entry for entry in outcome.signal_coverage if entry.records}
    assert "negative_feedback" in gaps
    assert gaps["negative_feedback"].covered_records == 0


def test_every_signal_has_a_row_even_the_ones_that_never_fired(tmp_path):
    """A missing row reads as 'we did not look'."""
    from loghog.score.settings import SIGNAL_NAMES

    config = windowed(tmp_path)
    goldens = goldens_yaml(SUBJECTS, tmp_path / "g.yaml")
    outcome = health_report(config, window="w", goldens_path=goldens)
    assert [entry.signal for entry in outcome.signal_coverage] == list(SIGNAL_NAMES)


# --- the comparison ---------------------------------------------------------


def test_the_interesting_traffic_is_compared_with_the_ordinary_traffic(tmp_path):
    config = windowed(tmp_path)
    goldens = goldens_yaml(SUBJECTS[:1], tmp_path / "g.yaml")
    outcome = health_report(config, window="w", goldens_path=goldens)
    comparison = outcome.comparison
    assert comparison.p_value == fisher_exact_one_sided(
        comparison.ordinary_covered,
        comparison.ordinary_total,
        comparison.signalled_covered,
        comparison.signalled_total,
    )
    assert 0.0 <= comparison.p_value <= 1.0


# --- redundancy -------------------------------------------------------------


def test_two_cases_that_are_near_duplicates_of_each_other_are_named(tmp_path):
    config = windowed(tmp_path)
    goldens = goldens_yaml(
        [SUBJECTS[0], SUBJECTS[0] + " at all", SUBJECTS[2]], tmp_path / "g.yaml"
    )
    outcome = health_report(config, window="w", goldens_path=goldens)
    assert outcome.redundant
    pair = outcome.redundant[0]
    assert {pair.left, pair.right} == {"case_0", "case_1"}
    assert pair.jaccard >= config.health.neighbour_jaccard


# --- the files --------------------------------------------------------------


def test_it_writes_a_report_and_a_json_document(tmp_path):
    config = windowed(tmp_path)
    goldens = goldens_yaml(SUBJECTS, tmp_path / "g.yaml")
    outcome = health_report(config, window="w", goldens_path=goldens)
    assert outcome.markdown_path == markdown_path_for(config, "w")
    assert outcome.json_path == json_path_for(config, "w")
    payload = json.loads(outcome.json_path.read_text(encoding="utf-8"))
    assert payload["coverage"]["share"] == 1.0
    assert payload["window"] == "w"
    assert payload["goldens_sha256"]
    report = outcome.markdown_path.read_text(encoding="utf-8")
    assert "## Coverage" in report
    assert "## Staleness" in report
    assert "## What to mine next" in report


def test_neither_file_quotes_the_traffic_or_the_dataset(tmp_path):
    config = windowed(tmp_path)
    goldens = goldens_yaml(SUBJECTS, tmp_path / "g.yaml")
    outcome = health_report(config, window="w", goldens_path=goldens)
    for path in (outcome.markdown_path, outcome.json_path):
        text = path.read_text(encoding="utf-8")
        for leaked in ("recycling bin", "kettle", "warranty card", "landscape"):
            assert leaked not in text


def test_a_second_run_writes_identical_bytes(tmp_path):
    config = windowed(tmp_path)
    goldens = goldens_yaml(SUBJECTS, tmp_path / "g.yaml")
    first = health_report(config, window="w", goldens_path=goldens)
    before = first.json_path.read_bytes()
    health_report(config, window="w", goldens_path=goldens)
    assert first.json_path.read_bytes() == before


# --- refusals ---------------------------------------------------------------


def test_a_missing_goldens_file_is_refused(tmp_path):
    config = windowed(tmp_path)
    with pytest.raises(HealthError):
        health_report(config, window="w", goldens_path=tmp_path / "nope.yaml")


def test_a_goldens_file_project_one_cannot_read_is_refused_with_its_own_error(tmp_path):
    config = windowed(tmp_path)
    broken = tmp_path / "broken.yaml"
    broken.write_text("- id: NOT-SNAKE\n  tags: []\n  input: x\n  criteria: [y]\n")
    with pytest.raises(HealthError) as excinfo:
        health_report(config, window="w", goldens_path=broken)
    assert "snake_case" in str(excinfo.value)


def test_an_unclustered_window_is_refused_by_name(tmp_path):
    config = load_test_config(tmp_path)
    goldens = goldens_yaml(SUBJECTS, tmp_path / "g.yaml")
    with pytest.raises(HealthError) as excinfo:
        health_report(config, window="never", goldens_path=goldens)
    assert "loghog ingest" in str(excinfo.value)


# --- the circularity ---------------------------------------------------------


def test_novelty_is_excluded_from_the_interesting_versus_ordinary_split(tmp_path):
    """`novelty` is a fact about the dataset, not about the traffic.

    A window scored with `--existing` fires `novelty` on almost every record
    that the dataset does not already hold — which is, by construction, almost
    exactly the set of clusters this report is about to call uncovered. Counting
    it as a signal would make the comparison read "clusters the dataset does not
    cover are covered less often than clusters it does", which is true of every
    dataset ever built and says nothing about any of them.

    So the split is over the twelve signals that are properties of the traffic,
    and this test is the one that fails if the thirteenth creeps back in.
    """
    config = windowed(tmp_path)
    goldens = goldens_yaml([SUBJECTS[0]], tmp_path / "g.yaml")
    scored_plain = health_report(config, window="w", goldens_path=goldens).comparison

    # Re-score the window against the goldens, which is what makes novelty fire.
    from loghog.cli_common import load_existing_inputs

    score_window(config, window="w", golden_inputs=load_existing_inputs(goldens))
    scored_against = health_report(config, window="w", goldens_path=goldens).comparison

    signals = read_signals_for(config, "w")
    assert any("novelty" in names for names in signals.values()), "novelty did not fire"
    assert scored_against.signalled_total == scored_plain.signalled_total
    assert scored_against.ordinary_total == scored_plain.ordinary_total
    assert scored_against.ordinary_total > 0


def read_signals_for(config, window):
    from loghog.window.artifacts import read_signals
    from loghog.window.store import WindowStore

    return read_signals(WindowStore(config.records_dir / window))
