"""
database/db.py
--------------
SQLite database initialization and all CRUD operations.
Uses raw sqlite3 for fine-grained control alongside LangChain cache.
"""

import sqlite3
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

DB_PATH = Path("data/hr_agent.db")


def get_connection() -> sqlite3.Connection:
    """Return a SQLite connection with WAL mode for concurrent access."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create all required tables if they don't exist."""
    conn = get_connection()
    try:
        cursor = conn.cursor()

        # ── Processed Resumes ──────────────────────────────────
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS processed_resumes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                file_hash   TEXT    UNIQUE NOT NULL,
                filename    TEXT    NOT NULL,
                candidate_name TEXT,
                profile_json   TEXT,   -- serialized CandidateProfile
                processed_at   TEXT    DEFAULT (datetime('now')),
                jd_hash        TEXT    -- link to which JD this was processed against
            )
        """)

        # ── Candidate Scores ───────────────────────────────────
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS candidate_scores (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                file_hash       TEXT    NOT NULL,
                candidate_name  TEXT,
                total_score     REAL,
                score_json      TEXT,   -- serialized CandidateScore
                jd_hash         TEXT,
                scored_at       TEXT    DEFAULT (datetime('now')),
                UNIQUE(file_hash, jd_hash)
            )
        """)

        # ── Human Overrides ────────────────────────────────────
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS overrides (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                file_hash       TEXT    NOT NULL,
                candidate_name  TEXT,
                old_score       REAL,
                new_score       REAL,
                reason          TEXT,
                override_by     TEXT    DEFAULT 'HR Manager',
                created_at      TEXT    DEFAULT (datetime('now'))
            )
        """)

        # ── Duplicate Hashes ───────────────────────────────────
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS file_hashes (
                file_hash   TEXT PRIMARY KEY,
                filename    TEXT,
                added_at    TEXT DEFAULT (datetime('now'))
            )
        """)

        # ── Processing Logs ────────────────────────────────────
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS processing_logs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                stage       TEXT,
                model_name  TEXT,
                latency_ms  REAL,
                token_usage TEXT,
                error       TEXT,
                extra       TEXT,
                logged_at   TEXT DEFAULT (datetime('now'))
            )
        """)

        conn.commit()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"DB init error: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


# ──────────────────────────────────────────────
# Hash / Duplicate Detection
# ──────────────────────────────────────────────

def is_duplicate(file_hash: str) -> bool:
    """Return True if this hash was already processed."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM file_hashes WHERE file_hash = ?", (file_hash,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def register_hash(file_hash: str, filename: str) -> None:
    """Store a new file hash to prevent future duplicates."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO file_hashes (file_hash, filename) VALUES (?, ?)",
            (file_hash, filename),
        )
        conn.commit()
    finally:
        conn.close()


# ──────────────────────────────────────────────
# Resume CRUD
# ──────────────────────────────────────────────

def save_resume(file_hash: str, filename: str, profile: Dict, jd_hash: str = "") -> None:
    """Persist parsed candidate profile to DB."""
    conn = get_connection()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO processed_resumes
               (file_hash, filename, candidate_name, profile_json, jd_hash)
               VALUES (?, ?, ?, ?, ?)""",
            (
                file_hash,
                filename,
                profile.get("name", "Unknown"),
                json.dumps(profile),
                jd_hash,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_cached_resume(file_hash: str, jd_hash: str = "") -> Optional[Dict]:
    """Return cached profile if previously parsed for same JD context."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT profile_json FROM processed_resumes WHERE file_hash = ? AND jd_hash = ?",
            (file_hash, jd_hash),
        ).fetchone()
        return json.loads(row["profile_json"]) if row else None
    finally:
        conn.close()


# ──────────────────────────────────────────────
# Score CRUD
# ──────────────────────────────────────────────

def save_score(file_hash: str, candidate_name: str, score: Dict, jd_hash: str = "") -> None:
    """Persist scoring results."""
    conn = get_connection()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO candidate_scores
               (file_hash, candidate_name, total_score, score_json, jd_hash)
               VALUES (?, ?, ?, ?, ?)""",
            (
                file_hash,
                candidate_name,
                score.get("total_weighted_score", 0),
                json.dumps(score),
                jd_hash,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_cached_score(file_hash: str, jd_hash: str) -> Optional[Dict]:
    """Return cached score if previously computed for this JD."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT score_json FROM candidate_scores WHERE file_hash = ? AND jd_hash = ?",
            (file_hash, jd_hash),
        ).fetchone()
        return json.loads(row["score_json"]) if row else None
    finally:
        conn.close()


# ──────────────────────────────────────────────
# Override CRUD
# ──────────────────────────────────────────────

def save_override(
    file_hash: str,
    candidate_name: str,
    old_score: float,
    new_score: float,
    reason: str,
    override_by: str = "HR Manager",
) -> None:
    """Store human override decision."""
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO overrides
               (file_hash, candidate_name, old_score, new_score, reason, override_by)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (file_hash, candidate_name, old_score, new_score, reason, override_by),
        )
        conn.commit()
    finally:
        conn.close()


def get_override(file_hash: str) -> Optional[Dict]:
    """Fetch the most recent override for a candidate."""
    conn = get_connection()
    try:
        row = conn.execute(
            """SELECT new_score, reason, override_by, created_at
               FROM overrides WHERE file_hash = ?
               ORDER BY created_at DESC LIMIT 1""",
            (file_hash,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_all_overrides() -> List[Dict]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM overrides ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ──────────────────────────────────────────────
# Log CRUD
# ──────────────────────────────────────────────

def save_log(
    stage: str,
    model_name: str = "",
    latency_ms: float = 0.0,
    token_usage: Optional[Dict] = None,
    error: str = "",
    extra: Optional[Dict] = None,
) -> None:
    """Persist a structured processing log entry."""
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO processing_logs
               (stage, model_name, latency_ms, token_usage, error, extra)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                stage,
                model_name,
                latency_ms,
                json.dumps(token_usage or {}),
                error,
                json.dumps(extra or {}),
            ),
        )
        conn.commit()
    except Exception as e:
        logger.warning(f"Failed to save log: {e}")
    finally:
        conn.close()
