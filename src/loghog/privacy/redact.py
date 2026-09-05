"""Replacement, stable tokens, and the report that counts what was taken out.

The token is the interesting part. `[EMAIL_1]` in one record and `[EMAIL_1]` in
another must mean the same address, or a later stage cannot tell "the same
customer wrote in three times" from "three customers wrote in once" — and that
is the difference between one eval case and three. So a `Redactor` is stateful
for the length of a window: it remembers which value it gave which number, and
hands out the same token for the same value however far apart the two records
are.

What it deliberately does *not* remember anywhere it can be read back is the
value itself. The map lives in memory for the duration of the run and is never
written; the report counts classes and distinct values and quotes nothing. A
redaction report that names what it redacted is a second copy of the data, in a
file people paste into tickets.
"""

from dataclasses import dataclass
from typing import Any

from loghog.errors import RedactionError
from loghog.privacy.detect import (
    CARD,
    EMAIL,
    IBAN,
    PHONE,
    PII_CLASSES,
    SSN,
    STRUCTURAL_CLASSES,
    Span,
    find_spans,
)

_DIGIT_CLASSES = frozenset({CARD, IBAN, SSN, PHONE})


def redaction_token(pii_class: str, index: int) -> str:
    """The replacement text for the `index`-th distinct value of a class."""
    if pii_class not in PII_CLASSES:
        raise RedactionError(f"unknown PII class {pii_class!r}")
    if not isinstance(index, int) or isinstance(index, bool) or index < 1:
        raise RedactionError(f"a token index starts at 1, got {index!r}")
    return f"[{pii_class}_{index}]"


@dataclass(frozen=True)
class RedactionReport:
    """What a window's redaction did, in numbers that carry no personal data."""

    enabled: bool
    by_class: dict[str, int]
    distinct_by_class: dict[str, int]
    total: int
    texts_seen: int
    texts_changed: int

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "by_class": dict(sorted(self.by_class.items())),
            "distinct_by_class": dict(sorted(self.distinct_by_class.items())),
            "enabled": self.enabled,
            "texts_changed": self.texts_changed,
            "texts_seen": self.texts_seen,
            "total": self.total,
        }


class Redactor:
    """Replaces personal data with stable tokens, and counts what it replaced.

    One instance per window. Reusing one across windows would make `[EMAIL_1]`
    mean two different people in two different files, which is worse than
    numbering from one in each.
    """

    def __init__(self, *, name_allowlist: tuple[str, ...] = (), enabled: bool = True) -> None:
        for entry in name_allowlist:
            if not isinstance(entry, str):
                raise RedactionError(
                    f"the name allowlist holds strings, got {type(entry).__name__}"
                )
        self._name_allowlist = tuple(name_allowlist)
        self._enabled = bool(enabled)
        self._tokens: dict[tuple[str, str], int] = {}
        self._counts: dict[str, int] = {}
        self._texts_seen = 0
        self._texts_changed = 0

    def redact(self, text: str | None) -> str | None:
        """Return `text` with every detected value replaced by its token.

        `None` stays `None`: an absent field is a different fact from an empty
        one, and redaction is not the place to conflate them.
        """
        if text is None:
            return None
        if not self._enabled:
            return text
        self._texts_seen += 1
        spans = find_spans(text, name_allowlist=self._name_allowlist)
        if not spans:
            return text
        # Two passes, and the order of each matters for a different reason.
        #
        # Numbering runs LEFT to right, because the token index is a reading
        # order: the first address in the window is `[EMAIL_1]`. Allocating
        # during the replacement pass instead would number them backwards, and
        # a reader comparing a record against its report would find the first
        # address called `[EMAIL_2]`.
        tokens = [self._token_for(span) for span in spans]
        # Replacement runs RIGHT to left, because every replacement changes the
        # length of the string and only this direction leaves the offsets of
        # the spans still to be replaced exactly where they were.
        result = text
        for span, token in zip(reversed(spans), reversed(tokens), strict=True):
            result = result[: span.start] + token + result[span.end :]
            self._counts[span.pii_class] = self._counts.get(span.pii_class, 0) + 1
        self._texts_changed += 1
        return result

    def report(self) -> RedactionReport:
        """The counts so far. Safe to render into a file a human reads."""
        distinct: dict[str, int] = {}
        for pii_class, _ in self._tokens:
            distinct[pii_class] = distinct.get(pii_class, 0) + 1
        return RedactionReport(
            enabled=self._enabled,
            by_class=dict(self._counts),
            distinct_by_class=distinct,
            total=sum(self._counts.values()),
            texts_seen=self._texts_seen,
            texts_changed=self._texts_changed,
        )

    def _token_for(self, span: Span) -> str:
        key = (span.pii_class, _canonical(span))
        index = self._tokens.get(key)
        if index is None:
            index = sum(1 for existing, _ in self._tokens if existing == span.pii_class) + 1
            self._tokens[key] = index
        return redaction_token(span.pii_class, index)


def _canonical(span: Span) -> str:
    """The form two spellings of one value must share to share a token.

    `SAM@Example.com` and `sam@example.com` are one mailbox; `4242 4242 4242
    4242` and `4242-4242-4242-4242` are one card. Giving either pair two tokens
    would silently split one customer in half.
    """
    if span.pii_class in _DIGIT_CLASSES:
        return "".join(character for character in span.value if character.isalnum()).upper()
    if span.pii_class == EMAIL:
        return span.value.lower()
    return " ".join(span.value.split()).lower()


def hard_pii_classes(text: str | None) -> tuple[str, ...]:
    """The *structural* PII classes still present in `text`, sorted, deduplicated.

    This is the write guard, not a second redactor. It asks only about the five
    classes a regex can be sure about — an email, a Luhn-valid card, an IBAN, an
    SSN, a dotted quad — because a guard that fired on the heuristics would
    refuse an honest ingest over a product name that looked like a street.

    It returns the classes rather than a boolean because the writer's refusal
    message names them. The class, never the value: that message goes into logs
    and tickets, and quoting what leaked would leak it again.
    """
    if not text:
        return ()
    found = {
        span.pii_class for span in find_spans(text) if span.pii_class in STRUCTURAL_CLASSES
    }
    return tuple(sorted(found))


def contains_hard_pii(text: str | None) -> bool:
    """Whether `text` still holds personal data of a structural class.

    The boolean form of `hard_pii_classes`, and defined in terms of it rather
    than beside it: one predicate with two spellings is one predicate that can
    disagree with itself after somebody edits only the spelling they found.
    """
    return bool(hard_pii_classes(text))
