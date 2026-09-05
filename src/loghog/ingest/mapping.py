"""A field mapping: how one vendor's log line becomes the canonical record.

This is the only place in the system that knows a particular producer calls the
answer `generation.output.text`. Everything after ingestion reads the canonical
record and nothing else — which is the whole reason for having a canonical
record at all.

A mapping is *configuration*, so it is validated like configuration: unknown
target fields, unknown keys, unknown extractors and unknown source formats all
stop the run. A tolerant loader here would fail sixty thousand log lines one at
a time over a typo in one line of TOML.
"""

import hashlib
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loghog.errors import MappingError
from loghog.ingest.extractors import DEFAULT_EXTRACTOR, extractor_for
from loghog.record import RECORD_KEYS

SCHEMA_VERSION = 1

CANONICAL_FIELDS: frozenset[str] = RECORD_KEYS
REQUIRED_FIELDS: tuple[str, ...] = ("record_id", "ts_utc", "input_text")
TEXT_FIELDS: frozenset[str] = frozenset({"input_text", "output_text"})

SOURCE_FORMATS: tuple[str, ...] = ("jsonl", "csv")

BUILTIN_MAPPINGS: tuple[str, ...] = (
    "regress_rollout_events",
    "prompton_events",
    "openai_chat_jsonl",
)
"""The mappings this repository ships in `mappings/`. Named here so that a typo
in `--mapping` produces a list rather than a file-not-found."""

_TOP_LEVEL_KEYS = frozenset(
    {"schema_version", "name", "description", "source_format", "fields", "defaults",
     "sidecar", "timestamp", "expect"}
)
_FIELD_SPEC_KEYS = frozenset({"path", "extractor", "criterion_key", "passed_key"})
_SIDECAR_KEYS = frozenset({"key_field", "text_field", "target"})


@dataclass(frozen=True)
class FieldSpec:
    """Where one canonical field comes from, and how it is read out."""

    target: str
    path: str | None
    extractor: str = DEFAULT_EXTRACTOR
    criterion_key: str = "criterion"
    passed_key: str = "passed"

    @property
    def required(self) -> bool:
        return self.target in REQUIRED_FIELDS


@dataclass(frozen=True)
class SidecarSpec:
    """How to rejoin text a log stored only as a hash.

    `regress-rollout` stores `input_sha256` and not the ticket, on purpose — its
    event log keeps what its monitor needs and no more. The text lives in the
    traffic file, and this is the seam that puts the two halves back together
    under an operator's eye rather than guessing.
    """

    key_field: str
    text_field: str
    target: str


@dataclass(frozen=True)
class FieldMapping:
    """One validated mapping file."""

    path: Path
    sha256: str
    name: str
    description: str
    source_format: str
    fields: dict[str, FieldSpec]
    defaults: dict[str, Any]
    sidecar: SidecarSpec | None
    naive_is_utc: bool
    expect_output_json: bool


def resolve_mapping(reference: str, *, mappings_dir: Path | None) -> FieldMapping:
    """Load a mapping named either by a bare built-in name or by a path."""
    candidate = Path(reference)
    if candidate.suffix == ".toml" or candidate.exists():
        return load_mapping(candidate)
    if mappings_dir is None:
        raise MappingError(f"{reference!r} is not a path and no mappings directory is configured")
    path = mappings_dir / f"{reference}.toml"
    if not path.is_file():
        known = ", ".join(BUILTIN_MAPPINGS)
        raise MappingError(f"no mapping named {reference!r} in {mappings_dir}. Built in: {known}")
    return load_mapping(path)


def load_mapping(path: Path) -> FieldMapping:
    """Read and validate one mapping file.

    Raises:
        MappingError: absent, unparseable, or naming something that does not
            exist. Every message names what was wrong.
    """
    path = Path(path)
    if not path.is_file():
        raise MappingError(f"no mapping file at {path}")
    raw_bytes = path.read_bytes()
    try:
        raw = tomllib.loads(raw_bytes.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise MappingError(f"{path} is not readable TOML: {exc}") from exc

    _reject_unknown(raw, allowed=_TOP_LEVEL_KEYS, what="top-level key", where=path)
    version = raw.get("schema_version")
    if version != SCHEMA_VERSION:
        raise MappingError(
            f"{path} declares schema_version {version!r}; this loader reads {SCHEMA_VERSION}. "
            "A mapping written for a later loader is not one this code can be trusted to read."
        )
    name = _require_string(raw, "name", where=path)
    description = _require_string(raw, "description", where=path)
    source_format = _require_string(raw, "source_format", where=path)
    if source_format not in SOURCE_FORMATS:
        raise MappingError(
            f"{path} declares source_format {source_format!r}; supported: "
            f"{', '.join(SOURCE_FORMATS)}"
        )

    fields = _read_fields(raw.get("fields"), where=path)
    defaults = _read_defaults(raw.get("defaults", {}), where=path)
    sidecar = _read_sidecar(raw.get("sidecar"), where=path)
    naive_is_utc = _read_naive_flag(raw.get("timestamp", {}), where=path)
    expect_output_json = _read_expect_flag(raw.get("expect", {}), where=path)

    supplied = set(fields) | set(defaults) | ({sidecar.target} if sidecar else set())
    absent = [field for field in REQUIRED_FIELDS if field not in supplied]
    if absent:
        raise MappingError(
            f"{path} maps none of {', '.join(absent)}, and a record cannot exist without them"
        )
    return FieldMapping(
        path=path,
        sha256=hashlib.sha256(raw_bytes).hexdigest(),
        name=name,
        description=description,
        source_format=source_format,
        fields=fields,
        defaults=defaults,
        sidecar=sidecar,
        naive_is_utc=naive_is_utc,
        expect_output_json=expect_output_json,
    )


def _read_fields(raw: Any, *, where: Path) -> dict[str, FieldSpec]:
    if not isinstance(raw, dict) or not raw:
        raise MappingError(f"{where} has no [fields] table")
    _reject_unknown(raw, allowed=CANONICAL_FIELDS, what="field", where=where)
    fields: dict[str, FieldSpec] = {}
    for target, spec in raw.items():
        if isinstance(spec, str):
            fields[target] = FieldSpec(target=target, path=spec)
            continue
        if not isinstance(spec, dict):
            raise MappingError(
                f"{where}: field {target} must be a path or a table, got {type(spec).__name__}"
            )
        _reject_unknown(spec, allowed=_FIELD_SPEC_KEYS, what=f"key in field {target}", where=where)
        path = spec.get("path")
        if path is not None and (not isinstance(path, str) or not path.strip()):
            raise MappingError(f"{where}: field {target} has an empty path")
        extractor = spec.get("extractor", DEFAULT_EXTRACTOR)
        if not isinstance(extractor, str):
            raise MappingError(f"{where}: field {target} names a non-string extractor")
        extractor_for(extractor)
        fields[target] = FieldSpec(
            target=target,
            path=path,
            extractor=extractor,
            criterion_key=str(spec.get("criterion_key", "criterion")),
            passed_key=str(spec.get("passed_key", "passed")),
        )
    return fields


def _read_defaults(raw: Any, *, where: Path) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise MappingError(f"{where}: [defaults] must be a table")
    _reject_unknown(raw, allowed=CANONICAL_FIELDS, what="default", where=where)
    return dict(raw)


def _read_sidecar(raw: Any, *, where: Path) -> SidecarSpec | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise MappingError(f"{where}: [sidecar] must be a table")
    _reject_unknown(raw, allowed=_SIDECAR_KEYS, what="key in [sidecar]", where=where)
    for key in ("key_field", "text_field", "target"):
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            raise MappingError(f"{where}: [sidecar] needs a non-empty {key}")
    target = raw["target"]
    if target not in TEXT_FIELDS:
        raise MappingError(
            f"{where}: [sidecar] target {target!r} is not a text field. A hash join can only "
            f"restore text; supported targets: {', '.join(sorted(TEXT_FIELDS))}"
        )
    return SidecarSpec(key_field=raw["key_field"], text_field=raw["text_field"], target=target)


def _read_naive_flag(raw: Any, *, where: Path) -> bool:
    if not isinstance(raw, dict):
        raise MappingError(f"{where}: [timestamp] must be a table")
    _reject_unknown(
        raw, allowed=frozenset({"naive_is_utc"}), what="key in [timestamp]", where=where
    )
    value = raw.get("naive_is_utc", False)
    if not isinstance(value, bool):
        raise MappingError(f"{where}: naive_is_utc must be true or false")
    return value


def _read_expect_flag(raw: Any, *, where: Path) -> bool:
    """`[expect] output_json`: the one thing about a producer's output shape a
    mapping declares.

    It lives here rather than in `loghog.toml` because it is a fact about one
    producer, and a window can hold several. It travels to the scorer in the
    manifest, per source, which is why the manifest schema went to 2.
    """
    if not isinstance(raw, dict):
        raise MappingError(f"{where}: [expect] must be a table")
    _reject_unknown(
        raw, allowed=frozenset({"output_json"}), what="key in [expect]", where=where
    )
    value = raw.get("output_json", False)
    if not isinstance(value, bool):
        raise MappingError(f"{where}: output_json must be true or false, got {value!r}")
    return value


def _require_string(raw: dict[str, Any], key: str, *, where: Path) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MappingError(f"{where} has no {key}")
    return value


def _reject_unknown(
    table: dict[str, Any], *, allowed: frozenset[str], what: str, where: Path
) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise MappingError(
            f"{where}: unknown {what}: {', '.join(unknown)}. Known: {', '.join(sorted(allowed))}"
        )
