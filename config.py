"""
config.py
---------
Central configuration for the Import Document Verification System.
All constants, document type mappings, and API scopes live here.
"""

import os

# ──────────────────────────────────────────────
# Application Metadata
# ──────────────────────────────────────────────
APP_NAME = "Import Document Verification System"
APP_VERSION = "1.0.0"
APP_ICON = "📋"

# ──────────────────────────────────────────────
# Google OAuth Scopes
# ──────────────────────────────────────────────
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

# ──────────────────────────────────────────────
# OAuth Redirect
# ──────────────────────────────────────────────
REDIRECT_URI = os.environ.get("REDIRECT_URI", "http://localhost:8501")

# ──────────────────────────────────────────────
# Google Sheet Column Layout
# ──────────────────────────────────────────────
# Adjust these if your sheet layout differs.
SHEET_COLUMNS = {
    "REF_NO":    "A",
    "LOC":       "B",
    "TERMS":     "C",
    "BRAND":     "D",   # ← contains the Drive folder hyperlink
    "CURRENCY":  "E",
    "VALUE":     "F",
    "INVOICE_NO":"G",
    "MODE":      "H",
    "BOE_NO":    "I",
    "BOE_DATE":  "J",
    # Document columns
    "PI":        "K",
    "SWIFT":     "L",
    "INV":       "M",
    "PL":        "N",
    "AWB":       "O",
    "INS":       "P",
    "BOE":       "Q",
    "FC":        "R",
    "GP":        "S",
    "OOC":       "T",
    "EWAY":      "U",
    "BOE ACK":   "V",
    "COSTING":   "W",
    "REMARKS":   "X",
}

# Column letter → zero-based index mapping (auto-generated)
COL_LETTER_TO_INDEX = {
    col: ord(letter) - ord("A")
    for col, letter in SHEET_COLUMNS.items()
}

DOCUMENT_COLUMNS = [
    "PI", "SWIFT", "INV", "PL", "AWB",
    "INS", "BOE", "FC", "GP", "OOC",
    "EWAY", "BOE ACK", "COSTING",
]

BRAND_COLUMN_INDEX = COL_LETTER_TO_INDEX["BRAND"]   # 0-based index of Brand column

# ──────────────────────────────────────────────
# Document Detection Keywords
# ──────────────────────────────────────────────
DOCUMENT_TYPES = {
    "PI":      ["PI", "PROFORMA"],
    "SWIFT":   ["SWIFT"],
    "INV":     ["INV", "INVOICE", "COMM INV"],
    "PL":      ["PL", "PACKING LIST", "PACKLIST"],
    "AWB":     ["AWB"],
    "INS":     ["INS", "INSURANCE"],
    "BOE":     ["BOE"],
    "FC":      ["FC"],
    "GP":      ["GP"],
    "OOC":     ["OOC"],
    "EWAY":    ["EWB", "EWAY", "E-WAY", "EWAY BILL"],
    "BOE ACK": ["BOE ACK", "ACKNOWLEDGEMENT", "BOEACK", "ACK"],
    "COSTING": ["COSTING"],
}

# Value written into the sheet when a document is found
DOCUMENT_FOUND_MARKER = "X"

# ──────────────────────────────────────────────
# Scanning Defaults
# ──────────────────────────────────────────────
DATA_START_ROW = 2          # 1-based row where data starts (row 1 = header)
BATCH_SIZE = 20             # rows per Sheets API batch-update call
MAX_CONCURRENT_SCANS = 5    # ThreadPoolExecutor max workers for Drive scanning
API_SLEEP_SECONDS = 0.05    # tiny sleep between Drive API calls to respect quota

# ──────────────────────────────────────────────
# Cache
# ──────────────────────────────────────────────
FOLDER_CACHE_TTL_SECONDS = 300   # 5 minutes

# ──────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────
LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "app.log")
LOG_MAX_BYTES = 10 * 1024 * 1024   # 10 MB
LOG_BACKUP_COUNT = 5

# ──────────────────────────────────────────────
# Export
# ──────────────────────────────────────────────
EXPORT_DATE_FORMAT = "%Y%m%d_%H%M%S"
