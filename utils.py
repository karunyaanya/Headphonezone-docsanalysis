"""
utils.py
--------
General-purpose helpers used across the application.
"""

import re
from typing import Optional
from urllib.parse import urlparse, parse_qs

from logger import get_logger

log = get_logger("utils")


# ──────────────────────────────────────────────────────────────────────────────
# Google Drive / Sheets URL helpers
# ──────────────────────────────────────────────────────────────────────────────

# Patterns that can appear in Drive folder URLs
_DRIVE_FOLDER_PATTERNS = [
    r"drive\.google\.com/drive/(?:u/\d+/)?folders/([a-zA-Z0-9_-]+)",
    r"drive\.google\.com/open\?id=([a-zA-Z0-9_-]+)",
    r"drive\.google\.com/folderview\?id=([a-zA-Z0-9_-]+)",
    r"id=([a-zA-Z0-9_-]+)",
]

_SHEETS_ID_PATTERN = re.compile(
    r"spreadsheets/d/([a-zA-Z0-9_-]+)"
)


def extract_folder_id(url: str) -> Optional[str]:
    """
    Extract a Google Drive folder ID from various URL formats.

    Supported formats:
      - https://drive.google.com/drive/folders/<ID>
      - https://drive.google.com/drive/u/0/folders/<ID>
      - https://drive.google.com/open?id=<ID>
      - https://drive.google.com/folderview?id=<ID>

    Returns None if extraction fails.
    """
    if not url:
        return None

    url = url.strip()

    for pattern in _DRIVE_FOLDER_PATTERNS:
        m = re.search(pattern, url)
        if m:
            folder_id = m.group(1)
            log.debug("Extracted folder ID '%s' from URL: %s", folder_id, url)
            return folder_id

    log.warning("Could not extract folder ID from URL: %s", url)
    return None


def extract_spreadsheet_id(url: str) -> Optional[str]:
    """
    Extract a Google Sheets spreadsheet ID from its URL.

    Example:
      https://docs.google.com/spreadsheets/d/<ID>/edit#gid=0
      → <ID>
    """
    if not url:
        return None

    m = _SHEETS_ID_PATTERN.search(url)
    if m:
        return m.group(1)

    log.warning("Could not extract spreadsheet ID from URL: %s", url)
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Hyperlink / formula helpers
# ──────────────────────────────────────────────────────────────────────────────

_HYPERLINK_FORMULA_RE = re.compile(
    r'=HYPERLINK\(\s*"([^"]+)"',
    re.IGNORECASE,
)


def extract_url_from_hyperlink_formula(cell_value: str) -> Optional[str]:
    """
    Given a cell value like:
        =HYPERLINK("https://drive.google.com/...", "BRAND")
    return the URL part.
    """
    if not cell_value:
        return None
    m = _HYPERLINK_FORMULA_RE.search(str(cell_value))
    if m:
        return m.group(1)
    return None


def is_drive_url(text: str) -> bool:
    """Return True if text looks like a Google Drive URL."""
    return bool(text and "drive.google.com" in text)


# ──────────────────────────────────────────────────────────────────────────────
# String normalisation helpers
# ──────────────────────────────────────────────────────────────────────────────

def normalise(text: str) -> str:
    """
    Uppercase, strip whitespace, and collapse multiple spaces.
    Used for keyword matching.
    """
    return re.sub(r"\s+", " ", text.strip().upper())


def col_letter_to_index(letter: str) -> int:
    """Convert a single column letter (A–Z) to a 0-based index."""
    return ord(letter.upper()) - ord("A")


def index_to_col_letter(index: int) -> str:
    """Convert a 0-based column index to a single letter (A–Z)."""
    return chr(ord("A") + index)


# ──────────────────────────────────────────────────────────────────────────────
# Misc
# ──────────────────────────────────────────────────────────────────────────────

def safe_get(lst: list, index: int, default=None):
    """Return list[index] or default if out of range."""
    try:
        return lst[index]
    except IndexError:
        return default


def truncate(text: str, max_len: int = 60) -> str:
    """Truncate a string for display purposes."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."
