"""
embeddings/similarity_engine.py
--------------------------------
Semantic matching between JD requirements and candidate profiles.
Uses sentence-transformers (all-MiniLM-L6-v2) + cosine similarity.
Model is loaded once and cached for the session.
"""

import logging
from typing import List, Optional
import numpy as np

logger = logging.getLogger(__name__)

_model = None  # Singleton — loaded once


def _get_model():
    """Lazy-load the embedding model (downloaded on first use)."""
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
            logger.info("[Embeddings] Loading all-MiniLM-L6-v2 model...")
            _model = SentenceTransformer("all-MiniLM-L6-v2")
            logger.info("[Embeddings] Model loaded successfully.")
        except Exception as e:
            logger.error(f"[Embeddings] Failed to load model: {e}")
            raise
    return _model


def cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    norm_a = np.linalg.norm(vec_a)
    norm_b = np.linalg.norm(vec_b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(vec_a, vec_b) / (norm_a * norm_b))


def compute_semantic_similarity(
    jd_skills: List[str],
    candidate_skills: List[str],
    jd_responsibilities: List[str] = None,
    candidate_projects: List[str] = None,
) -> float:
    """
    Compute overall semantic relevance between JD and candidate.

    Strategy:
    1. Embed concatenated JD skills/responsibilities as one text.
    2. Embed concatenated candidate skills/projects as one text.
    3. Return cosine similarity.

    Returns:
        Float in [0.0, 1.0]
    """
    try:
        model = _get_model()

        # Build JD representation text
        jd_parts = jd_skills + (jd_responsibilities or [])
        jd_text = " | ".join(jd_parts) if jd_parts else "general software engineering role"

        # Build candidate representation text
        cand_parts = candidate_skills + (candidate_projects or [])
        cand_text = " | ".join(cand_parts) if cand_parts else "general software skills"

        # Generate embeddings
        embeddings = model.encode([jd_text, cand_text], show_progress_bar=False)
        sim = cosine_similarity(embeddings[0], embeddings[1])

        logger.debug(f"[Embeddings] Semantic similarity: {sim:.4f}")
        return round(sim, 4)

    except Exception as e:
        logger.error(f"[Embeddings] Similarity computation failed: {e}")
        return 0.0


def compute_skill_overlap(jd_skills: List[str], candidate_skills: List[str]) -> float:
    """
    Exact + fuzzy skill overlap score (0–1).
    Used as a fast supplement to semantic similarity.
    """
    if not jd_skills or not candidate_skills:
        return 0.0

    jd_lower = {s.lower().strip() for s in jd_skills}
    cand_lower = {s.lower().strip() for s in candidate_skills}

    exact_matches = jd_lower & cand_lower
    exact_score = len(exact_matches) / len(jd_lower)

    # Partial match: check if any JD skill is substring of any candidate skill or vice versa
    partial = 0
    for jd_skill in jd_lower - exact_matches:
        for cand_skill in cand_lower:
            if jd_skill in cand_skill or cand_skill in jd_skill:
                partial += 1
                break

    partial_score = partial / len(jd_lower) if jd_lower else 0.0

    combined = (exact_score * 0.7) + (partial_score * 0.3)
    logger.debug(f"[Embeddings] Skill overlap: exact={exact_score:.2f} partial={partial_score:.2f} combined={combined:.2f}")
    return round(combined, 4)
