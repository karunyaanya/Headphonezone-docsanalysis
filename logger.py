"""
logger.py
---------
Centralised logging for the Import Document Verification System.
Writes to both the console and a rotating log file.
"""

import logging
import os
from logging.handlers import RotatingFileHandler

from config import LOG_DIR, LOG_FILE, LOG_MAX_BYTES, LOG_BACKUP_COUNT


def get_logger(name: str = "import_verifier") -> logging.Logger:
    """
    Return a configured logger.  Safe to call multiple times with the same
    name — Python's logging module deduplicates handlers.
    """
    # Ensure the logs directory exists
    os.makedirs(LOG_DIR, exist_ok=True)

    logger = logging.getLogger(name)

    if logger.handlers:
        # Already configured — return as-is
        return logger

    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # ── Rotating file handler ──────────────────────────────────────────────
    try:
        fh = RotatingFileHandler(
            LOG_FILE,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except OSError as exc:
        # If we can't write to the log file (e.g. read-only FS), fall back
        # to console only and warn there.
        print(f"[WARN] Could not open log file {LOG_FILE}: {exc}")

    # ── Stream (console) handler ───────────────────────────────────────────
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    return logger


# Module-level convenience logger
log = get_logger()
