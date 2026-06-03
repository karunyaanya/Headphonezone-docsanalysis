"""
document_matcher.py
-------------------
Intelligent keyword-based document detection.

Given a list of filenames found in a Drive folder, this module determines
which of the known document types (PI, SWIFT, INV, …) are present.

Matching rules:
  - Case insensitive
  - Space / hyphen / underscore insensitive
  - Whole-word and substring keyword matching
  - Handles compound keywords ("BOE ACK", "PACKING LIST")
"""

import re
from typing import Dict, List, Set

from config import DOCUMENT_TYPES, DOCUMENT_COLUMNS
from logger import get_logger

log = get_logger("document_matcher")


# ──────────────────────────────────────────────────────────────────────────────
# Pre-compile keyword patterns for performance
# ──────────────────────────────────────────────────────────────────────────────

def _build_patterns(keywords: List[str]) -> List[re.Pattern]:
    """
    For each keyword, build a regex pattern that:
      - Is case insensitive
      - Ignores spaces / hyphens / underscores between characters
      - Matches the keyword as a whole token (not necessarily a whole word,
        because filenames often have no delimiters: "IRIVERINV.pdf")
    """
    patterns = []
    for kw in keywords:
        # Normalise: upper, collapse whitespace
        kw_norm = re.sub(r"[\s_\-]+", r"[\\s_\\-]*", kw.strip().upper())
        pattern = re.compile(kw_norm, re.IGNORECASE)
        patterns.append(pattern)
    return patterns


_COMPILED: Dict[str, List[re.Pattern]] = {
    doc_type: _build_patterns(keywords)
    for doc_type, keywords in DOCUMENT_TYPES.items()
}


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def match_documents(filenames: List[str]) -> Dict[str, bool]:
    """
    Given a list of filenames, return a dict mapping each document type
    to True (found) or False (not found).

    Example:
        filenames = ["IRIVER USD 3326 BOE.pdf", "IRIVER USD 3326 SWIFT.pdf"]
        → {"PI": False, "SWIFT": True, "INV": False, "BOE": True, ...}
    """
    results: Dict[str, bool] = {doc: False for doc in DOCUMENT_COLUMNS}

    # Normalise filenames once — strip extension, upper, collapse separators
    normalised = [_normalise_filename(f) for f in filenames]

    for doc_type, patterns in _COMPILED.items():
        for norm_name in normalised:
            if _any_pattern_matches(patterns, norm_name):
                results[doc_type] = True
                log.debug(
                    "Matched document type '%s' in filename '%s'",
                    doc_type, norm_name,
                )
                break   # no need to check remaining filenames for this type

    found = [k for k, v in results.items() if v]
    missing = [k for k, v in results.items() if not v]
    log.debug("Found: %s | Missing: %s", found, missing)
    return results


def get_found_documents(filenames: List[str]) -> List[str]:
    """Return list of document types that were found."""
    return [doc for doc, found in match_documents(filenames).items() if found]


def get_missing_documents(filenames: List[str]) -> List[str]:
    """Return list of document types that were NOT found."""
    return [doc for doc, found in match_documents(filenames).items() if not found]


# ──────────────────────────────────────────────────────────────────────────────
# Private helpers
# ──────────────────────────────────────────────────────────────────────────────

def _normalise_filename(filename: str) -> str:
    """
    Strip file extension and collapse non-alphanumeric characters to a single
    space for easier pattern matching.
    """
    # Remove file extension
    name = re.sub(r"\.[^.]+$", "", filename)
    # Replace separators with space
    name = re.sub(r"[\s_\-/\\]+", " ", name)
    return name.upper().strip()


def _any_pattern_matches(patterns: List[re.Pattern], text: str) -> bool:
    """Return True if any compiled pattern matches the text."""
    return any(p.search(text) for p in patterns)
