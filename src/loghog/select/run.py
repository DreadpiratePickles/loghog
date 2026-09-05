"""Stage 05: the shortlist, and the accounting for everything that did not make it.

One rule holds the whole stage together: **no cap is silent.** Every record that
was not chosen was refused by exactly one named cap, and `selection.md` gives
the count for each. A shortlist whose omissions are unexplained is a shortlist
nobody can trust to be representative, and representativeness is the only
property it has.

The caps are checked in a fixed order, and the order is the design:

1. **already in the goldens** — a case you have is not a case to mine, and it
   must not consume the slot a new one needed. First, so it never does.
2. **the cluster cap** — twenty-five tickets about Tuesday's outage are one
   case. At `max_per_cluster = 1` the record that survives a cluster is its
   highest-scoring member, which is exactly the representative stage 04 named.
3. **the stratum quota** — a pure top-N by score is a dataset made entirely of
   the loudest failure mode of that week, which then measures one thing.
4. **the global cap** — last, so that it is only ever blamed for records that
   would otherwise have been taken.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loghog.cluster.shingles import jaccard, shingles
from loghog.config_file import LoghogConfig
from loghog.errors import SelectionError
from loghog.record import Record
from loghog.score.settings import SIGNAL_NAMES
from loghog.select.report import render_selection_report
from loghog.select.settings import ORDINARY, STRATA
from loghog.window.artifacts import read_clusters, read_jsonl, write_jsonl, write_text
from loghog.window.store import WindowStore

EXIT_OK = 0
EXIT_TRUNCATED = 1
EXIT_NOTHING = 2

CANDIDATES_NAME = "candidates.jsonl"
SELECTION_REPORT_NAME = "selection.md"


@dataclass(frozen=True)
class Candidate:
    """One record that made the shortlist, and why."""

    rank: int
    record_id: str
    score: int
    stratum: str
    cluster_id: str
    cluster_size: int
    reasons: tuple[str, ...]
    input_text: str
    output_text: str | None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "cluster_size": self.cluster_size,
            "input_text": self.input_text,
            "output_text": self.output_text,
            "rank": self.rank,
            "reasons": list(self.reasons),
            "record_id": self.record_id,
            "score": self.score,
            "stratum": self.stratum,
        }


@dataclass(frozen=True)
class Stratum:
    """One stratum's quota and how much of it the window could fill."""

    name: str
    quota: int
    selected: int

    @property
    def unfilled(self) -> int:
        return max(self.quota - self.selected, 0)


@dataclass(frozen=True)
class SelectOutcome:
    """What one `loghog select` did."""

    window: str
    directory: Path
    selected: tuple[Candidate, ...]
    strata: tuple[Stratum, ...]
    dropped: dict[str, int]
    considered: int
    max_candidates: int
    max_per_cluster: int
    exit_code: int

    @property
    def selected_count(self) -> int:
        return len(self.selected)

    @property
    def unfilled(self) -> tuple[tuple[str, int], ...]:
        return tuple(
            (stratum.name, stratum.unfilled) for stratum in self.strata if stratum.unfilled
        )


def select_candidates(
    config: LoghogConfig,
    *,
    window: str,
    max_candidates: int | None = None,
    golden_inputs: Sequence[str] | None = None,
    out_dir: Path | None = None,
) -> SelectOutcome:
    """Build the shortlist for one window.

    Raises:
        SelectionError: a cap below one, a window that has not been clustered,
            or a clusters document that names a record the window does not hold.
        ScoreError: the window has not been scored.
    """
    if max_candidates is not None and (
        isinstance(max_candidates, bool) or not isinstance(max_candidates, int)
        or max_candidates < 1
    ):
        raise SelectionError(f"--max-candidates is at least 1, got {max_candidates!r}")
    cap = max_candidates if max_candidates is not None else config.select.max_candidates

    store = WindowStore(config.records_dir / window)
    records = {record.record_id: record for record in store.read_records()}
    if not records:
        raise SelectionError(
            f"no records in window {window!r}. Run `loghog ingest --window {window} ...` first."
        )
    scored = _scored_rows(store, records)
    cluster_of, cluster_size = _cluster_index(store, records)
    golden_shingles = (
        tuple(shingles(text, size=config.cluster.shingle_words) for text in golden_inputs)
        if golden_inputs
        else None
    )

    selected: list[Candidate] = []
    dropped: dict[str, int] = {}
    filled: dict[str, int] = dict.fromkeys(STRATA, 0)
    per_cluster: dict[str, int] = {}

    for record_id, score, signal_names in scored:
        record = records[record_id]
        stratum = stratum_for(signal_names, config)
        cluster = cluster_of[record_id]
        if golden_shingles is not None and _already_held(record, golden_shingles, config):
            _count(dropped, "already_in_goldens")
            continue
        if per_cluster.get(cluster, 0) >= config.select.max_per_cluster:
            _count(dropped, "cluster_cap")
            continue
        if filled[stratum] >= config.select.quota(stratum):
            _count(dropped, f"quota:{stratum}")
            continue
        if len(selected) >= cap:
            _count(dropped, "max_candidates")
            continue
        filled[stratum] += 1
        per_cluster[cluster] = per_cluster.get(cluster, 0) + 1
        selected.append(
            Candidate(
                rank=len(selected) + 1,
                record_id=record_id,
                score=score,
                stratum=stratum,
                cluster_id=cluster,
                cluster_size=cluster_size[cluster],
                reasons=signal_names or ("no signal fired; ordinary traffic",),
                input_text=record.input_text,
                output_text=record.output_text,
            )
        )

    strata = tuple(
        Stratum(name=name, quota=config.select.quota(name), selected=filled[name])
        for name in STRATA
    )
    directory = Path(out_dir) if out_dir is not None else config.selected_dir / window
    outcome = SelectOutcome(
        window=window,
        directory=directory,
        selected=tuple(selected),
        strata=strata,
        dropped=dropped,
        considered=len(scored),
        max_candidates=cap,
        max_per_cluster=config.select.max_per_cluster,
        exit_code=_exit_code(selected, dropped),
    )
    write_jsonl(
        directory / CANDIDATES_NAME,
        [candidate.to_json_dict() for candidate in outcome.selected],
    )
    write_text(directory / SELECTION_REPORT_NAME, render_selection_report(outcome))
    return outcome


def stratum_for(signal_names: tuple[str, ...], config: LoghogConfig) -> str:
    """The stratum a record belongs to: its highest-weighted signal.

    Ties are broken by the registry order, which is fixed — so two runs over one
    window put every record in the same stratum, and a record that fired both
    `error` and `tiny_input` is counted against the evidence that actually made
    it interesting rather than against whichever check happened to run first.
    """
    if not signal_names:
        return ORDINARY
    order = {name: index for index, name in enumerate(SIGNAL_NAMES)}
    known = [name for name in signal_names if name in order]
    if not known:
        return ORDINARY
    return min(known, key=lambda name: (-config.score.weight(name), order[name]))


def _scored_rows(
    store: WindowStore, records: dict[str, Record]
) -> list[tuple[str, int, tuple[str, ...]]]:
    """Every record with its score and signal names, best first.

    Ordered by descending score and then by record id, so that the shortlist is
    a function of the window rather than of the order a file happened to be
    written in.
    """
    rows = []
    for payload in read_jsonl(store.scores_path, what="scores file"):
        record_id = payload.get("record_id")
        if record_id not in records:
            raise SelectionError(
                f"{store.scores_path} scores {record_id!r}, which is not in this window. "
                f"Re-run `loghog score --window {store.directory.name}`."
            )
        names = tuple(entry["name"] for entry in payload.get("signals", []))
        rows.append((record_id, int(payload["score"]), names))
    missing = sorted(set(records) - {row[0] for row in rows})
    if missing:
        raise SelectionError(
            f"{len(missing)} record(s) in this window have no score, starting with "
            f"{missing[0]!r}. Re-run `loghog score --window {store.directory.name}`."
        )
    rows.sort(key=lambda row: (-row[1], row[0]))
    return rows


def _cluster_index(
    store: WindowStore, records: dict[str, Record]
) -> tuple[dict[str, str], dict[str, int]]:
    payload = read_clusters(store)
    cluster_of: dict[str, str] = {}
    sizes: dict[str, int] = {}
    for cluster in payload["clusters"]:
        sizes[cluster["cluster_id"]] = len(cluster["member_ids"])
        for member in cluster["member_ids"]:
            cluster_of[member] = cluster["cluster_id"]
    missing = sorted(set(records) - set(cluster_of))
    if missing:
        raise SelectionError(
            f"{len(missing)} record(s) are in no cluster, starting with {missing[0]!r}. "
            f"Re-run `loghog cluster --window {store.directory.name}`."
        )
    return cluster_of, sizes


def _already_held(
    record: Record, golden_shingles: tuple[frozenset[str], ...], config: LoghogConfig
) -> bool:
    mine = shingles(record.input_text, size=config.cluster.shingle_words)
    best = max((jaccard(mine, theirs) for theirs in golden_shingles), default=0.0)
    return best >= config.score.novelty_max_jaccard


def _count(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1


def _exit_code(selected: list[Candidate], dropped: dict[str, int]) -> int:
    """0 worked, 1 truncated, 2 nothing chosen.

    An unfilled stratum does **not** make this 1. It is a fact about the
    traffic — most windows contain no injection attempts — and a code that was
    1 on almost every run would stop meaning anything. Truncation is a fact
    about the run: there was more worth having and the cap stopped it, which is
    exactly the case where somebody should read the report.
    """
    if not selected:
        return EXIT_NOTHING
    return EXIT_TRUNCATED if dropped.get("max_candidates") else EXIT_OK
