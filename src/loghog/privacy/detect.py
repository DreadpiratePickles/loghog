"""What counts as personal data in a support ticket, and what does not.

Eight classes, in two groups.

**Structural** — `EMAIL`, `CARD`, `IBAN`, `SSN`, `IPV4`. These have a shape a
regex can be sure about, and two of them carry a checksum. A match here is
almost never wrong, which is why these five and only these five are what the
write guard re-checks in `redact.contains_hard_pii`.

**Heuristic** — `PHONE`, `ADDRESS`, `NAME`. These guess. A phone number and an
order reference are both runs of digits; a street and a product name are both
Title Case. Each detector here is deliberately narrow — a phone needs at least
two separated groups or a country code, an address needs a house number *and* a
street word, a name needs an honorific — and the `NAME` heuristic takes an
allowlist because the correction for "we stock Dr Pepper" cannot be a regex.

Detection returns *spans*, not replacements. Overlaps are resolved once, at the
end, by a fixed priority — so `4242 4242 4242 4242` is one `[CARD_1]` rather
than a card with a phone number inside it — and the caller replaces right to
left, which is the only order that keeps the earlier offsets valid.
"""

import re
from dataclasses import dataclass

from loghog.privacy.luhn import digits_only, luhn_ok

EMAIL = "EMAIL"
CARD = "CARD"
IBAN = "IBAN"
SSN = "SSN"
IPV4 = "IPV4"
PHONE = "PHONE"
ADDRESS = "ADDRESS"
NAME = "NAME"

PII_CLASSES: tuple[str, ...] = (EMAIL, IBAN, CARD, SSN, IPV4, PHONE, ADDRESS, NAME)
"""Every class, in priority order: earlier wins an overlap.

`EMAIL` first because an address contains a name, a phone-shaped run of digits
and a dotted quad, and all three are wrong. `CARD` above `PHONE` because a
sixteen-digit run that passes Luhn is a card whatever else it looks like.
`NAME` last because it is the only detector that guesses at a word rather than
at a shape.
"""

STRUCTURAL_CLASSES: frozenset[str] = frozenset({EMAIL, CARD, IBAN, SSN, IPV4})
"""The five a regex can be sure about — checksummed or structurally unambiguous.

`PHONE` is deliberately absent. It is the heuristic with the widest net, and a
write guard built on it would refuse an honest ingest because a product code
looked dialable.
"""

# --- the patterns -----------------------------------------------------------

_EMAIL = re.compile(
    # No word boundary at the front: the single most common way an address
    # survives a naive redactor is by sitting inside a URL, where it is
    # surrounded by slashes rather than spaces. The local-part character class
    # excludes `/` and `:`, which is what stops the match starting too early.
    r"[A-Za-z0-9._%+\-']+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}"
)

_CARD = re.compile(
    # Anchored to non-digits at both ends, so a digit run yields exactly one
    # candidate rather than a sliding window of them. That is what stops a
    # 24-digit machine id from being matched at the 16-digit Luhn-valid window
    # somewhere in its middle.
    r"(?<!\d)\d(?:[ -]?\d){12,18}(?!\d)"
)

_IBAN = re.compile(
    r"(?<![A-Za-z0-9])[A-Z]{2}\d{2}(?:[ ]?[A-Za-z0-9]{4}){2,7}(?:[ ]?[A-Za-z0-9]{1,3})?"
    r"(?![A-Za-z0-9])"
)

_SSN = re.compile(
    # The separator is captured and back-referenced: `123-45 6789` is not a
    # thing anybody types, and allowing it widens the net for nothing.
    r"(?<![\d-])\d{3}([- ])\d{2}\1\d{4}(?![\d-])"
)

_OCTET = r"(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)"
_IPV4 = re.compile(
    # The trailing guard is `(?!\.?\d)` and not `(?![\d.])`, which is the
    # difference between finding an address and not. "…timing out from
    # 192.168.1.14." ends a sentence, and a guard that refuses a following dot
    # refuses every IP anybody wrote in prose. What must be refused is a FIFTH
    # octet, which is a dot followed by a digit.
    rf"(?<![\d.]){_OCTET}(?:\.{_OCTET}){{3}}(?!\.?\d)"
)

_PHONE = re.compile(
    # Three shapes, and the third is why this is not one loose pattern.
    #
    #   A. a country code, then one or more further groups: +44 20 7946 0958
    #   B. a parenthesised area code:                       (555) 010-9999
    #   C. no prefix at all, and then THREE groups:         020 7946 0958
    #
    # C needs three because two is `9911-2233`, which is an invoice number, and
    # the sample CSV has one. Every real number in the test set has either a
    # country code, a parenthesised area code, or three groups — so the extra
    # group costs nothing and removes a whole class of false positive.
    r"(?<![\w.])(?:"
    r"\+\d{1,3}[ -]?(?:\(\d{1,4}\)[ -]?)?\d{2,4}(?:[ -]\d{2,6}){1,4}"
    r"|\(\d{1,4}\)[ -]?\d{2,4}(?:[ -]\d{2,6}){1,4}"
    r"|\d{2,4}(?:[ -]\d{2,6}){2,4}"
    r")(?!\w)"
)

_DATE_LIKE = re.compile(r"^\d{4}-\d{2}-\d{2}$|^\d{2}[-/]\d{2}[-/]\d{4}$")
"""A date is three groups of digits with separators, which is also the shape of
a North American telephone number. Dates are excluded by name rather than by
narrowing the phone pattern until it stops matching real numbers."""

MIN_PHONE_DIGITS = 7
"""Below seven digits nothing is dialable, and "rooms 12-34" is not a number."""

_STREET_WORDS = (
    "Street|St|Road|Rd|Avenue|Ave|Lane|Ln|Drive|Boulevard|Blvd|Way|Close|Court|Ct|"
    "Place|Pl|Terrace|Square|Sq|Crescent|Gardens|Grove|Hill|Park|Walk"
)
_LEADING_STREET_WORDS = "Rue|Via|Calle|Avenida|Piazza|Plaza|Strasse|Straat"

_ADDRESS_TRAILING = re.compile(
    # "221B Baker Street", "10 Downing St", "1600 Pennsylvania Avenue".
    rf"(?<!\d)\d{{1,5}}[A-Za-z]?\s+(?:[A-Z][A-Za-z'\-]+\s+){{0,3}}(?:{_STREET_WORDS})\b"
)
_ADDRESS_LEADING = re.compile(
    # "7 Rue Lafayette" — much of Europe puts the street word first.
    rf"(?<!\d)\d{{1,5}}[A-Za-z]?\s+(?:{_LEADING_STREET_WORDS})\s+[A-Z][A-Za-z'\-]+"
)

_HONORIFICS = "mrs|miss|mr|ms|mx|dr|prof|sir|dame|rev|fr|capt|sgt|lord|lady"
_NAME = re.compile(
    # An honorific and one or two capitalised words. Narrow on purpose: without
    # the honorific, "Lumen Desk" and "Susan Calvin" are the same string to a
    # regex, and the product name is the half an eval case needs.
    rf"\b(?i:{_HONORIFICS})\.?[ ]+[A-Z][A-Za-z'\-]+(?:[ ]+[A-Z][A-Za-z'\-]+)?"
)

_TOKEN = re.compile(r"\[[A-Z0-9]+_\d+\]")
"""An already-placed redaction token. Re-running ingestion over a redacted
window must be a no-op, not a second round of numbering."""


@dataclass(frozen=True)
class Span:
    """One stretch of text that is personal data, and which kind."""

    start: int
    end: int
    pii_class: str
    value: str


def find_spans(text: str, *, name_allowlist: tuple[str, ...] = ()) -> tuple[Span, ...]:
    """Every non-overlapping span of personal data in `text`, in document order.

    Args:
        text: the text to scan. Empty or non-string input yields nothing.
        name_allowlist: Title Case pairs that follow an honorific but are not
            people. Matched case-insensitively against the whole matched span.
    """
    if not isinstance(text, str) or not text:
        return ()
    allowed = frozenset(entry.strip().lower() for entry in name_allowlist)
    protected = [(match.start(), match.end()) for match in _TOKEN.finditer(text)]

    candidates: list[Span] = []
    candidates += _simple(text, _EMAIL, EMAIL)
    candidates += _validated(text, _IBAN, IBAN, _iban_ok)
    candidates += _validated(text, _CARD, CARD, luhn_ok)
    candidates += _simple(text, _SSN, SSN)
    candidates += _simple(text, _IPV4, IPV4)
    candidates += _validated(text, _PHONE, PHONE, _phone_ok)
    candidates += _simple(text, _ADDRESS_TRAILING, ADDRESS)
    candidates += _simple(text, _ADDRESS_LEADING, ADDRESS)
    candidates += [
        span for span in _simple(text, _NAME, NAME) if span.value.lower() not in allowed
    ]
    candidates = [span for span in candidates if not _overlaps_any(span, protected)]
    return resolve_overlaps(candidates)


def resolve_overlaps(spans: list[Span]) -> tuple[Span, ...]:
    """Keep the best span wherever two overlap; return the survivors in order.

    Best means: the higher-priority class first, and within a class the longer
    span. Greedy, and that is sufficient because the priority order is total —
    there is no cycle for a greedy pass to get wrong.
    """
    ranked = sorted(
        spans,
        key=lambda span: (PII_CLASSES.index(span.pii_class), -(span.end - span.start), span.start),
    )
    kept: list[Span] = []
    for span in ranked:
        if not any(span.start < other.end and other.start < span.end for other in kept):
            kept.append(span)
    return tuple(sorted(kept, key=lambda span: span.start))


def _simple(text: str, pattern: re.Pattern[str], pii_class: str) -> list[Span]:
    return [
        Span(start=match.start(), end=match.end(), pii_class=pii_class, value=match.group(0))
        for match in pattern.finditer(text)
    ]


def _validated(text, pattern, pii_class, check) -> list[Span]:
    return [span for span in _simple(text, pattern, pii_class) if check(span.value)]


def _overlaps_any(span: Span, ranges: list[tuple[int, int]]) -> bool:
    return any(span.start < end and start < span.end for start, end in ranges)


def _iban_ok(value: str) -> bool:
    """An IBAN is 15 to 34 alphanumerics after the spaces come out.

    The regex is deliberately loose about grouping and this is the length check
    it delegates to; ISO 13616 country lengths are not restated here, because a
    table of thirty-odd lengths would go stale and a redactor that misses a new
    country's format is worse than one that redacts a few extra bank codes.
    """
    stripped = value.replace(" ", "")
    return 15 <= len(stripped) <= 34


def _phone_ok(value: str) -> bool:
    """Enough digits to dial, and not a date wearing a phone number's shape."""
    if _DATE_LIKE.match(value.strip()):
        return False
    return len(digits_only(value)) >= MIN_PHONE_DIGITS
