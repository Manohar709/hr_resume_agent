"""
utils/cache_utils.py
--------------------
Configure LangChain's SQLite cache to avoid redundant LLM API calls.
Must be called BEFORE any LangChain LLM is instantiated.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_DB_PATH = "cache/langchain_cache.db"


def setup_llm_cache() -> None:
    """
    Install LangChain's SQLite cache globally.
    All subsequent LLM calls with identical prompts will be served from cache.
    """
    try:
        Path("cache").mkdir(parents=True, exist_ok=True)
        from langchain_core.globals import set_llm_cache
        from langchain_community.cache import SQLiteCache

        set_llm_cache(SQLiteCache(database_path=CACHE_DB_PATH))
        logger.info(f"[Cache] LangChain SQLite cache enabled: {CACHE_DB_PATH}")
    except ImportError as e:
        logger.warning(f"[Cache] Could not enable LangChain cache: {e}")
    except Exception as e:
        logger.warning(f"[Cache] Cache setup failed (non-fatal): {e}")
