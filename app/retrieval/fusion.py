"""Reciprocal rank fusion.

Dense scores are cosine similarities and BM25 scores are unbounded sums; they live
on different scales and cannot be added or averaged without inventing a weighting
that would need its own calibration. RRF sidesteps that entirely by discarding the
magnitudes and combining *ranks*, which is why it survives a change of encoder or a
change of corpus without retuning.
"""

from __future__ import annotations

from collections.abc import Sequence

# The conventional damping constant. Large enough that the top few ranks are not
# wildly dominant, small enough that rank still matters.
RRF_K = 60


def reciprocal_rank_fusion(
    ranked_lists: Sequence[Sequence[str]],
    *,
    k: int = RRF_K,
) -> list[tuple[str, float]]:
    """Fuse ranked id lists into one ranking.

    A document appearing modestly high in both lists beats one that tops a single
    list, which is the behaviour we want: agreement between two different notions of
    relevance is stronger evidence than a high score under either alone.
    """
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, doc_id in enumerate(ranked, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))
