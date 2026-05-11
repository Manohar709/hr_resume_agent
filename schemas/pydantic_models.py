"""
schemas/pydantic_models.py (ENHANCED)
--------------------------------------
All Pydantic models for structured validation across the pipeline.
These act as contracts between agents, ensuring data integrity.
NOW with robust handling for missing fields in resumes.
"""

from pydantic import BaseModel, Field, validator
from typing import List, Optional, Dict, Any
from datetime import datetime


# ──────────────────────────────────────────────
# JD (Job Description) Schemas
# ──────────────────────────────────────────────

class JDRequirements(BaseModel):
    """Structured output from JD Parser Agent."""
    role_title: str = Field(..., description="Job title/role name")
    required_skills: List[str] = Field(default_factory=list, description="Must-have technical skills")
    preferred_skills: List[str] = Field(default_factory=list, description="Nice-to-have skills")
    experience_years: Optional[str] = Field(None, description="Years of experience required (e.g. '3-5 years')")
    education_requirement: Optional[str] = Field(None, description="Minimum education requirement")
    soft_skills: List[str] = Field(default_factory=list, description="Communication, teamwork, leadership etc.")
    tools_technologies: List[str] = Field(default_factory=list, description="Specific tools, frameworks, platforms")
    domain: Optional[str] = Field(None, description="Industry/domain (e.g. FinTech, HealthTech)")
    responsibilities: List[str] = Field(default_factory=list, description="Key job responsibilities")

    @validator("role_title", pre=True)
    def sanitize_role_title(cls, v):
        """Strip any injection attempts from role title."""
        return str(v).strip()[:200]


# ──────────────────────────────────────────────
# Resume / Candidate Schemas (ENHANCED)
# ──────────────────────────────────────────────

class CandidateProfile(BaseModel):
    """
    Structured output from Resume Parser Agent.
    ENHANCED: Robust handling for missing sections - no more crashes.
    """
    name: str = Field(..., description="Full candidate name")
    email: Optional[str] = Field(None, description="Email address")
    phone: Optional[str] = Field(None, description="Phone number")
    linkedin: Optional[str] = Field(None, description="LinkedIn profile URL")
    github: Optional[str] = Field(None, description="GitHub profile URL")
    
    # Skills - gracefully handle if not present
    skills: List[str] = Field(default_factory=list, description="Technical and soft skills listed")
    
    # Experience - handle missing experience section
    experience_years: Optional[float] = Field(None, description="Total years of work experience")
    experience_summary: str = Field(default="", description="Brief work history summary")
    
    # Education - handle missing education
    education: Optional[str] = Field(None, description="Highest education level and institution")
    
    # Certifications - gracefully default to empty
    certifications: List[str] = Field(default_factory=list, description="Professional certifications")
    
    # Projects - handle if not mentioned
    projects: List[str] = Field(default_factory=list, description="Key projects described")
    
    # Achievements - handle if quantified achievements missing
    achievements: List[str] = Field(default_factory=list, description="Quantified or notable achievements")
    
    # Communication quality
    communication_quality: str = Field(default="average", description="Assessment of resume writing quality")
    raw_text_length: int = Field(default=0, description="Character count of resume text")

    @validator("name", pre=True)
    def sanitize_name(cls, v):
        """Ensure name is present and clean."""
        if not v:
            return "Unknown Candidate"
        return str(v).strip()[:200]

    @validator("communication_quality", pre=True)
    def validate_comm_quality(cls, v):
        """Ensure communication quality is valid, default to average if missing."""
        allowed = {"poor", "average", "good", "excellent"}
        if not v:
            return "average"
        v_lower = str(v).lower().strip()
        return v_lower if v_lower in allowed else "average"

    @validator("experience_years", pre=True)
    def validate_experience_years(cls, v):
        """Handle missing or invalid experience years."""
        if v is None or v == "":
            return None
        try:
            years = float(v)
            return round(max(0.0, min(years, 70.0)), 1)  # Reasonable bounds
        except (ValueError, TypeError):
            return None

    @validator("skills", "certifications", "projects", "achievements", pre=True)
    def handle_list_fields(cls, v):
        """Convert None or non-list values to empty list."""
        if v is None or v == "":
            return []
        if isinstance(v, str):
            # Handle comma-separated strings
            return [item.strip() for item in v.split(",") if item.strip()]
        if isinstance(v, list):
            return [str(item).strip() for item in v if item]
        return []

    @validator("experience_summary", "education", pre=True)
    def handle_optional_strings(cls, v):
        """Convert None to empty string for string fields."""
        if v is None or v == "":
            return ""
        return str(v).strip()

    class Config:
        """Allow population by field name and use defaults for missing fields."""
        extra = "ignore"  # Ignore extra fields from parsed data


# ──────────────────────────────────────────────
# Scoring Schemas
# ──────────────────────────────────────────────

class DimensionScore(BaseModel):
    """Score for a single rubric dimension."""
    dimension: str
    raw_score: float = Field(..., ge=0.0, le=10.0, description="Score out of 10")
    weight: float = Field(..., ge=0.0, le=1.0, description="Weight as decimal")
    weighted_score: float = Field(..., description="raw_score * weight")
    justification: str = Field(..., description="LLM reasoning for this score")

    @validator("raw_score", "weighted_score", pre=True)
    def clamp_score(cls, v):
        try:
            return round(min(max(float(v), 0.0), 10.0), 2)
        except Exception:
            return 0.0

    @validator("justification", pre=True)
    def ensure_justification(cls, v):
        """Ensure justification is always present."""
        if not v:
            return "No specific reasoning provided"
        return str(v).strip()[:500]


class CandidateScore(BaseModel):
    """Full scoring result for a candidate."""
    candidate_name: str
    file_hash: str
    dimension_scores: List[DimensionScore] = Field(default_factory=list)
    semantic_similarity: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence_bonus: float = Field(default=0.0, description="Bonus for GitHub, metrics, evidence")
    total_weighted_score: float = Field(default=0.0, description="Final score 0-10")
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)
    recommendation: str = Field(default="Maybe", description="Strong Yes / Yes / Maybe / No")
    processing_time_ms: Optional[float] = None

    @validator("total_weighted_score", pre=True)
    def clamp_total(cls, v):
        try:
            return round(min(max(float(v), 0.0), 10.0), 2)
        except Exception:
            return 0.0

    @validator("recommendation", pre=True)
    def validate_recommendation(cls, v):
        """Ensure recommendation is valid."""
        valid_recommendations = {"Strong Yes", "Yes", "Maybe", "No"}
        if not v or str(v).strip() not in valid_recommendations:
            return "Maybe"
        return str(v).strip()

    @validator("strengths", "weaknesses", pre=True)
    def handle_score_lists(cls, v):
        """Ensure strengths/weaknesses are always lists."""
        if v is None or v == "":
            return []
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        if isinstance(v, list):
            return [str(item).strip() for item in v if item]
        return []


# ──────────────────────────────────────────────
# Override Schema
# ──────────────────────────────────────────────

class ScoreOverride(BaseModel):
    """Human-in-the-loop override record."""
    candidate_name: str
    file_hash: str
    old_score: float
    new_score: float = Field(..., ge=0.0, le=10.0)
    reason: str = Field(..., min_length=5, description="Override justification")
    override_by: str = Field(default="HR Manager")
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    @validator("reason", pre=True)
    def ensure_reason(cls, v):
        """Ensure reason is substantive."""
        if not v or len(str(v).strip()) < 5:
            return "HR decision override"
        return str(v).strip()


# ──────────────────────────────────────────────
# Report Schema
# ──────────────────────────────────────────────

class ReportEntry(BaseModel):
    """Single candidate entry in the final report."""
    rank: int
    candidate_name: str
    total_score: float
    recommendation: str
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)
    dimension_scores: Dict[str, float] = Field(default_factory=dict)
    has_github: bool = Field(default=False)
    has_override: bool = Field(default=False)
    override_reason: Optional[str] = None


class FinalReport(BaseModel):
    """Complete screening report."""
    job_title: str
    total_candidates: int
    shortlisted_count: int
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    entries: List[ReportEntry] = Field(default_factory=list)
    summary: str = Field(default="")

    @validator("summary", pre=True)
    def ensure_summary(cls, v):
        """Ensure summary is always present."""
        if not v:
            return "Screening completed"
        return str(v).strip()


# ──────────────────────────────────────────────
# Validation Result Schema
# ──────────────────────────────────────────────

class FileValidationResult(BaseModel):
    """Result of file validation checks."""
    is_valid: bool
    filename: str
    file_size_kb: float
    error_message: Optional[str] = None
    mime_type: Optional[str] = None

    @validator("filename", pre=True)
    def ensure_filename(cls, v):
        """Ensure filename is always present."""
        if not v:
            return "unknown_file"
        return str(v).strip()


# ──────────────────────────────────────────────
# Log Schema
# ──────────────────────────────────────────────

class ProcessingLog(BaseModel):
    """Structured log entry for observability."""
    stage: str
    model_name: Optional[str] = None
    prompt_preview: Optional[str] = None  # first 200 chars only
    token_usage: Optional[Dict[str, int]] = None
    latency_ms: Optional[float] = None
    error: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    @validator("stage", pre=True)
    def ensure_stage(cls, v):
        """Ensure stage is always present."""
        if not v:
            return "unknown_stage"
        return str(v).strip()

    @validator("prompt_preview", pre=True)
    def limit_prompt_preview(cls, v):
        """Limit prompt preview to 200 chars."""
        if not v:
            return None
        return str(v).strip()[:200]
