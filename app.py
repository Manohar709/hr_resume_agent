"""
app.py
------
AI HR Resume Screening Agent — Streamlit Frontend
Production-style, modular, beginner-friendly.

Run:
    streamlit run app.py
"""

import os
import io
import json
import logging
import time
from pathlib import Path
from typing import List, Optional

import streamlit as st
from dotenv import load_dotenv

# ── Bootstrap ──────────────────────────────────────────────────────────────────
load_dotenv()

# Must happen before any LangChain imports
from utils.cache_utils import setup_llm_cache
from utils.logging_utils import setup_logging
from database.db import init_db

setup_logging()
setup_llm_cache()
init_db()

logger = logging.getLogger(__name__)

# ── LangChain / Gemini ─────────────────────────────────────────────────────────
from langchain_google_genai import ChatGoogleGenerativeAI

# ── Internal modules ───────────────────────────────────────────────────────────
from utils.pdf_utils import extract_text_from_pdf
from utils.validation import validate_uploaded_file
from utils.hashing import compute_sha256, compute_text_hash
from database.db import (
    is_duplicate, register_hash, save_resume, get_cached_resume,
    save_score, get_cached_score, save_override, get_override,
)
from agents.jd_parser import JDParserAgent
from agents.resume_parser import ResumeParserAgent
from agents.scoring_agent import ScoringAgent
from agents.ranking_agent import rank_candidates, get_shortlist
from agents.report_generator import generate_json_report, generate_html_report, generate_pdf_report
from embeddings.similarity_engine import compute_semantic_similarity, compute_skill_overlap
from schemas.pydantic_models import CandidateScore, JDRequirements


# ── Page Config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="AI HR Resume Screener",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  .main { background: #f8faff; }
  .stButton > button {
    background: linear-gradient(135deg, #1e3a8a, #3b82f6);
    color: white; border: none; border-radius: 8px;
    padding: 0.5rem 1.5rem; font-weight: 600; transition: all 0.2s;
  }
  .stButton > button:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(59,130,246,0.4); }
  .metric-card {
    background: white; border-radius: 12px; padding: 1.2rem;
    box-shadow: 0 2px 12px rgba(0,0,0,0.08); text-align: center;
  }
  .score-badge {
    display: inline-block; padding: 4px 14px; border-radius: 20px;
    font-weight: 700; font-size: 14px;
  }
  .rank-header {
    background: linear-gradient(135deg, #1e3a8a, #3b82f6);
    color: white; padding: 12px 20px; border-radius: 10px; margin-bottom: 8px;
  }
</style>
""", unsafe_allow_html=True)


# ── Helper: LLM Factory ────────────────────────────────────────────────────────
@st.cache_resource
def get_llm():
    """Create and cache the Gemini LLM instance (created ONCE, not per rerun)."""
    api_key = os.getenv("GOOGLE_API_KEY", "")
    if not api_key:
        st.error("❌ GOOGLE_API_KEY not found in .env file.")
        st.stop()
    return ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        temperature=0,
        google_api_key=api_key,
        convert_system_message_to_human=True,
    )


# ── Session State Init ─────────────────────────────────────────────────────────
def init_session():
    defaults = {
        "jd": None,               # JDRequirements (parsed)
        "jd_hash": "",
        "jd_text": "",
        "jd_bytes": None,         # FIX: store raw bytes so file isn't re-read after rerun
        "resume_bytes_map": {},   # FIX: {filename: bytes} — read once, reuse across reruns
        "candidates": [],
        "scores": [],
        "ranked": [],
        "processing_done": False,
        "stage_log": [],
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


init_session()


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.image("https://img.icons8.com/color/96/artificial-intelligence.png", width=64)
    st.title("⚙️ Settings")
    st.divider()

    min_score_threshold = st.slider("Shortlist Min Score", 0.0, 10.0, 5.0, 0.5)
    top_n = st.number_input("Max Candidates to Show", 1, 50, 20, 1)
    show_all = st.checkbox("Show ALL candidates (ignore threshold)", value=False)

    st.divider()
    st.markdown("**Model:** Gemini 2.0 Flash")
    st.markdown("**Embeddings:** all-MiniLM-L6-v2")
    st.markdown("**Cache:** SQLite (LangChain)")

    st.divider()
    st.markdown("### 📊 Rubric Weights")
    st.markdown("""
    | Dimension | Weight |
    |-----------|--------|
    | Skills Match | 30% |
    | Experience | 25% |
    | Projects | 20% |
    | Education | 15% |
    | Communication | 10% |
    """)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN HEADER
# ══════════════════════════════════════════════════════════════════════════════

st.markdown("""
<div style="background:linear-gradient(135deg,#1e3a8a,#3b82f6);padding:2rem;border-radius:16px;margin-bottom:2rem;color:white;">
  <h1 style="margin:0;font-size:2.2rem;">🧠 AI HR Resume Screening Agent</h1>
  <p style="margin:0.5rem 0 0;opacity:0.9;font-size:1.1rem;">
    Upload a Job Description and Resumes — get ranked candidates with AI-powered insights.
  </p>
</div>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1: UPLOAD SECTION
# ══════════════════════════════════════════════════════════════════════════════

col1, col2 = st.columns([1, 2], gap="large")

with col1:
    st.subheader("📄 Step 1: Upload Job Description")
    jd_file = st.file_uploader(
        "Upload JD PDF",
        type=["pdf"],
        key="jd_uploader",
        help="Upload a single job description PDF (max 10 MB)",
    )

    if jd_file:
        st.success(f"✅ {jd_file.name} ({jd_file.size / 1024:.1f} KB)")
        # FIX: Read bytes immediately on upload and store in session_state.
        # file_uploader objects are ephemeral — .read() returns empty after a rerun
        # unless you store the bytes yourself.
        st.session_state["jd_bytes"] = jd_file.read()

with col2:
    st.subheader("📂 Step 2: Upload Resumes")
    resume_files = st.file_uploader(
        "Upload Resume PDFs (multiple allowed)",
        type=["pdf"],
        accept_multiple_files=True,
        key="resume_uploader",
        help="Upload up to 50 resume PDFs (max 10 MB each)",
    )

    if resume_files:
        st.success(f"✅ {len(resume_files)} resume(s) uploaded")
        # FIX: Read and cache ALL resume bytes immediately — same reason as above.
        # Store as {filename: bytes} so we can look them up by name later.
        for rf in resume_files:
            if rf.name not in st.session_state["resume_bytes_map"]:
                st.session_state["resume_bytes_map"][rf.name] = rf.read()

        with st.expander("📋 Uploaded files"):
            for f in resume_files:
                st.markdown(f"- `{f.name}` ({f.size / 1024:.1f} KB)")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3: RUN SCREENING
# ══════════════════════════════════════════════════════════════════════════════

st.divider()
run_col, clear_col = st.columns([3, 1])

with run_col:
    run_button = st.button("🚀 Run AI Screening", use_container_width=True)
with clear_col:
    if st.button("🗑️ Clear Results", use_container_width=True):
        keys_to_reset = [
            "jd", "jd_hash", "jd_text", "jd_bytes",
            "resume_bytes_map", "candidates", "scores",
            "ranked", "processing_done", "stage_log"
        ]
        for key in keys_to_reset:
            if key in ["jd", "jd_bytes"]:
                st.session_state[key] = None
            elif key == "resume_bytes_map":
                st.session_state[key] = {}
            elif isinstance(st.session_state.get(key), list):
                st.session_state[key] = []
            elif isinstance(st.session_state.get(key), bool):
                st.session_state[key] = False
            else:
                st.session_state[key] = ""
        st.rerun()


# ── GUARD: Only run screening logic when button is explicitly clicked ──────────
# FIX: All processing is INSIDE this if block. Nothing runs on passive reruns.
if run_button:
    # ── Validate uploads are available ────────────────────────────────────────
    jd_bytes = st.session_state.get("jd_bytes")
    resume_bytes_map = st.session_state.get("resume_bytes_map", {})

    if not jd_bytes:
        st.error("❌ Please upload a Job Description PDF first.")
        st.stop()
    if not resume_bytes_map:
        st.error("❌ Please upload at least one resume PDF.")
        st.stop()

    llm = get_llm()  # Fetches from @st.cache_resource — no re-init
    jd_agent = JDParserAgent(llm)
    resume_agent = ResumeParserAgent(llm)
    scoring_agent = ScoringAgent(llm)

    progress = st.progress(0, text="Starting AI screening...")
    status = st.empty()

    # ── STEP A: Validate & Parse JD ───────────────────────────────────────────
    status.info("📄 Validating and parsing Job Description...")

    jd_filename = jd_file.name if jd_file else "job_description.pdf"
    is_valid, err = validate_uploaded_file(jd_filename, jd_bytes)
    if not is_valid:
        st.error(f"❌ JD upload failed: {err}")
        st.stop()

    jd_text, ok = extract_text_from_pdf(jd_bytes, jd_filename)
    if not ok or len(jd_text) < 50:
        st.error("❌ Could not extract text from JD PDF. Is it a scanned image?")
        st.stop()

    # ── FIX: JD cache check is INSIDE run_button block (was incorrectly de-dented) ──
    jd_hash = compute_text_hash(jd_text)

    if (
        st.session_state.get("jd") is not None
        and st.session_state.get("jd_hash") == jd_hash
    ):
        # Same JD uploaded again — reuse parsed result, skip API call
        jd = st.session_state["jd"]
        st.info("💾 JD loaded from session cache (no API call made)")
    else:
        with st.spinner("🤖 LLM parsing Job Description..."):
            jd = jd_agent.parse(jd_text)

        if not jd:
            st.error("❌ LLM failed to parse the JD.")
            st.stop()

        st.session_state["jd"] = jd
        st.session_state["jd_hash"] = jd_hash

    progress.progress(10, text=f"✅ JD parsed: {jd.role_title}")
    st.success(f"✅ Job Description parsed: **{jd.role_title}**")

    # ── STEP B: Process Resumes ───────────────────────────────────────────────
    # FIX: Iterate over stored bytes map, not the file_uploader objects
    # (which may be stale / unreadable after a rerun).
    total = len(resume_bytes_map)
    processed_candidates = []
    processed_scores = []
    skipped_duplicates = 0
    skipped_invalid = 0

    for i, (resume_name, res_bytes) in enumerate(resume_bytes_map.items()):
        pct = 10 + int((i / total) * 60)
        status.info(f"📝 Processing resume {i+1}/{total}: `{resume_name}`")
        progress.progress(pct, text=f"Processing resume {i+1}/{total}...")

        # Validate
        is_valid, err = validate_uploaded_file(resume_name, res_bytes)
        if not is_valid:
            st.warning(f"⚠️ Skipping `{resume_name}`: {err}")
            skipped_invalid += 1
            continue

        # Duplicate detection
        file_hash = compute_sha256(res_bytes)
        if is_duplicate(file_hash):
            st.info(f"♻️ Skipping duplicate: `{resume_name}`")
            skipped_duplicates += 1
            continue
        register_hash(file_hash, resume_name)

        # FIX: Check DB cache BEFORE making any LLM call —
        # same resume + same JD hash means we already scored this pair.
        cached_profile = get_cached_resume(file_hash, jd_hash)
        cached_score = get_cached_score(file_hash, jd_hash)

        if cached_profile and cached_score:
            from schemas.pydantic_models import CandidateProfile
            profile = CandidateProfile(**cached_profile)
            score = CandidateScore(**cached_score)
            st.info(f"💾 Loaded from DB cache: `{resume_name}` (no API call)")
            processed_candidates.append(profile)
            processed_scores.append(score)
            continue

        # Extract text
        res_text, ok = extract_text_from_pdf(res_bytes, resume_name)
        if not ok or len(res_text) < 30:
            st.warning(f"⚠️ Skipping `{resume_name}`: could not extract text.")
            skipped_invalid += 1
            continue

        # Parse resume via LLM (only reaches here on cache miss)
        profile = resume_agent.parse(res_text, filename=resume_name)
        if not profile:
            st.warning(f"⚠️ Could not parse `{resume_name}`. Skipping.")
            skipped_invalid += 1
            continue

        # Semantic similarity (local model — no API cost)
        sem_sim = compute_semantic_similarity(
            jd_skills=jd.required_skills + jd.preferred_skills,
            candidate_skills=profile.skills,
            jd_responsibilities=jd.responsibilities,
            candidate_projects=profile.projects,
        )
        skill_overlap = compute_skill_overlap(
            jd_skills=jd.required_skills,
            candidate_skills=profile.skills,
        )
        blended_sim = round(sem_sim * 0.6 + skill_overlap * 0.4, 4)

        # Score via LLM
        score = scoring_agent.score(profile, jd, file_hash, semantic_score=blended_sim)
        if not score:
            skipped_invalid += 1
            continue

        # Persist to DB so next run is a cache hit
        save_resume(file_hash, resume_name, profile.model_dump(), jd_hash)
        save_score(file_hash, profile.name, score.model_dump(), jd_hash)

        processed_candidates.append(profile)
        processed_scores.append(score)

    st.session_state["candidates"] = processed_candidates
    st.session_state["scores"] = processed_scores

    # ── STEP C: Rank ──────────────────────────────────────────────────────────
    status.info("📊 Ranking candidates...")
    progress.progress(80, text="Ranking candidates...")

    ranked = rank_candidates(processed_scores)
    st.session_state["ranked"] = ranked
    st.session_state["processing_done"] = True

    progress.progress(100, text="✅ Screening complete!")
    status.success(
        f"✅ Done! Processed **{len(processed_candidates)}** candidates | "
        f"{skipped_duplicates} duplicates | {skipped_invalid} invalid"
    )


# ══════════════════════════════════════════════════════════════════════════════
# RESULTS DASHBOARD — reads only from session_state, zero API calls here
# ══════════════════════════════════════════════════════════════════════════════

if st.session_state.get("processing_done") and st.session_state.get("ranked"):
    jd = st.session_state["jd"]
    ranked = st.session_state["ranked"]

    st.divider()
    st.header(f"🏆 Screening Results — {jd.role_title}")

    # ── Summary Metrics ────────────────────────────────────────────────────────
    total_cands = len(ranked)
    shortlisted = [r for r in ranked if r[1].total_weighted_score >= min_score_threshold]
    avg_score = sum(r[1].total_weighted_score for r in ranked) / total_cands if total_cands else 0
    top_score = ranked[0][1].total_weighted_score if ranked else 0

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("Total Candidates", total_cands)
    with m2:
        st.metric("Shortlisted", len(shortlisted))
    with m3:
        st.metric("Avg Score", f"{avg_score:.1f}/10")
    with m4:
        st.metric("Top Score", f"{top_score:.1f}/10")

    st.divider()

    # ── Candidate Cards ────────────────────────────────────────────────────────
    display_ranked = ranked if show_all else shortlisted
    display_ranked = display_ranked[:int(top_n)]

    if not display_ranked:
        st.warning(f"No candidates scored above {min_score_threshold}. Lower the threshold or toggle 'Show All'.")
    else:
        st.subheader(f"📋 Ranked Candidates ({len(display_ranked)} shown)")

        for rank, score, override in display_ranked:
            eff_score = override.get("new_score", score.total_weighted_score) if override else score.total_weighted_score

            rec_colors = {
                "Strong Yes": "🟢", "Yes": "🔵", "Maybe": "🟡", "No": "🔴"
            }
            rec_icon = rec_colors.get(score.recommendation, "⚪")

            with st.expander(
                f"{rec_icon} #{rank}  {score.candidate_name}  —  **{eff_score:.1f}/10**  {score.recommendation}"
                + ("  ⚡ Overridden" if override else ""),
                expanded=(rank <= 3),
            ):
                col_a, col_b, col_c = st.columns([2, 2, 1])

                with col_a:
                    st.markdown("**📊 Dimension Scores**")
                    for d in score.dimension_scores:
                        bar_val = d.raw_score / 10
                        st.markdown(
                            f"`{d.dimension.replace('_',' ').title():<22}` "
                            f"**{d.raw_score:.1f}/10**  (×{d.weight})"
                        )
                        st.progress(bar_val)

                with col_b:
                    st.markdown("**✅ Strengths**")
                    for s in score.strengths:
                        st.markdown(f"- {s}")
                    st.markdown("**⚠️ Weaknesses**")
                    for w in score.weaknesses:
                        st.markdown(f"- {w}")

                with col_c:
                    st.markdown("**📈 Scores**")
                    st.metric("Effective Score", f"{eff_score:.1f}")
                    st.metric("Semantic Sim", f"{score.semantic_similarity:.2%}")
                    st.metric("Confidence Bonus", f"+{score.confidence_bonus:.1f}")
                    if override:
                        st.info(f"Override: {override.get('reason','')}")

                # ── Human Override Controls ────────────────────────────────────
                st.divider()
                with st.form(key=f"override_form_{score.file_hash}"):
                    st.markdown("**🖊️ Human Override**")
                    oc1, oc2 = st.columns([2, 3])
                    with oc1:
                        new_score = st.slider(
                            "Override Score", 0.0, 10.0,
                            float(eff_score), 0.1,
                            key=f"slider_{score.file_hash}"
                        )
                    with oc2:
                        reason = st.text_input(
                            "Override Reason",
                            placeholder="e.g. Strong portfolio reviewed separately",
                            key=f"reason_{score.file_hash}"
                        )
                    if st.form_submit_button("💾 Save Override"):
                        if reason.strip():
                            save_override(
                                file_hash=score.file_hash,
                                candidate_name=score.candidate_name,
                                old_score=eff_score,
                                new_score=new_score,
                                reason=reason.strip(),
                            )
                            st.success(f"✅ Override saved for {score.candidate_name}")
                            # Re-rank with override — no API call, pure local re-sort
                            st.session_state["ranked"] = rank_candidates(st.session_state["scores"])
                            st.rerun()
                        else:
                            st.error("Please provide an override reason.")

    # ══════════════════════════════════════════════════════════════════════════
    # DOWNLOAD REPORTS 
    # ══════════════════════════════════════════════════════════════════════════

    st.divider()
    st.subheader("📥 Download Reports")
    r1, r2, r3 = st.columns(3)

    with r1:
        if st.button("📄 Generate JSON Report", use_container_width=True):
            with st.spinner("Generating JSON..."):
                path = generate_json_report(ranked, jd)
                data = path.read_bytes()
            st.download_button(
                "⬇️ Download JSON",
                data=data,
                file_name=path.name,
                mime="application/json",
                use_container_width=True,
            )

    with r2:
        if st.button("🌐 Generate HTML Report", use_container_width=True):
            with st.spinner("Generating HTML..."):
                path = generate_html_report(ranked, jd)
                data = path.read_bytes()
            st.download_button(
                "⬇️ Download HTML",
                data=data,
                file_name=path.name,
                mime="text/html",
                use_container_width=True,
            )

    with r3:
        if st.button("📑 Generate PDF Report", use_container_width=True):
            with st.spinner("Generating PDF (ReportLab)..."):
                path = generate_pdf_report(ranked, jd)
            if path:
                data = path.read_bytes()
                st.download_button(
                    "⬇️ Download PDF",
                    data=data,
                    file_name=path.name,
                    mime="application/pdf",
                    use_container_width=True,
                )
            else:
                st.error("PDF generation failed. Check logs.")

    # ── JD Summary Card ────────────────────────────────────────────────────────
    st.divider()
    with st.expander("📋 Job Description Summary"):
        jc1, jc2 = st.columns(2)
        with jc1:
            st.markdown(f"**Role:** {jd.role_title}")
            st.markdown(f"**Experience:** {jd.experience_years or 'Not specified'}")
            st.markdown(f"**Education:** {jd.education_requirement or 'Not specified'}")
            st.markdown("**Required Skills:**")
            st.write(", ".join(jd.required_skills) if jd.required_skills else "None listed")
        with jc2:
            st.markdown("**Preferred Skills:**")
            st.write(", ".join(jd.preferred_skills) if jd.preferred_skills else "None listed")
            st.markdown("**Tools & Technologies:**")
            st.write(", ".join(jd.tools_technologies) if jd.tools_technologies else "None listed")
            st.markdown("**Soft Skills:**")
            st.write(", ".join(jd.soft_skills) if jd.soft_skills else "None listed")

else:
    # Empty state
    st.markdown("""
    <div style="text-align:center;padding:3rem;color:#9ca3af;">
      <div style="font-size:4rem;">📂</div>
      <h3 style="color:#6b7280;">Upload files and click Run to start screening</h3>
      <p>Supports PDF job descriptions and multiple resume PDFs</p>
    </div>
    """, unsafe_allow_html=True)