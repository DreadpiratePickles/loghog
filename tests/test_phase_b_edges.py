"""The refusals in the Phase B stages that only a broken window can reach.

Every one of these is a message an operator would see exactly once, at the worst
moment, and each names the command that fixes it. They are tested because a
message nobody has ever read is a message nobody has ever checked — and the
half of this repository that is worth anything is the half that fails clearly.
"""

import json

import pytest

from conftest import SAMPLES_DIR, load_test_config, write_jsonl
from loghog.cluster.window import cluster_window
from loghog.config_file import load_config
from loghog.drift.run import drift_report
from loghog.drift.settings import DriftSettings
from loghog.errors import ClusterError, ConfigFileError, DriftError, ScoreError, SelectionError
from loghog.ingest.run import ingest
from loghog.score.run import score_window
from loghog.score.settings import SIGNAL_NAMES
from loghog.select.run import select_candidates, stratum_for
from loghog.window.artifacts import write_json
from loghog.window.artifacts import write_jsonl as write_rows
from loghog.window.store import WindowStore

ROWS = [
    {
        "id": f"r-{index}",
        "created": 1_788_000_000 + index,
        "messages": [
            {"role": "user", "content": text},
            {"role": "assistant", "content": f"A summary of: {text}"},
        ],
        "latency_ms": 300,
    }
    for index, text in enumerate(
        [
            "The desk lamp flickers whenever the brightness is above about half",
            "The courier never rang the bell and took the parcel away again",
        ],
        start=1,
    )
]


def prepared(tmp_path, *, window="w", score=True, cluster=True):
    config = load_test_config(tmp_path)
    source = tmp_path / f"{window}.jsonl"
    write_jsonl(source, ROWS)
    ingest(
        config, input_path=source, source_format="jsonl",
        mapping_reference="openai_chat_jsonl", window=window,
    )
    if score:
        score_window(config, window=window)
    if cluster:
        cluster_window(config, window=window)
    return config


# --- settings accessors -----------------------------------------------------


def test_asking_for_the_weight_of_an_unknown_signal_is_refused(tmp_path):
    with pytest.raises(ConfigFileError, match="no weight configured"):
        load_test_config(tmp_path).score.weight("telepathy")


def test_asking_for_the_quota_of_an_unknown_stratum_is_refused(tmp_path):
    with pytest.raises(ConfigFileError, match="no quota configured"):
        load_test_config(tmp_path).select.quota("telepathy")


def test_the_settings_render_themselves_for_a_report(tmp_path):
    config = load_test_config(tmp_path)
    assert sorted(config.score.to_json_dict()["weights"]) == sorted(SIGNAL_NAMES)
    assert config.select.to_json_dict()["max_per_cluster"] == config.select.max_per_cluster
    assert DriftSettings(novel_cluster_jaccard=0.4).to_json_dict() == {
        "novel_cluster_jaccard": 0.4
    }


def test_a_missing_weights_table_is_refused(tmp_path):
    path = tmp_path / "loghog.toml"
    text = load_test_config(tmp_path).path.read_text(encoding="utf-8")
    head, _ = text.split("[score.weights]", 1)
    rest = text.split("[cluster]", 1)[1]
    path.write_text(head + "[cluster]" + rest, encoding="utf-8")
    with pytest.raises(ConfigFileError, match=r"\[score.weights\] is missing"):
        load_config(path)


def test_a_missing_quotas_table_is_refused(tmp_path):
    path = tmp_path / "loghog.toml"
    text = load_test_config(tmp_path).path.read_text(encoding="utf-8")
    head, _ = text.split("[select.quotas]", 1)
    rest = text.split("[drift]", 1)[1]
    path.write_text(head + "[drift]" + rest, encoding="utf-8")
    with pytest.raises(ConfigFileError, match=r"\[select.quotas\] is missing"):
        load_config(path)


# --- strata -----------------------------------------------------------------


def test_a_signal_name_the_registry_does_not_know_falls_back_to_ordinary(tmp_path):
    # A scores file written by a later build could name a signal this one has
    # never heard of. Guessing a stratum for it would put a record in a quota
    # nobody configured; `ordinary` is the honest place for it.
    config = load_test_config(tmp_path)
    assert stratum_for(("telepathy",), config) == "ordinary"
    assert stratum_for((), config) == "ordinary"


# --- broken windows ---------------------------------------------------------


def test_scoring_a_window_whose_records_file_is_empty_is_refused(tmp_path):
    config = prepared(tmp_path, score=False, cluster=False)
    WindowStore(config.records_dir / "w").records_path.write_text("", encoding="utf-8")
    with pytest.raises(ScoreError, match="no records"):
        score_window(config, window="w")


def test_clustering_a_window_whose_records_file_is_empty_is_refused(tmp_path):
    config = prepared(tmp_path, score=False, cluster=False)
    WindowStore(config.records_dir / "w").records_path.write_text("", encoding="utf-8")
    with pytest.raises(ClusterError, match="no records"):
        cluster_window(config, window="w")


def test_selecting_from_a_window_whose_records_file_is_empty_is_refused(tmp_path):
    config = prepared(tmp_path)
    WindowStore(config.records_dir / "w").records_path.write_text("", encoding="utf-8")
    with pytest.raises(SelectionError, match="loghog ingest"):
        select_candidates(config, window="w")


def test_a_scores_file_naming_a_record_the_window_does_not_hold_is_refused(tmp_path):
    config = prepared(tmp_path)
    store = WindowStore(config.records_dir / "w")
    write_rows(store.scores_path, [{"record_id": "ghost", "score": 1, "signals": []}])
    with pytest.raises(SelectionError, match="not in this window"):
        select_candidates(config, window="w")


def test_a_record_with_no_score_is_refused_rather_than_scored_zero(tmp_path):
    config = prepared(tmp_path)
    store = WindowStore(config.records_dir / "w")
    rows = [json.loads(line) for line in store.scores_path.read_text().splitlines()]
    write_rows(store.scores_path, rows[:1])
    with pytest.raises(SelectionError, match="have no score"):
        select_candidates(config, window="w")


def test_a_record_in_no_cluster_is_refused_rather_than_left_out(tmp_path):
    config = prepared(tmp_path)
    store = WindowStore(config.records_dir / "w")
    payload = json.loads(store.clusters_path.read_text(encoding="utf-8"))
    payload["clusters"] = payload["clusters"][:1]
    write_json(store.clusters_path, payload)
    with pytest.raises(SelectionError, match="in no cluster"):
        select_candidates(config, window="w")


def test_drift_against_a_window_whose_records_file_is_empty_is_refused(tmp_path):
    config = prepared(tmp_path, window="old")
    prepared(tmp_path, window="new")
    WindowStore(config.records_dir / "new").records_path.write_text("", encoding="utf-8")
    with pytest.raises(DriftError, match="no records"):
        drift_report(config, earlier="old", later="new")


def test_drift_over_a_clusters_document_naming_a_missing_representative_is_refused(tmp_path):
    config = prepared(tmp_path, window="old")
    prepared(tmp_path, window="new")
    store = WindowStore(config.records_dir / "new")
    payload = json.loads(store.clusters_path.read_text(encoding="utf-8"))
    payload["clusters"][0]["representative_id"] = "ghost"
    write_json(store.clusters_path, payload)
    with pytest.raises(DriftError, match="does not hold"):
        drift_report(config, earlier="old", later="new")


def test_drift_over_a_broken_clusters_document_is_a_drift_error(tmp_path):
    # Reported as a drift failure rather than as a selection one: the caller
    # asked to compare two windows and needs a message about that.
    config = prepared(tmp_path, window="old")
    prepared(tmp_path, window="new")
    store = WindowStore(config.records_dir / "new")
    store.clusters_path.write_text('{"window": "new"}', encoding="utf-8")
    with pytest.raises(DriftError, match="not a clusters document"):
        drift_report(config, earlier="old", later="new")


# --- reports over unusual windows -------------------------------------------


def test_an_unredacted_window_carries_the_banner_into_the_score_report(tmp_path):
    config = load_test_config(tmp_path, [("redact = true", "redact = false")])
    source = tmp_path / "w.jsonl"
    write_jsonl(source, ROWS)
    ingest(
        config, input_path=source, source_format="jsonl",
        mapping_reference="openai_chat_jsonl", window="w", allow_unredacted=True,
    )
    score_window(config, window="w")
    report = (config.records_dir / "w" / "score.md").read_text(encoding="utf-8")
    assert report.splitlines()[0].startswith("UNREDACTED")


def test_a_window_in_which_nothing_is_interesting_says_so(tmp_path):
    config = prepared(tmp_path, cluster=False)
    report = (config.records_dir / "w" / "score.md").read_text(encoding="utf-8")
    assert "Every record in this window looks ordinary." in report


def test_a_window_with_no_impediments_says_every_signal_had_what_it_needed(tmp_path):
    # It takes all four conditions at once: dedupe off, every source declaring
    # [expect] output_json, a goldens file, and enough records for a p95. The
    # committed judged sample is the one window in this repository that has
    # them, which is most of why it is committed.
    config = load_test_config(tmp_path, [("dedupe = true", "dedupe = false")])
    ingest(
        config, input_path=SAMPLES_DIR / "judged_summaries.synthetic.jsonl",
        source_format="jsonl", mapping_reference=str(SAMPLES_DIR / "judged_summaries.toml"),
        window="judged", synthetic=True,
    )
    outcome = score_window(
        config, window="judged", golden_inputs=["something else entirely about a tax return"]
    )
    assert outcome.context.not_evaluated == ()
    report = (config.records_dir / "judged" / "score.md").read_text(encoding="utf-8")
    assert "Every signal had what it needed." in report


def test_a_window_of_wordless_records_is_reported_as_such(tmp_path):
    config = load_test_config(tmp_path)
    source = tmp_path / "w.jsonl"
    write_jsonl(
        source,
        [
            {
                "id": f"n-{index}",
                "created": 1_788_000_000 + index,
                "messages": [
                    {"role": "user", "content": f"{index}{index}{index} 4242"},
                    {"role": "assistant", "content": "A number."},
                ],
            }
            for index in range(1, 3)
        ],
    )
    ingest(config, input_path=source, source_format="jsonl",
           mapping_reference="openai_chat_jsonl", window="w")
    score_window(config, window="w")
    outcome = cluster_window(config, window="w")
    assert len(outcome.wordless_ids) == 2
    report = (config.records_dir / "w" / "cluster.md").read_text(encoding="utf-8")
    assert "no words left after" in report


def test_the_selection_report_says_when_nothing_was_dropped(tmp_path):
    config = prepared(tmp_path)
    outcome = select_candidates(config, window="w")
    report = (outcome.directory / "selection.md").read_text(encoding="utf-8")
    assert "Nothing. Every scored record in this window is on the shortlist." in report


def test_a_record_that_fired_nothing_records_that_as_its_reason(tmp_path):
    config = prepared(tmp_path)
    outcome = select_candidates(config, window="w")
    assert outcome.selected[0].reasons == ("no signal fired; ordinary traffic",)
