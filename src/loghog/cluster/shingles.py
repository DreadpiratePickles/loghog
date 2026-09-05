"""Word shingles and Jaccard similarity — the whole of the similarity model.

Deliberately not embeddings. An embedding threshold of 0.83 is a number nobody
can explain and nobody can check by hand; a shingle overlap of 0.6 is one a
reviewer can verify with a pencil by writing out two sets. When somebody later
asks "why did these two tickets merge", the answer here is a list of five-word
phrases they shared, which is an answer. "They were close in vector space" is
not one.

Three things happen during normalisation, and each of them removes a way for one
complaint to look like two.

**Digits go.** Two tickets about one outage differ by their order references,
and keeping the digits would make every ticket its own cluster.

**Redaction tokens collapse.** `[EMAIL_1]` and `[EMAIL_2]` carry the same fact —
"an address was here" — and the number in them is *which customer wrote in*.
Leaving it would split one cluster by the very thing stage 02 spent its effort
making stable.

**Case and whitespace go**, which is the same conservative normalisation stage
01 already uses for exact deduplication.
"""

import re

from loghog.errors import ClusterError

_TOKEN = re.compile(r"\[([a-z]+)_\d+\]")
_DIGITS = re.compile(r"\d+")
_WHITESPACE = re.compile(r"\s+")


def normalise_for_shingles(text: str) -> str:
    """Lowercase, collapse redaction tokens, drop digits, collapse whitespace.

    Raises:
        ClusterError: `text` is not a string. Clustering is the first stage
            that reads a window rather than writing one, and a `None` here
            means a record shape changed underneath it.
    """
    if not isinstance(text, str):
        raise ClusterError(f"text to shingle must be a string, got {type(text).__name__}")
    # The token collapse runs BEFORE the digits go, or `[EMAIL_1]` would become
    # `[EMAIL_]` and two tokens of one class would still be two words.
    lowered = _TOKEN.sub(r"[\1]", text.lower())
    return _WHITESPACE.sub(" ", _DIGITS.sub(" ", lowered)).strip()


def shingles(text: str, *, size: int) -> frozenset[str]:
    """The set of `size`-word phrases in `text`, after normalisation.

    A text with fewer than `size` words becomes one shingle of the whole thing,
    which is what makes short texts compare by exact equality — the fallback
    the stage contract promises, falling out of one rule rather than out of a
    second code path that could disagree with the first.

    A text with no words at all yields the empty set. That is not an oversight:
    an input that normalises to nothing is evidence of nothing, and two such
    absences are not a match.

    Raises:
        ClusterError: `size` is below one.
    """
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise ClusterError(f"a shingle is at least 1 word wide, got {size!r}")
    words = normalise_for_shingles(text).split()
    if not words:
        return frozenset()
    if len(words) <= size:
        return frozenset({" ".join(words)})
    return frozenset(
        " ".join(words[start : start + size]) for start in range(len(words) - size + 1)
    )


def jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    """Intersection over union, with the empty case answering zero.

    `jaccard(∅, ∅)` is conventionally 1 and is 0 here on purpose. Two records
    whose text normalised away have nothing in common; they have *nothing*, and
    calling that a perfect match would cluster every bare order number in a
    window into one case.
    """
    if not left or not right:
        return 0.0
    union = len(left | right)
    return len(left & right) / union
