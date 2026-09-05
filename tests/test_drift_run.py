"""Comparing two windows: what changed, and how sure the numbers are.

Four questions, and every one of them is a number rather than a feeling: which
signals fire more often now, what fraction of today's subjects the older window
had never seen, whether inputs got longer, and whether the error and negative
feedback rates moved by more than their own intervals.

The report holds no text from either window. It names cluster ids, counts,
rates and a statistic — which is all a person needs to decide whether to mine
again, and none of what a person would have to be careful with.
"""

import json

import pytest

from conftest import load_test_config, write_jsonl
from loghog.cluster.window import cluster_window
from loghog.drift.run import drift_report
from loghog.errors import DriftError
from loghog.ingest.run import ingest
from loghog.score.run import score_window
from loghog.select.run import select_candidates


def chat(record_id: str, text: str, *, error: bool = False, feedback: str | None = None) -> dict:
    messages = [{"role": "user", "content": text}]
    row = {"id": record_id, "created": 1_788_000_000, "messages": messages, "latency_ms": 300}
    if error:
        row["error"] = "ProviderTransientError"
    else:
        messages.append({"role": "assistant", "content": f"A summary of: {text}"})
    if feedback is not None:
        row["feedback"] = feedback
    return row


OLD = [
    chat("a-1", "The desk lamp flickers whenever the brightness is above about half"),
    chat("a-2", "The courier never rang the bell and took the parcel away again"),
    chat("a-3", "My invoice shows a duplicate charge for the very same order"),
    chat("a-4", "The mobile application crashes whenever i open the settings screen"),
]
NEW = [
    chat("b-1", "The desk lamp flickers whenever the brightness is above about half"),
    chat("b-2", "The courier never rang the bell and took the parcel away again",
         error=True),
    chat("b-3", "The subscription renewed although i cancelled it last month entirely",
         feedback="down"),
    chat("b-4", "The tracking page has said out for delivery since last Wednesday",
         error=True),
]


def prepared(tmp_path, *, rows_a=None, rows_b=None):
    config = load_test_config(tmp_path)
    for window, rows in (("old", rows_a or OLD), ("new", rows_b or NEW)):
        source = tmp_path / f"{window}.jsonl"
        write_jsonl(source, rows)
        ingest(
            config, input_path=source, source_format="jsonl",
            mapping_reference="openai_chat_jsonl", window=window,
        )
        score_window(config, window=window)
        cluster_window(config, window=window)
    return config


def report_of(tmp_path, **overrides):
    config = prepared(tmp_path, **overrides)
    return config, drift_report(config, earlier="old", later="new")


def test_the_report_is_written_as_markdown_and_json_named_for_both_windows(tmp_path):
    config, outcome = report_of(tmp_path)
    assert (config.drift_dir / "old-vs-new.md").is_file()
    assert (config.drift_dir / "old-vs-new.json").is_file()
    assert outcome.markdown_path.name == "old-vs-new.md"


def test_the_json_carries_every_section_the_markdown_does(tmp_path):
    config, _ = report_of(tmp_path)
    payload = json.loads((config.drift_dir / "old-vs-new.json").read_text(encoding="utf-8"))
    assert sorted(payload) == [
        "cluster_novelty", "earlier", "input_length", "later", "loghog_version",
        "rates", "schema_version", "signal_rates", "synthetic",
    ]


def test_signal_rates_move_with_the_traffic(tmp_path):
    _, outcome = report_of(tmp_path)
    error = outcome.signal_rates["error"]
    assert error.earlier_rate == 0.0
    assert error.later_rate == pytest.approx(0.5)
    assert error.delta > 0


def test_every_signal_appears_even_when_it_never_fired(tmp_path):
    # A signal missing from the table reads as "we did not look", and looking
    # and finding nothing is the more common and more useful answer.
    from loghog.score.settings import SIGNAL_NAMES

    _, outcome = report_of(tmp_path)
    assert sorted(outcome.signal_rates) == sorted(SIGNAL_NAMES)


def test_cluster_novelty_finds_the_subjects_the_older_window_never_saw(tmp_path):
    _, outcome = report_of(tmp_path)
    # b-1 and b-2 repeat old subjects; b-3 and b-4 are new.
    assert outcome.novelty.new_clusters == 2
    assert outcome.novelty.total_clusters == 4
    assert outcome.novelty.share == pytest.approx(0.5)


def test_the_new_clusters_are_listed_biggest_first_by_id(tmp_path):
    _, outcome = report_of(tmp_path)
    sizes = [entry.size for entry in outcome.novelty.entries]
    assert sizes == sorted(sizes, reverse=True)


def test_two_identical_windows_have_no_novelty_and_no_length_shift(tmp_path):
    _, outcome = report_of(tmp_path, rows_b=[chat(f"b-{i}", row["messages"][0]["content"])
                                             for i, row in enumerate(OLD, start=1)])
    assert outcome.novelty.new_clusters == 0
    assert outcome.input_length.ks_statistic == pytest.approx(0.0)


def test_the_length_shift_is_a_ks_statistic_over_input_lengths(tmp_path):
    long_rows = [chat(f"b-{i}", "a much longer complaint about something " * 6 + str(i))
                 for i in range(4)]
    _, outcome = report_of(tmp_path, rows_b=long_rows)
    assert outcome.input_length.ks_statistic == pytest.approx(1.0)
    assert outcome.input_length.later_median > outcome.input_length.earlier_median


def test_the_error_rate_comparison_carries_wilson_intervals(tmp_path):
    _, outcome = report_of(tmp_path)
    rates = outcome.rates["error"]
    assert rates.earlier_low <= rates.earlier_rate <= rates.earlier_high
    assert rates.later_rate == pytest.approx(0.5)


def test_the_negative_feedback_rate_is_compared_too(tmp_path):
    _, outcome = report_of(tmp_path)
    assert outcome.rates["negative_feedback"].later_rate == pytest.approx(0.25)


def test_a_small_sample_gives_a_wide_interval_rather_than_a_confident_number(tmp_path):
    _, outcome = report_of(tmp_path)
    rates = outcome.rates["error"]
    assert rates.later_high - rates.later_low > 0.3


def test_the_report_quotes_no_text_from_either_window(tmp_path):
    config, _ = report_of(tmp_path)
    markdown = (config.drift_dir / "old-vs-new.md").read_text(encoding="utf-8")
    for fragment in ("lamp", "courier", "invoice", "subscription", "tracking"):
        assert fragment not in markdown


def test_running_it_twice_writes_the_same_bytes(tmp_path):
    config, _ = report_of(tmp_path)
    path = config.drift_dir / "old-vs-new.md"
    first = path.read_text(encoding="utf-8")
    drift_report(config, earlier="old", later="new")
    assert path.read_text(encoding="utf-8") == first


def test_comparing_a_window_to_itself_is_refused(tmp_path):
    config = prepared(tmp_path)
    with pytest.raises(DriftError, match="itself"):
        drift_report(config, earlier="old", later="old")


def test_an_unscored_window_is_refused_with_the_command_that_fixes_it(tmp_path):
    config = load_test_config(tmp_path)
    for window in ("old", "new"):
        source = tmp_path / f"{window}.jsonl"
        write_jsonl(source, OLD if window == "old" else NEW)
        ingest(config, input_path=source, source_format="jsonl",
               mapping_reference="openai_chat_jsonl", window=window)
    with pytest.raises(DriftError, match="loghog score"):
        drift_report(config, earlier="old", later="new")


def test_an_unclustered_window_is_refused_with_the_command_that_fixes_it(tmp_path):
    config = load_test_config(tmp_path)
    for window in ("old", "new"):
        source = tmp_path / f"{window}.jsonl"
        write_jsonl(source, OLD if window == "old" else NEW)
        ingest(config, input_path=source, source_format="jsonl",
               mapping_reference="openai_chat_jsonl", window=window)
        score_window(config, window=window)
    with pytest.raises(DriftError, match="loghog cluster"):
        drift_report(config, earlier="old", later="new")


def test_a_missing_window_is_refused_by_name(tmp_path):
    config = prepared(tmp_path)
    with pytest.raises(DriftError, match="nowhere"):
        drift_report(config, earlier="old", later="nowhere")


def test_drift_does_not_need_a_selection_to_have_been_run(tmp_path):
    # Drift is about the traffic, not about the dataset. Requiring a shortlist
    # first would make it impossible to ask "has anything changed?" before
    # deciding whether to mine at all.
    config = prepared(tmp_path)
    assert drift_report(config, earlier="old", later="new").novelty.total_clusters == 4
    assert not (config.selected_dir / "new").exists()
    select_candidates(config, window="new")
