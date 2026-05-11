"""
utils/hashing.py
----------------
SHA-256 file hashing for duplicate resume detection.
"""

import hashlib


def compute_sha256(file_bytes: bytes) -> str:
    """Return hex SHA-256 digest of file bytes."""
    return hashlib.sha256(file_bytes).hexdigest()


def compute_text_hash(text: str) -> str:
    """Hash a text string (for JD caching)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
