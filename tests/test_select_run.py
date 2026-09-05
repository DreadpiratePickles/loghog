"""Stage 05: the shortlist, and the accounting for everything that did not make it.

The rule this stage lives by is that **no cap is silent**. Every record that was
not chosen was refused by exactly one named cap — a cluster already full, a
stratum quota already met, an existing golden case, or the global limit — and
`selection.md` gives the count for each. A shortlist whose omissions are
unexplained is a shortlist nobody can trust to be representative, which is the
one property it is supposed to have.
"""

import json
import re

import pytest

from conftest import load_test_config, write_jsonl
from loghog.cluster.window import cluster_window
from loghog.config_file import load_config
from loghog.errors import SelectionError
from loghog.ingest.run import ingest
from loghog.score.run import score_window
from loghog.select.run import EXIT_NOTHING, EXIT_OK, EXIT_TRUNCATED, select_candidates

FLICKER = "The desk lamp flickers whenever the brightness is above about half"


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


def prepared(tmp_path, rows, *, substitutions=(), window="w"):
    config = load_test_config(tmp_path, substitutions)
    source = tmp_path / f"{window}.jsonl"
    write_jsonl(source, rows)
    ingest(
        config, input_path=source, source_format="jsonl",
        mapping_reference="openai_chat_jsonl", window=window,
    )
    score_window(config, window=window)
    cluster_window(config, window=window)
    return config


def outcome_for(tmp_path, rows, *, substitutions=(), **overrides):
    config = prepared(tmp_path, rows, substitutions=substitutions)
    return config, select_candidates(config, window="w", **overrides)


DISTINCT = [
    chat("r-1", "The desk lamp flickers whenever the brightness is above about half"),
    chat("r-2", "The courier never rang the bell and took the parcel away again",
         error=True),
    chat("r-3", "My invoice shows a duplicate charge for the very same order",
         feedback="down"),
    chat("r-4", "The mobile application crashes whenever i open the settings screen"),
]


def test_a_candidate_line_carries_the_case_and_the_reasons(tmp_path):
    config, outcome = outcome_for(tmp_path, DISTINCT)
    path = config.selected_dir / "w" / "candidates.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == outcome.selected_count
    first = rows[0]
    assert sorted(first) == [
        "cluster_id", "cluster_size", "input_text", "output_text", "rank",
        "reasons", "record_id", "score", "stratum",
    ]
    assert first["rank"] == 1


def test_candidates_are_ordered_by_score_then_by_record_id(tmp_path):
    _, outcome = outcome_for(tmp_path, DISTINCT)
    scores = [(-entry.score, entry.record_id) for entry in outcome.selected]
    assert scores == sorted(scores)


def test_the_stratum_is_the_highest_weighted_signal_that_fired(tmp_path):
    _, outcome = outcome_for(tmp_path, DISTINCT)
    by_id = {entry.record_id: entry for entry in outcome.selected}
    assert by_id["r-2"].stratum == "error"
    assert by_id["r-3"].stratum == "negative_feedback"


def test_a_record_that_fired_nothing_lands_in_ordinary(tmp_path):
    _, outcome = outcome_for(tmp_path, DISTINCT)
    by_id = {entry.record_id: entry for entry in outcome.selected}
    assert by_id["r-1"].stratum == "ordinary"


def test_only_one_record_per_cluster_is_taken(tmp_path):
    rows = [
        chat("r-1", f"{FLICKER} and it is annoying"),
        chat("r-2", f"{FLICKER} and it is very annoying"),
        chat("r-3", "The courier never rang the bell and took the parcel away again"),
    ]
    _, outcome = outcome_for(tmp_path, rows)
    clusters = [entry.cluster_id for entry in outcome.selected]
    assert len(clusters) == len(set(clusters))
    assert outcome.dropped["cluster_cap"] == 1


def test_the_record_kept_from_a_cluster_is_the_highest_scoring_one(tmp_path):
    rows = [
        chat("r-1", f"{FLICKER} and it is annoying"),
        chat("r-2", f"{FLICKER} and it is very annoying", error=True),
    ]
    _, outcome = outcome_for(tmp_path, rows)
    assert [entry.record_id for entry in outcome.selected] == ["r-2"]


def test_a_larger_cluster_cap_takes_more_of_one_cluster(tmp_path):
    rows = [
        chat("r-1", f"{FLICKER} and it is annoying"),
        chat("r-2", f"{FLICKER} and it is very annoying"),
    ]
    _, outcome = outcome_for(
        tmp_path, rows, substitutions=[("max_per_cluster = 1", "max_per_cluster = 2")]
    )
    assert outcome.selected_count == 2
    assert outcome.dropped.get("cluster_cap", 0) == 0


def test_a_full_quota_stops_a_stratum_and_the_drop_is_named(tmp_path):
    rows = [
        chat("r-1", "The courier never rang the bell and took the parcel away again",
             error=True),
        chat("r-2", "My invoice shows a duplicate charge for the very same order",
             error=True),
    ]
    _, outcome = outcome_for(
        tmp_path, rows, substitutions=[("error = 6\njudge_failure", "error = 1\njudge_failure")]
    )
    assert outcome.selected_count == 1
    assert outcome.dropped["quota:error"] == 1


def test_an_unfilled_stratum_is_reported_and_never_topped_up(tmp_path):
    _, outcome = outcome_for(tmp_path, DISTINCT)
    unfilled = dict(outcome.unfilled)
    assert unfilled["injection_pattern"] > 0
    assert outcome.selected_count <= sum(entry.quota for entry in outcome.strata)


def test_the_global_cap_truncates_and_says_so(tmp_path):
    _, outcome = outcome_for(tmp_path, DISTINCT, max_candidates=2)
    assert outcome.selected_count == 2
    assert outcome.dropped["max_candidates"] == 2
    assert outcome.exit_code == EXIT_TRUNCATED


def test_a_shortlist_that_fits_exits_zero(tmp_path):
    _, outcome = outcome_for(tmp_path, DISTINCT)
    assert outcome.exit_code == EXIT_OK


def test_a_command_line_cap_of_zero_is_refused(tmp_path):
    config = prepared(tmp_path, DISTINCT)
    with pytest.raises(SelectionError, match="at least 1"):
        select_candidates(config, window="w", max_candidates=0)


def test_a_case_the_goldens_already_hold_is_suppressed(tmp_path):
    _, outcome = outcome_for(
        tmp_path, DISTINCT, golden_inputs=[DISTINCT[0]["messages"][0]["content"]]
    )
    assert "r-1" not in {entry.record_id for entry in outcome.selected}
    assert outcome.dropped["already_in_goldens"] == 1


def test_suppression_does_not_spend_a_quota(tmp_path):
    # A case already in the goldens must not consume the slot a new one needed.
    config = prepared(tmp_path, DISTINCT)
    plain = select_candidates(config, window="w")
    suppressed = select_candidates(
        config, window="w", golden_inputs=[DISTINCT[1]["messages"][0]["content"]]
    )
    assert suppressed.selected_count == plain.selected_count - 1


def test_selecting_from_a_window_with_no_clusters_is_refused(tmp_path):
    config = load_test_config(tmp_path)
    source = tmp_path / "w.jsonl"
    write_jsonl(source, DISTINCT)
    ingest(config, input_path=source, source_format="jsonl",
           mapping_reference="openai_chat_jsonl", window="w")
    score_window(config, window="w")
    with pytest.raises(SelectionError, match="loghog cluster"):
        select_candidates(config, window="w")


def test_a_window_where_every_quota_is_zero_selects_nothing_and_exits_two(tmp_path):
    # Every stratum excluded is a legitimate configuration and an empty
    # shortlist is not a shortlist, so it exits 2 rather than pretending.
    outcome = select_candidates(_with_zero_quotas(prepared(tmp_path, DISTINCT)), window="w")
    assert outcome.selected_count == 0
    assert outcome.exit_code == EXIT_NOTHING


def test_the_summary_names_every_cap_and_its_count(tmp_path):
    config, _ = outcome_for(tmp_path, DISTINCT, max_candidates=2)
    report = (config.selected_dir / "w" / "selection.md").read_text(encoding="utf-8")
    assert "## What was dropped, and by which cap" in report
    assert "max_candidates" in report
    assert "## Strata" in report


def test_the_summary_names_the_unfilled_strata(tmp_path):
    config, _ = outcome_for(tmp_path, DISTINCT)
    report = (config.selected_dir / "w" / "selection.md").read_text(encoding="utf-8")
    assert "injection_pattern" in report


def test_the_summary_quotes_no_case_text(tmp_path):
    # `candidates.jsonl` holds the redacted case, because stage 06 needs it.
    # `selection.md` is the file people paste into tickets, and it holds none.
    config, _ = outcome_for(tmp_path, DISTINCT)
    report = (config.selected_dir / "w" / "selection.md").read_text(encoding="utf-8")
    for fragment in ("lamp", "courier", "invoice", "flickers"):
        assert fragment not in report


def test_selecting_twice_writes_the_same_shortlist(tmp_path):
    config, _ = outcome_for(tmp_path, DISTINCT)
    path = config.selected_dir / "w" / "candidates.jsonl"
    first = path.read_text(encoding="utf-8")
    select_candidates(config, window="w")
    assert path.read_text(encoding="utf-8") == first


def test_the_candidates_file_is_written_at_the_records_permissions(tmp_path):
    config, _ = outcome_for(tmp_path, DISTINCT)
    path = config.selected_dir / "w" / "candidates.jsonl"
    assert path.stat().st_mode & 0o777 == 0o600


def _with_zero_quotas(config):
    """Zero every quota, and nothing outside `[select.quotas]`.

    The table is bounded by the next section header rather than by the end of
    the file: an unbounded substitution would also zero the integers in the
    sections that follow, and `[label] max_calls = 0` is refused — so the test
    would fail for a reason that has nothing to do with quotas.
    """
    head, quotas = config.path.read_text(encoding="utf-8").split("[select.quotas]", 1)
    table, marker, tail = quotas.partition("\n[")
    table = re.sub(r"^([a-z_]+) = \d+$", r"\1 = 0", table, flags=re.MULTILINE)
    config.path.write_text(
        head + "[select.quotas]" + table + marker + tail, encoding="utf-8"
    )
    return load_config(config.path)
