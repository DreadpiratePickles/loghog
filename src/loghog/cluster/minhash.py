"""MinHash: a fixed-width sketch whose agreement rate estimates Jaccard.

For each of `k` random permutations of the universe of shingles, the signature
records the smallest shingle under that permutation. Two sets agree on a given
position with probability exactly their Jaccard similarity, so the fraction of
positions where two signatures agree is an unbiased estimate of it — computed in
`k` integer comparisons rather than by intersecting two sets.

The base hash is **BLAKE2b, not Python's `hash()`**, and that is the one
decision in this module that would otherwise be a bug nobody noticed for months.
`hash()` of a `str` is salted per interpreter process: it is stable inside one
run and different in the next. Every unit test would pass, every clustering
would be internally consistent, and re-running the same command on the same
window on the same machine would silently produce a different partition. There
is a test that runs this module in two subprocesses under two values of
`PYTHONHASHSEED` and compares the output, because that is the only way to catch
it.

The permutations are the standard `(a·x + b) mod p` family over the Mersenne
prime 2⁶¹−1, with `a` and `b` drawn from a seeded generator. Seeded, so the
sketch is a function of the configuration and nothing else.
"""

import hashlib
import random
from dataclasses import dataclass

from loghog.errors import ClusterError

MERSENNE_PRIME = (1 << 61) - 1
"""2⁶¹−1. Large enough that collisions are not a practical concern and prime, so
`(a·x + b) mod p` is a permutation for every non-zero `a`."""

_MAX_HASH = MERSENNE_PRIME


def base_hash(shingle: str) -> int:
    """The process-independent integer a shingle stands for.

    BLAKE2b truncated to eight bytes. Any cryptographic digest would do; what
    matters is that it does not depend on the interpreter's hash seed.
    """
    digest = hashlib.blake2b(shingle.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % MERSENNE_PRIME


@dataclass(frozen=True)
class MinHasher:
    """One family of seeded permutations, and the signatures it produces."""

    permutations: int
    seed: int
    multipliers: tuple[int, ...]
    offsets: tuple[int, ...]

    @classmethod
    def create(cls, *, permutations: int, seed: int) -> "MinHasher":
        """Build the permutation family for a width and a seed.

        Raises:
            ClusterError: `permutations` is below one.
        """
        if isinstance(permutations, bool) or not isinstance(permutations, int):
            raise ClusterError(f"permutations must be an integer, got {permutations!r}")
        if permutations < 1:
            raise ClusterError(f"a signature is at least 1 hash wide, got {permutations}")
        # `random.Random` with an explicit seed is deterministic across versions
        # for `randrange`, and this is the only use of randomness in the
        # package — every other decision here is a function of its inputs.
        rng = random.Random(seed)
        multipliers = tuple(rng.randrange(1, MERSENNE_PRIME) for _ in range(permutations))
        offsets = tuple(rng.randrange(0, MERSENNE_PRIME) for _ in range(permutations))
        return cls(
            permutations=permutations, seed=seed, multipliers=multipliers, offsets=offsets
        )

    def signature(self, shingle_set: frozenset[str]) -> tuple[int, ...]:
        """The minimum of each permutation over `shingle_set`.

        Raises:
            ClusterError: the set is empty. An empty set has no minimum, and
                inventing one — the maximum, say — would give every wordless
                record the same signature and cluster them all together.
        """
        if not shingle_set:
            raise ClusterError(
                "an empty shingle set has no signature. A record whose text normalised to "
                "nothing is a singleton, not a member."
            )
        bases = [base_hash(shingle) for shingle in shingle_set]
        return tuple(
            min((multiplier * base + offset) % MERSENNE_PRIME for base in bases)
            for multiplier, offset in zip(self.multipliers, self.offsets, strict=True)
        )


def estimated_jaccard(left: tuple[int, ...], right: tuple[int, ...]) -> float:
    """The fraction of positions on which two signatures agree.

    Raises:
        ClusterError: the signatures are different widths, which means they came
            from two different configurations and comparing them is meaningless.
    """
    if len(left) != len(right):
        raise ClusterError(
            f"signatures of width {len(left)} and {len(right)} cannot be compared; "
            "they came from different permutation families."
        )
    if not left:
        raise ClusterError("an empty signature estimates nothing")
    agreements = sum(1 for one, other in zip(left, right, strict=True) if one == other)
    return agreements / len(left)
