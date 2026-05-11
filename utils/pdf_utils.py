"""
utils/pdf_utils.py
------------------
PDF text extraction using IBM Docling.
Supports scanned PDFs, OCR, tables, and structured extraction.
"""

import logging
import tempfile
import os
from typing import Tuple

logger = logging.getLogger(__name__)


def extract_text_from_pdf(file_bytes: bytes, filename: str = "unknown.pdf") -> Tuple[str, bool]:
    """
    Extract text from PDF using Docling.

    Returns:
        (text, success)
    """

    try:
        from docling.document_converter import DocumentConverter

        # Create temporary PDF file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
            temp_pdf.write(file_bytes)
            temp_pdf_path = temp_pdf.name

        # Initialize Docling
        converter = DocumentConverter()

        # Convert PDF
        result = converter.convert(temp_pdf_path)

        # Export extracted content as markdown
        text = result.document.export_to_markdown().strip()

        # Remove temp file
        os.remove(temp_pdf_path)

        # Validate extracted text
        if len(text) < 50:
            logger.warning(
                f"[DOCLING] Very short text extracted from {filename} ({len(text)} chars)"
            )

        logger.info(
            f"[DOCLING] Extracted {len(text)} chars from {filename}"
        )

        return text, True

    except Exception as e:
        logger.error(f"[DOCLING] Extraction failed for {filename}: {e}")
        return "", False


def is_valid_pdf_bytes(file_bytes: bytes) -> bool:
    """
    Basic PDF validation.
    """

    if not file_bytes or len(file_bytes) < 8:
        return False

    # PDF header check
    if not file_bytes[:5] == b"%PDF-":
        return False

    return True