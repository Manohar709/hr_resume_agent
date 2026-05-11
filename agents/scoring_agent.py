"""
agents/scoring_agent.py
-----------------------
Scoring Agent — applies rubric weights and LLM reasoning to score candidates.
Combines semantic similarity + LLM judgment + confidence bonuses.
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional

from schemas.pydantic_models import CandidateProfile, JDRequirements, CandidateScore
from utils.logging_utils import log_stage

logger = logging.getLogger(__name__)

PROMPT_PATH = Path("prompts/scoring_prompt.txt")

WEIGHTS = {
    "skills_match": 0.30,
    "experience_relevance": 0.25,
    "education_certs": 0.15,
    "project_relevance": 0.20,
    "communication_quality": 0.10,
}


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        inner = lines[1:-1] if lines and lines[-1].strip() == "```" else lines[1:]
        text = "\n".join(inner).strip()
    return text


class ScoringAgent:
    """
    Scores a candidate against a JD using a weighted rubric.
    Combines LLM scoring with pre-computed semantic similarity.
    """

    def __init__(self, llm):
        self.llm = llm
        self.prompt_template = self._load_prompt()

    def _load_prompt(self) -> str:
        try:
            return PROMPT_PATH.read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.error(f"Scoring prompt not found at {PROMPT_PATH}")
            return ""

    def score(
        self,
        candidate: CandidateProfile,
        jd: JDRequirements,
        file_hash: str,
        semantic_score: float = 0.0,
    ) -> Optional[CandidateScore]:
        """
        Score a single candidate against the JD.

        Args:
            candidate: Parsed candidate profile.
            jd: Parsed JD requirements.
            file_hash: SHA256 hash of the resume file.
            semantic_score: Pre-computed cosine similarity score.

        Returns:
            CandidateScore or None on failure.
        """
        start = time.time()

        jd_json = jd.model_dump_json(indent=2)
        cand_json = candidate.model_dump_json(indent=2)

        prompt = self.prompt_template.format(
            jd_json=jd_json,
            candidate_json=cand_json,
            semantic_score=f"{semantic_score:.4f}",
        )

        try:
            response = self.llm.invoke(prompt)
            raw_output = response.content if hasattr(response, "content") else str(response)
            raw_output = _strip_json_fences(raw_output)

            data = json.loads(raw_output)

            # Inject fields that come from our pipeline, not LLM
            data["candidate_name"] = candidate.name
            data["file_hash"] = file_hash
            data["semantic_similarity"] = semantic_score

            # Validate and clamp dimension weights
            for dim in data.get("dimension_scores", []):
                expected_weight = WEIGHTS.get(dim.get("dimension", ""), 0.0)
                if expected_weight:
                    dim["weight"] = expected_weight  # enforce our weights, don't trust LLM
                    dim["weighted_score"] = round(dim["raw_score"] * expected_weight, 4)

            # Recalculate total from dimensions to ensure consistency
            total = sum(d.get("weighted_score", 0) for d in data.get("dimension_scores", []))
            bonus = float(data.get("confidence_bonus", 0.0))
            data["total_weighted_score"] = round(min(total + bonus, 10.0), 2)

            cs = CandidateScore(**data)
            cs.processing_time_ms = (time.time() - start) * 1000

            elapsed = (time.time() - start) * 1000
            log_stage(
                stage="scoring_agent",
                model_name="gemini-2.5-flash",
                latency_ms=elapsed,
                extra={
                    "candidate": candidate.name,
                    "score": cs.total_weighted_score,
                    "recommendation": cs.recommendation,
                },
            )
            logger.info(
                f"[Scoring] ✓ {candidate.name} → {cs.total_weighted_score}/10 | {cs.recommendation}"
            )
            return cs

        except json.JSONDecodeError as e:
            elapsed = (time.time() - start) * 1000
            log_stage(stage="scoring_agent", latency_ms=elapsed, error=f"JSON decode: {e}")
            logger.error(f"[Scoring] JSON parse failed for {candidate.name}: {e}")
            return _fallback_score(candidate, file_hash, semantic_score)

        except Exception as e:
            elapsed = (time.time() - start) * 1000
            log_stage(stage="scoring_agent", latency_ms=elapsed, error=str(e))
            logger.error(f"[Scoring] Error scoring {candidate.name}: {e}")
            return _fallback_score(candidate, file_hash, semantic_score)


def _fallback_score(
    candidate: CandidateProfile,
    file_hash: str,
    semantic_score: float,
) -> CandidateScore:
    """
    Generate a basic rule-based fallback score when LLM fails.
    Ensures the pipeline never crashes.
    """
    logger.warning(f"[Scoring] Using fallback score for {candidate.name}")

    # Simple heuristic scoring
    skill_score = min(len(candidate.skills) * 0.5, 7.0)
    exp_score = min((candidate.experience_years or 0) * 1.0, 8.0)
    edu_score = 5.0  # neutral
    proj_score = min(len(candidate.projects) * 1.5, 7.0)
    comm_map = {"poor": 3.0, "average": 5.0, "good": 7.0, "excellent": 9.0}
    comm_score = comm_map.get(candidate.communication_quality, 5.0)

    bonus = 0.0
    if candidate.github:
        bonus += 0.2
    if candidate.achievements:
        bonus += 0.2

    dims = [
        {"dimension": "skills_match", "raw_score": skill_score, "weight": 0.30,
         "weighted_score": skill_score * 0.30, "justification": "Fallback: skill count heuristic"},
        {"dimension": "experience_relevance", "raw_score": exp_score, "weight": 0.25,
         "weighted_score": exp_score * 0.25, "justification": "Fallback: experience years"},
        {"dimension": "education_certs", "raw_score": edu_score, "weight": 0.15,
         "weighted_score": edu_score * 0.15, "justification": "Fallback: neutral"},
        {"dimension": "project_relevance", "raw_score": proj_score, "weight": 0.20,
         "weighted_score": proj_score * 0.20, "justification": "Fallback: project count"},
        {"dimension": "communication_quality", "raw_score": comm_score, "weight": 0.10,
         "weighted_score": comm_score * 0.10, "justification": "Fallback: communication quality"},
    ]

    total = sum(d["weighted_score"] for d in dims) + bonus

    return CandidateScore(
        candidate_name=candidate.name,
        file_hash=file_hash,
        dimension_scores=dims,
        semantic_similarity=semantic_score,
        confidence_bonus=bonus,
        total_weighted_score=round(min(total, 10.0), 2),
        strengths=candidate.achievements[:2] if candidate.achievements else ["Profile parsed"],
        weaknesses=["LLM scoring unavailable — heuristic used"],
        recommendation="Maybe",
    )
