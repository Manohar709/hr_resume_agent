"""
agents/ranking_agent.py
------------------------
Ranking Engine — sorts candidates by score and applies human overrides.
"""

import logging
from typing import List, Dict, Tuple

from schemas.pydantic_models import CandidateScore
from database.db import get_override

logger = logging.getLogger(__name__)


def rank_candidates(
    scores: List[CandidateScore],
) -> List[Tuple[int, CandidateScore, Dict]]:
    """
    Sort candidates by effective score (override if exists, else LLM score).

    Args:
        scores: List of CandidateScore objects from the scoring agent.

    Returns:
        List of (rank, CandidateScore, override_info) tuples, sorted 1=best.
    """
    ranked = []

    for score in scores:
        override_info = get_override(score.file_hash) or {}
        effective_score = override_info.get("new_score", score.total_weighted_score)
        ranked.append((effective_score, score, override_info))

    # Sort descending by effective score
    ranked.sort(key=lambda x: x[0], reverse=True)

    result = []
    for rank, (eff_score, score, override_info) in enumerate(ranked, start=1):
        result.append((rank, score, override_info))
        logger.info(
            f"[Ranking] #{rank} {score.candidate_name} — "
            f"score={eff_score:.2f} {'(overridden)' if override_info else ''}"
        )

    return result


def get_shortlist(
    ranked: List[Tuple[int, CandidateScore, Dict]],
    min_score: float = 5.0,
    top_n: int = None,
) -> List[Tuple[int, CandidateScore, Dict]]:
    """
    Filter to candidates above threshold and/or top N.

    Args:
        ranked: Output of rank_candidates().
        min_score: Minimum score to include in shortlist.
        top_n: If set, cap at top N candidates regardless of score.

    Returns:
        Filtered and ranked list.
    """
    shortlisted = [
        (rank, score, override)
        for rank, score, override in ranked
        if (override.get("new_score", score.total_weighted_score) >= min_score)
    ]

    if top_n:
        shortlisted = shortlisted[:top_n]

    logger.info(
        f"[Ranking] Shortlisted {len(shortlisted)}/{len(ranked)} candidates "
        f"(min_score={min_score})"
    )
    return shortlisted
