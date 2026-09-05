"""Clustering a window, and measuring the blocking step against brute force.

The last test in this file is the one that matters. LSH trades recall for not
comparing every pair, and a clustering tool that does not measure how much it
traded is a tool making a claim nobody checked. So the suite computes the exact
answer on a synthetic corpus, and asserts precision and recall against it.
"""

import pytest

from conftest import make_record
from loghog.cluster.run import ClusterParams, cluster_records
from loghog.cluster.shingles import jaccard, shingles
from loghog.errors import ClusterError

PARAMS = ClusterParams(shingle_words=3, permutations=64, bands=16, seed=1729, threshold=0.5)


def record(record_id: str, text: str):
    return make_record(record_id=record_id, input_text=text)


def cluster_of(outcome, record_id: str):
    for cluster in outcome.clusters:
        if record_id in cluster.member_ids:
            return cluster
    raise AssertionError(f"{record_id} is in no cluster")


def test_an_empty_window_is_refused():
    with pytest.raises(ClusterError, match="no records"):
        cluster_records([], scores={}, params=PARAMS)


def test_one_record_is_one_cluster_of_one():
    only = [record("a", "the lamp flickers above half")]
    outcome = cluster_records(only, scores={}, params=PARAMS)
    assert len(outcome.clusters) == 1
    assert outcome.clusters[0].member_ids == ("a",)
    assert outcome.clusters[0].representative_id == "a"


def test_every_record_lands_in_exactly_one_cluster():
    records = [record(f"r-{i}", f"complaint number {i} about a different thing") for i in range(6)]
    outcome = cluster_records(records, scores={}, params=PARAMS)
    seen = [member for cluster in outcome.clusters for member in cluster.member_ids]
    assert sorted(seen) == sorted(r.record_id for r in records)
    assert len(seen) == len(set(seen))


def test_paraphrases_of_one_complaint_become_one_cluster():
    texts = [
        "the desk lamp flickers whenever the brightness is above half",
        "the desk lamp flickers whenever the brightness is above about half",
        "the desk lamp flickers whenever brightness is above half",
    ]
    records = [record(f"r-{i}", text) for i, text in enumerate(texts)]
    outcome = cluster_records(records, scores={}, params=PARAMS)
    assert len(outcome.clusters) == 1
    assert outcome.clusters[0].size == 3


def test_two_different_complaints_do_not_merge():
    records = [
        record("a", "the desk lamp flickers whenever the brightness is above half"),
        record("b", "the courier never rang the bell and took the parcel away again"),
    ]
    outcome = cluster_records(records, scores={}, params=PARAMS)
    assert len(outcome.clusters) == 2


def test_the_representative_is_the_highest_scored_member():
    texts = [
        "the desk lamp flickers whenever the brightness is above half",
        "the desk lamp flickers whenever the brightness is above about half",
    ]
    records = [record("low", texts[0]), record("high", texts[1])]
    outcome = cluster_records(records, scores={"low": 1, "high": 9}, params=PARAMS)
    assert outcome.clusters[0].representative_id == "high"


def test_a_tie_on_score_is_broken_by_record_id_so_the_answer_is_stable():
    texts = [
        "the desk lamp flickers whenever the brightness is above half",
        "the desk lamp flickers whenever the brightness is above about half",
    ]
    records = [record("bbb", texts[0]), record("aaa", texts[1])]
    outcome = cluster_records(records, scores={"aaa": 5, "bbb": 5}, params=PARAMS)
    assert outcome.clusters[0].representative_id == "aaa"


def test_a_record_with_no_score_is_treated_as_zero_not_as_missing():
    texts = [
        "the desk lamp flickers whenever the brightness is above half",
        "the desk lamp flickers whenever the brightness is above about half",
    ]
    records = [record("scored", texts[0]), record("unscored", texts[1])]
    outcome = cluster_records(records, scores={"scored": 1}, params=PARAMS)
    assert outcome.clusters[0].representative_id == "scored"


def test_clustering_is_order_independent():
    texts = [
        "the desk lamp flickers whenever the brightness is above half",
        "the desk lamp flickers whenever the brightness is above about half",
        "the courier never rang the bell and took the parcel away again",
        "the courier never rang the bell and took the parcel back again",
    ]
    records = [record(f"r-{i}", text) for i, text in enumerate(texts)]
    forward = cluster_records(records, scores={}, params=PARAMS)
    backward = cluster_records(list(reversed(records)), scores={}, params=PARAMS)
    assert [c.member_ids for c in forward.clusters] == [c.member_ids for c in backward.clusters]


def test_clusters_are_ordered_by_size_then_by_representative():
    texts = {
        "z-1": "the desk lamp flickers whenever the brightness is above half",
        "z-2": "the desk lamp flickers whenever the brightness is above about half",
        "a-1": "the courier never rang the bell and took the parcel away again",
    }
    records = [record(rid, text) for rid, text in texts.items()]
    outcome = cluster_records(records, scores={}, params=PARAMS)
    assert [c.size for c in outcome.clusters] == [2, 1]


def test_cluster_ids_are_assigned_in_that_order_and_are_stable():
    records = [
        record("a", "the desk lamp flickers whenever the brightness is above half"),
        record("b", "the desk lamp flickers whenever the brightness is above about half"),
        record("c", "the courier never rang the bell and took the parcel away again"),
    ]
    outcome = cluster_records(records, scores={}, params=PARAMS)
    assert [c.cluster_id for c in outcome.clusters] == ["c-0001", "c-0002"]


def test_a_record_with_no_words_is_always_a_singleton():
    # Two inputs that normalise to nothing are two absences, not two matches.
    records = [record("a", "1234 5678"), record("b", "9999 0000")]
    outcome = cluster_records(records, scores={}, params=PARAMS)
    assert len(outcome.clusters) == 2
    assert outcome.wordless_ids == ("a", "b")


def test_a_singleton_has_no_link_similarity():
    outcome = cluster_records([record("a", "one lonely complaint about a lamp")], scores={},
                              params=PARAMS)
    assert outcome.clusters[0].min_link_jaccard is None


def test_a_merged_cluster_reports_the_weakest_link_that_built_it():
    records = [
        record("a", "the desk lamp flickers whenever the brightness is above half"),
        record("b", "the desk lamp flickers whenever the brightness is above about half"),
    ]
    outcome = cluster_records(records, scores={}, params=PARAMS)
    similarity = outcome.clusters[0].min_link_jaccard
    assert similarity is not None
    assert similarity >= PARAMS.threshold


def test_a_candidate_pair_below_the_threshold_is_not_merged():
    # LSH proposes; exact Jaccard disposes. Without the verification step a
    # band collision alone would merge two unrelated tickets.
    records = [
        record("a", "alpha beta gamma delta epsilon zeta eta theta"),
        record("b", "alpha beta gamma iota kappa lambda mu nu"),
    ]
    strict = ClusterParams(shingle_words=3, permutations=64, bands=32, seed=1729, threshold=0.95)
    outcome = cluster_records(records, scores={}, params=strict)
    assert len(outcome.clusters) == 2


def test_the_params_are_carried_on_the_outcome_so_a_report_can_state_them():
    outcome = cluster_records([record("a", "a lamp that flickers a lot")], scores={},
                              params=PARAMS)
    assert outcome.params == PARAMS


def test_duplicate_record_ids_are_refused():
    records = [record("a", "one complaint"), record("a", "another complaint")]
    with pytest.raises(ClusterError, match="twice"):
        cluster_records(records, scores={}, params=PARAMS)


# --- the measurement --------------------------------------------------------


def synthetic_corpus() -> list:
    """Ten families of five paraphrases each, plus twenty unrelated singletons."""
    stems = [
        "the desk lamp flickers whenever the brightness goes above",
        "the courier never rang the bell and left with the",
        "my invoice shows a duplicate charge for the same",
        "the mobile application crashes when i open the settings",
        "the export finishes but the downloaded file is completely",
        "nobody has answered my email about the broken replacement",
        "the subscription renewed even though i cancelled it last",
        "the tracking page has said out for delivery since",
        "the promised discount code is rejected at the checkout",
        "the printer refuses to connect to the office wireless",
    ]
    tails = ["half", "a half", "one half", "roughly half", "about half"]
    records, families = [], {}
    for family, stem in enumerate(stems):
        for index, tail in enumerate(tails):
            record_id = f"f{family}-{index}"
            records.append(record(record_id, f"{stem} {tail}"))
            families[record_id] = family
    singletons = [
        "the warehouse rejected the return because the seal was broken",
        "my colleague cannot see the shared board at all today",
        "the confirmation letter arrived addressed to somebody else entirely",
        "an engineer visited but brought the wrong replacement part",
        "the gift wrapping option disappeared halfway through the basket",
        "your shop keeps logging me out between the two steps",
        "the size guide contradicts the measurements on the product page",
        "nobody warned me the delivery needed somebody over eighteen",
        "the battery indicator stays orange however long it charges",
        "the receipt lists a colour that was never on the listing",
        "the courier photographed a doorway that is not my doorway",
        "the discount applied and then vanished when i changed quantity",
        "the manual is printed in a language i cannot read",
        "the spare keys were shipped separately and never turned up",
        "your telephone menu loops back to itself after two choices",
        "the replacement screen arrived already scratched across one corner",
        "my address was truncated so the parcel went somewhere odd",
        "the warranty card is dated before the day i ordered",
        "the packaging leaked and ruined the box underneath it",
        "the newsletter keeps arriving although i unsubscribed three times",
    ]
    for index, text in enumerate(singletons):
        record_id = f"s-{index:02d}"
        records.append(record(record_id, text))
        families[record_id] = 100 + index
    return records


def brute_force_pairs(records, *, size: int, threshold: float) -> set[tuple[str, str]]:
    sets = {r.record_id: shingles(r.input_text, size=size) for r in records}
    pairs = set()
    ids = sorted(sets)
    for i, left in enumerate(ids):
        for right in ids[i + 1 :]:
            if jaccard(sets[left], sets[right]) >= threshold:
                pairs.add((left, right))
    return pairs


def test_lsh_finds_what_brute_force_finds():
    records = synthetic_corpus()
    outcome = cluster_records(records, scores={}, params=PARAMS)
    exact = brute_force_pairs(records, size=PARAMS.shingle_words, threshold=PARAMS.threshold)
    found = outcome.merged_pairs

    true_positives = len(found & exact)
    precision = true_positives / len(found) if found else 1.0
    recall = true_positives / len(exact) if exact else 1.0
    # Precision is exactly 1 by construction: every candidate pair is verified
    # against the true Jaccard before it is merged. Recall is where the banding
    # actually costs something.
    assert precision == 1.0
    assert recall >= 0.95
    assert outcome.comparisons < len(records) * (len(records) - 1) // 2


def test_the_families_in_the_synthetic_corpus_come_back_as_families():
    outcome = cluster_records(synthetic_corpus(), scores={}, params=PARAMS)
    for family in range(10):
        cluster = cluster_of(outcome, f"f{family}-0")
        assert set(cluster.member_ids) == {f"f{family}-{i}" for i in range(5)}
