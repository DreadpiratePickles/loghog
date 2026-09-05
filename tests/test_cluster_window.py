"""Stage 04 against a real window: read, partition, write `clusters.json`.

The sample log contains one complaint written twice, word for word, and stage 01
already removed the exact duplicate. What is left for this stage in the sample
is mostly singletons — which is the honest result, and the report says so rather
than quietly presenting thirteen clusters of one as a finding.
"""

import json

import pytest

from conftest import SAMPLES_DIR, load_test_config, write_jsonl
from loghog.cluster.window import cluster_window
from loghog.errors import ClusterError, ScoreError
from loghog.ingest.run import ingest
from loghog.score.run import score_window
from loghog.window.artifacts import read_clusters
from loghog.window.store import WindowStore

SAMPLE = SAMPLES_DIR / "support_chat.synthetic.jsonl"


def prepared(tmp_path, *, score=True):
    config = load_test_config(tmp_path)
    ingest(
        config,
        input_path=SAMPLE,
        source_format="jsonl",
        mapping_reference="openai_chat_jsonl",
        window="demo",
        synthetic=True,
    )
    if score:
        score_window(config, window="demo")
    return config


def test_clustering_writes_a_document_naming_every_record(tmp_path):
    config = prepared(tmp_path)
    outcome = cluster_window(config, window="demo")
    store = WindowStore(config.records_dir / "demo")
    payload = read_clusters(store)
    members = [m for cluster in payload["clusters"] for m in cluster["member_ids"]]
    assert sorted(members) == sorted(r.record_id for r in store.read_records())
    assert len(payload["clusters"]) == len(outcome.clusters)


def test_the_document_states_the_parameters_it_used(tmp_path):
    config = prepared(tmp_path)
    cluster_window(config, window="demo")
    payload = read_clusters(WindowStore(config.records_dir / "demo"))
    assert payload["params"]["jaccard_threshold"] == config.cluster.threshold
    assert payload["params"]["seed"] == config.cluster.seed
    assert payload["params"]["rows_per_band"] == 4


def test_clustering_twice_writes_the_same_bytes(tmp_path):
    config = prepared(tmp_path)
    cluster_window(config, window="demo")
    path = WindowStore(config.records_dir / "demo").clusters_path
    first = path.read_text(encoding="utf-8")
    cluster_window(config, window="demo")
    assert path.read_text(encoding="utf-8") == first


def test_the_representative_is_the_highest_scoring_member(tmp_path):
    config = load_test_config(tmp_path)
    source = tmp_path / "pairs.jsonl"
    write_jsonl(
        source,
        [
            _chat("a", "The desk lamp flickers whenever the brightness is above half."),
            _chat(
                "b",
                "The desk lamp flickers whenever the brightness is above about half.",
                error=True,
            ),
        ],
    )
    ingest(
        config, input_path=source, source_format="jsonl",
        mapping_reference="openai_chat_jsonl", window="pairs",
    )
    score_window(config, window="pairs")
    outcome = cluster_window(config, window="pairs")
    # `b` failed, so it scores higher, so it speaks for the pair.
    assert outcome.clusters[0].representative_id == "b"


def test_clustering_an_unscored_window_is_refused_with_the_command(tmp_path):
    config = prepared(tmp_path, score=False)
    with pytest.raises(ScoreError, match="loghog score"):
        cluster_window(config, window="demo")


def test_clustering_a_window_that_does_not_exist_is_refused(tmp_path):
    config = load_test_config(tmp_path)
    with pytest.raises(ClusterError, match="loghog ingest"):
        cluster_window(config, window="nothing-here")


def test_the_report_says_when_every_cluster_is_a_singleton(tmp_path):
    config = prepared(tmp_path)
    cluster_window(config, window="demo")
    report = (config.records_dir / "demo" / "cluster.md").read_text(encoding="utf-8")
    assert "singleton" in report


def test_the_report_warns_when_one_cluster_swallowed_the_window(tmp_path):
    # A single cluster over a whole window means the threshold is wrong, and a
    # stage that quietly selected one case out of it would hide that.
    config = load_test_config(tmp_path, [("jaccard_threshold = 0.6", "jaccard_threshold = 0.01")])
    source = tmp_path / "same.jsonl"
    write_jsonl(source, [_chat(f"r-{i}", f"the lamp flickers above half brightness {i}")
                         for i in range(4)])
    ingest(config, input_path=source, source_format="jsonl",
           mapping_reference="openai_chat_jsonl", window="same")
    score_window(config, window="same")
    cluster_window(config, window="same")
    report = (config.records_dir / "same" / "cluster.md").read_text(encoding="utf-8")
    assert "one cluster" in report


def test_the_report_quotes_no_record_text(tmp_path):
    config = prepared(tmp_path)
    cluster_window(config, window="demo")
    report = (config.records_dir / "demo" / "cluster.md").read_text(encoding="utf-8")
    for fragment in ("lamp", "flickers", "Dr Pepper", "refund"):
        assert fragment not in report


def test_the_clusters_file_has_the_windows_permissions(tmp_path):
    config = prepared(tmp_path)
    cluster_window(config, window="demo")
    path = WindowStore(config.records_dir / "demo").clusters_path
    assert path.stat().st_mode & 0o777 == 0o600


def test_the_document_is_valid_json_with_sorted_keys(tmp_path):
    config = prepared(tmp_path)
    cluster_window(config, window="demo")
    raw = WindowStore(config.records_dir / "demo").clusters_path.read_text(encoding="utf-8")
    payload = json.loads(raw)
    assert list(payload) == sorted(payload)


def _chat(record_id: str, text: str, *, error: bool = False) -> dict:
    messages = [{"role": "user", "content": text}]
    row = {
        "id": record_id,
        "created": 1_788_000_000,
        "messages": messages,
        "latency_ms": 300,
    }
    if error:
        row["error"] = "ProviderTransientError"
    else:
        messages.append({"role": "assistant", "content": f"A summary of: {text}"})
    return row
