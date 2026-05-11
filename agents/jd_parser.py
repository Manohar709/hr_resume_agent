"""
agents/jd_parser.py
-------------------
JD Parser Agent — extracts structured requirements from job description text.
Uses Gemini 2.0 Flash via LangChain with Pydantic validation.
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional

from schemas.pydantic_models import JDRequirements
from utils.validation import sanitize_text
from utils.logging_utils import log_stage

logger = logging.getLogger(__name__)

PROMPT_PATH = Path("prompts/jd_prompt.txt")


class JDParserAgent:
    """
    Parses a job description PDF text into structured JDRequirements.
    Uses Gemini 2.0 Flash with temperature=0 for deterministic output.
    """

    def __init__(self, llm):
        self.llm = llm
        self.prompt_template = self._load_prompt()

    def _load_prompt(self) -> str:
        try:
            return PROMPT_PATH.read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.error(f"JD prompt not found at {PROMPT_PATH}")
            return ""

    def parse(self, jd_text: str) -> Optional[JDRequirements]:
        """
        Parse JD text into a structured JDRequirements object.

        Args:
            jd_text: Raw text extracted from JD PDF.

        Returns:
            JDRequirements on success, None on failure.
        """
        start = time.time()

        # Sanitize to prevent prompt injection
        clean_text = sanitize_text(jd_text, max_length=15_000)

        if len(clean_text) < 50:
            logger.warning("[JDParser] JD text too short — possibly empty PDF.")
            return None

        prompt = self.prompt_template.format(jd_text=clean_text)

        try:
            response = self.llm.invoke(prompt)
            raw_output = response.content if hasattr(response, "content") else str(response)

            # Strip markdown fences if model ignores instructions
            raw_output = _strip_json_fences(raw_output)

            data = json.loads(raw_output)
            jd = JDRequirements(**data)

            elapsed = (time.time() - start) * 1000
            log_stage(
                stage="jd_parser",
                model_name="gemini-2.5-flash",
                latency_ms=elapsed,
                extra={"role": jd.role_title, "required_skills_count": len(jd.required_skills)},
            )
            logger.info(f"[JDParser] ✓ Parsed: {jd.role_title} | {len(jd.required_skills)} required skills")
            return jd

        except json.JSONDecodeError as e:
            elapsed = (time.time() - start) * 1000
            log_stage(stage="jd_parser", latency_ms=elapsed, error=f"JSON decode error: {e}")
            logger.error(f"[JDParser] JSON parse failed: {e}\nRaw output: {raw_output[:300]}")
            return None

        except Exception as e:
            elapsed = (time.time() - start) * 1000
            log_stage(stage="jd_parser", latency_ms=elapsed, error=str(e))
            logger.error(f"[JDParser] Unexpected error: {e}")
            return None


def _strip_json_fences(text: str) -> str:
    """Remove ```json ... ``` or ``` ... ``` wrappers if present."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Drop first line (```json or ```) and last line (```)
        inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        text = "\n".join(inner).strip()
    return text
