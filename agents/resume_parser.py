"""
agents/resume_parser.py
-----------------------
Resume Parser Agent — extracts structured candidate data from resume text.
Handles batch processing; continues if individual resumes fail.
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional

from schemas.pydantic_models import CandidateProfile
from utils.validation import sanitize_text
from utils.logging_utils import log_stage

logger = logging.getLogger(__name__)

PROMPT_PATH = Path("prompts/resume_prompt.txt")


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        inner = lines[1:-1] if lines and lines[-1].strip() == "```" else lines[1:]
        text = "\n".join(inner).strip()
    return text


class ResumeParserAgent:
    """
    Parses individual resume text into a CandidateProfile.
    Designed to be called per-resume in a batch loop.
    """

    def __init__(self, llm):
        self.llm = llm
        self.prompt_template = self._load_prompt()

    def _load_prompt(self) -> str:
        try:
            return PROMPT_PATH.read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.error(f"Resume prompt not found at {PROMPT_PATH}")
            return ""

    def parse(self, resume_text: str, filename: str = "unknown") -> Optional[CandidateProfile]:
        """
        Parse resume text into a CandidateProfile.

        Args:
            resume_text: Raw text from PDF.
            filename: Used for logging context.

        Returns:
            CandidateProfile on success, None on failure.
        """
        start = time.time()

        # Sanitize input
        clean_text = sanitize_text(resume_text, max_length=12_000)

        if len(clean_text) < 30:
            logger.warning(f"[ResumeParser] Resume too short ({filename}), skipping.")
            return None

        prompt = self.prompt_template.format(resume_text=clean_text)

        try:
            response = self.llm.invoke(prompt)
            raw_output = response.content if hasattr(response, "content") else str(response)
            raw_output = _strip_json_fences(raw_output)

            data = json.loads(raw_output)

            # Inject metadata
            data["raw_text_length"] = len(resume_text)

            profile = CandidateProfile(**data)

            elapsed = (time.time() - start) * 1000
            log_stage(
                stage="resume_parser",
                model_name="gemini-2.5-flash",
                latency_ms=elapsed,
                extra={"file": filename, "candidate": profile.name, "skills": len(profile.skills)},
            )
            logger.info(
                f"[ResumeParser] ✓ {profile.name} | {len(profile.skills)} skills | "
                f"{profile.experience_years}y exp | {filename}"
            ) 
            return profile

        except json.JSONDecodeError as e:
            elapsed = (time.time() - start) * 1000
            log_stage(stage="resume_parser", latency_ms=elapsed, error=f"JSON decode error: {e}", extra={"file": filename})
            logger.error(f"[ResumeParser] JSON parse failed for {filename}: {e}")
            return None

        except Exception as e:
            elapsed = (time.time() - start) * 1000
            log_stage(stage="resume_parser", latency_ms=elapsed, error=str(e), extra={"file": filename})
            logger.error(f"[ResumeParser] Error parsing {filename}: {e}")
            return None
