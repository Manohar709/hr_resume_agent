"""
utils/validation.py
-------------------
File validation: extension, MIME type, size, and PDF integrity.
All validation failures return descriptive error messages.
"""

import logging
import mimetypes
from typing import Tuple

from utils.pdf_utils import is_valid_pdf_bytes

logger = logging.getLogger(__name__)

MAX_FILE_SIZE_MB = 10  # 10 MB hard limit per file
ALLOWED_EXTENSIONS = {".pdf"}
ALLOWED_MIME_TYPES = {"application/pdf", "application/x-pdf"}


def validate_uploaded_file(
    filename: str,
    file_bytes: bytes,
) -> Tuple[bool, str]:
    """
    Run all validation checks on an uploaded file.

    Returns:
        (is_valid, error_message)  —  error_message is "" on success.
    """
    # 1. Extension check
    if not filename:
        return False, "Filename is empty."

    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        return False, f"Invalid file extension '{ext}'. Only PDF files are accepted."

    # 2. Empty file check
    if not file_bytes or len(file_bytes) == 0:
        return False, "File is empty."

    # 3. File size check
    size_mb = len(file_bytes) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        return False, f"File too large ({size_mb:.1f} MB). Maximum allowed is {MAX_FILE_SIZE_MB} MB."

    # 4. MIME type check (best-effort from bytes header)
    mime_type = _detect_mime(file_bytes, filename)
    if mime_type and mime_type not in ALLOWED_MIME_TYPES:
        logger.warning(f"[Validate] Suspicious MIME type '{mime_type}' for {filename}")
        # Don't hard-fail on MIME — browsers sometimes send wrong type
        # but do fail on obvious non-PDFs
        if not file_bytes[:4] in (b"%PDF", b"%PDF"):
            pass  # We'll rely on the PDF integrity check below

    # 5. PDF integrity check
    if not is_valid_pdf_bytes(file_bytes):
        return False, "File appears to be a corrupted or invalid PDF."

    logger.info(f"[Validate] ✓ {filename} passed all checks ({size_mb:.2f} MB)")
    return True, ""


def sanitize_text(text: str, max_length: int = 50_000) -> str:
    """
    Remove potential prompt injection patterns from extracted text.
    Truncates to max_length to prevent token overflow.
    """
    if not text:
        return ""

    # Remove common injection-style instructions that could appear in resumes
    injection_patterns = [
        "ignore previous instructions",
        "ignore all instructions",
        "disregard the above",
        "new instructions:",
        "system prompt:",
        "you are now",
        "forget everything",
        "act as",
        "jailbreak",
        "dan mode",
    ]

    text_lower = text.lower()
    for pattern in injection_patterns:
        if pattern in text_lower:
            logger.warning(f"[Security] Potential injection pattern detected: '{pattern}'")
            # Replace only the injection attempt, not entire text
            idx = text_lower.find(pattern)
            text = text[:idx] + "[REDACTED]" + text[idx + len(pattern):]
            text_lower = text.lower()

    # Truncate to prevent prompt flooding
    return text[:max_length]


def _detect_mime(file_bytes: bytes, filename: str) -> str:
    """Detect MIME type from filename and magic bytes."""
    # From filename
    mime, _ = mimetypes.guess_type(filename)
    if mime:
        return mime
    # From magic bytes
    if file_bytes[:5] == b"%PDF-":
        return "application/pdf"
    return "application/octet-stream"
