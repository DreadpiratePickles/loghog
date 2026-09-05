"""Two fixed pattern registries: injection attempts in, refusals out.

Both are code and not configuration, for the reason the extractor registry is:
a regex read from a file is a regex nobody reviewed, and a catastrophically
backtracking one is a run that never finishes over somebody else's log. The
*weight* on each signal is configuration, because that is the argument; the
patterns are the implementation of a definition, and definitions live with
tests naming what they are for.

Every pattern is deliberately narrow. The failure mode that matters is not
missing an attack — a missed injection is one case not mined — it is firing on
ordinary traffic, because a signal that matches "please ignore the second
attachment" turns the shortlist into a list of ordinary tickets and the whole
stage stops meaning anything.

Neither function ever returns what it matched. A signal's evidence names the
pattern, because an injection attempt is production text like any other, and a
report that quoted it would carry it into the ticket.
"""

import re

INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "override_instructions",
        # "ignore/disregard/forget" within a few words of "instructions" or
        # "prompt". The proximity requirement is what keeps "ignore the second
        # attachment" out.
        re.compile(
            r"\b(?:ignore|disregard|forget)\b[^.!?\n]{0,40}?"
            r"\b(?:instruction|instructions|prompt|rules?|guidelines?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "reveal_system_prompt",
        re.compile(
            r"\b(?:system|initial|original)\s+(?:prompt|message|instructions)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "repeat_the_above",
        re.compile(
            r"\brepeat\b[^.!?\n]{0,30}?\b(?:above|preceding|everything)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "roleplay_jailbreak",
        re.compile(
            r"\byou are now\b|\b(?:dan|do anything now)\s+mode\b"
            r"|\bpretend (?:you are|to be) (?:a |an )?(?:different|another|unrestricted)\b"
            r"|\bwith no (?:rules|restrictions|filters)\b",
            re.IGNORECASE,
        ),
    ),
)

REFUSAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "cannot_help",
        # An apology alone is not a refusal — "sorry for the delay" is good
        # support writing. The refusal is the inability that follows it.
        re.compile(
            # Two shapes, and both need the inability. The apologetic one —
            # "I'm sorry, but I can't" — and the flat one, which is pinned to a
            # verb so that "I can't find the order number you gave" stays a
            # support answer rather than becoming a refusal.
            r"\bi\s*(?:'m|’m|\s+am)?\s*(?:really |very |so )?(?:sorry|afraid)[,\s]*"
            r"(?:but\s+)?i\s*(?:can\s?not|can'?t|can’t|won'?t|will not)\b"
            r"|\bi\s*(?:can\s?not|cannot|can'?t|can’t)\s+"
            r"(?:help|assist|provide|comply|answer|continue|do that)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "unable_to",
        re.compile(r"\bi\s*(?:am|'m|’m)?\s*(?:not able|unable)\s+to\b", re.IGNORECASE),
    ),
    (
        "as_an_ai",
        re.compile(r"\bas an ai(?:\s+(?:language\s+)?model)?\b", re.IGNORECASE),
    ),
)


def _matched(text: str | None, registry: tuple[tuple[str, re.Pattern[str]], ...]) -> str | None:
    if not text:
        return None
    for name, pattern in registry:
        if pattern.search(text):
            return name
    return None


def matched_injection(text: str | None) -> str | None:
    """The name of the first injection pattern `text` matches, or `None`."""
    return _matched(text, INJECTION_PATTERNS)


def matched_refusal(text: str | None) -> str | None:
    """The name of the first refusal pattern `text` matches, or `None`."""
    return _matched(text, REFUSAL_PATTERNS)
