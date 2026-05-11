"""
utils/logging_utils.py
----------------------
Structured logging setup with file + console handlers.
Each log entry includes stage, latency, tokens, and errors.
"""

import logging
import json
import time
from pathlib import Path
from functools import wraps
from typing import Callable, Any

from database.db import save_log

LOG_DIR = Path("logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)


def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logger with file and console handlers."""
    log_file = LOG_DIR / "hr_agent.log"

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # File handler — rotates would be added for production
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def log_stage(
    stage: str,
    model_name: str = "",
    latency_ms: float = 0.0,
    token_usage: dict = None,
    error: str = "",
    extra: dict = None,
) -> None:
    """Persist a structured log entry to DB and Python logger."""
    logger = logging.getLogger("observability")

    log_data = {
        "stage": stage,
        "model": model_name,
        "latency_ms": round(latency_ms, 2),
        "tokens": token_usage or {},
        "error": error,
    }
    if extra:
        log_data.update(extra)

    if error:
        logger.error(f"[{stage}] {error} | {json.dumps(log_data)}")
    else:
        logger.info(f"[{stage}] OK | latency={latency_ms:.0f}ms | {json.dumps(log_data)}")

    # Persist to SQLite asynchronously-ish (no true async here, but fast)
    try:
        save_log(
            stage=stage,
            model_name=model_name,
            latency_ms=latency_ms,
            token_usage=token_usage,
            error=error,
            extra=extra,
        )
    except Exception:
        pass  # Logging must never crash the app


def timed(stage: str) -> Callable:
    """Decorator that times a function and logs it."""
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs) -> Any:
            start = time.time()
            error_msg = ""
            try:
                result = fn(*args, **kwargs)
                return result
            except Exception as e:
                error_msg = str(e)
                raise
            finally:
                elapsed = (time.time() - start) * 1000
                log_stage(stage=stage, latency_ms=elapsed, error=error_msg)
        return wrapper
    return decorator
