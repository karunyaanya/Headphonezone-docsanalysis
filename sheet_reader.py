"""
sheet_reader.py
---------------
Reads data from a Google Sheet via the Sheets API (v4).

Key responsibilities:
  • Fetch all rows (values + metadata)
  • Extract the Drive folder hyperlink from the Brand cell
  • Support =HYPERLINK() formulas, manual URLs, and rich-text hyperlinks
"""

import re
from typing import List, Optional, Dict, Any, Tuple

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials

from config import (
    BRAND_COLUMN_INDEX,
    DATA_START_ROW,
    SHEET_COLUMNS,
    DOCUMENT_COLUMNS,
)
from utils import extract_folder_id, extract_url_from_hyperlink_formula, safe_get
from logger import get_logger

log = get_logger("sheet_reader")


# ──────────────────────────────────────────────────────────────────────────────
# Data structures
# ──────────────────────────────────────────────────────────────────────────────

class SheetRow:
    """Represents one data row from the Google Sheet."""

    def __init__(
        self,
        row_index: int,        # 0-based index in the full values array
        sheet_row: int,        # 1-based row number in the spreadsheet
        values: List[str],
        brand_url: Optional[str],
        folder_id: Optional[str],
    ):
        self.row_index   = row_index
        self.sheet_row   = sheet_row
        self.values      = values
        self.brand_url   = brand_url
        self.folder_id   = folder_id

    @property
    def brand_name(self) -> str:
        return safe_get(self.values, BRAND_COLUMN_INDEX, "") or ""

    @property
    def ref_no(self) -> str:
        return safe_get(self.values, 0, "") or ""

    def is_empty(self) -> bool:
        return not any(v.strip() for v in self.values if v)

    def __repr__(self):
        return f"<SheetRow sheet_row={self.sheet_row} brand='{self.brand_name}'>"


# ──────────────────────────────────────────────────────────────────────────────
# SheetReader
# ──────────────────────────────────────────────────────────────────────────────

class SheetReader:

    def __init__(self, credentials: Credentials, spreadsheet_id: str, sheet_name: str = "Sheet1"):
        self._credentials     = credentials
        self._spreadsheet_id  = spreadsheet_id
        self._sheet_name      = sheet_name
        self._service         = None
        self._header: List[str] = []

    # ── Build service ─────────────────────────────────────────────────────────

    def _get_service(self):
        if self._service is None:
            self._service = build("sheets", "v4", credentials=self._credentials)
        return self._service

    # ── Public: discover actual sheet name ───────────────────────────────────

    def discover_sheet_name(self) -> str:
        """Return the name of the first (visible) sheet in the spreadsheet."""
        try:
            meta = (
                self._get_service()
                .spreadsheets()
                .get(spreadsheetId=self._spreadsheet_id)
                .execute()
            )
            for sheet in meta.get("sheets", []):
                props = sheet.get("properties", {})
                if not props.get("hidden", False):
                    name = props["title"]
                    log.info("Discovered active sheet name: '%s'", name)
                    self._sheet_name = name
                    return name
        except HttpError as exc:
            log.error("Failed to fetch spreadsheet metadata: %s", exc)
        return self._sheet_name

    # ── Public: fetch all rows ────────────────────────────────────────────────

    def fetch_rows(self) -> Tuple[List[str], List[SheetRow]]:
        """
        Fetch the header row and all data rows.

        Returns:
            (header, rows)
            header – list of column names from row 1
            rows   – list of SheetRow objects (one per non-empty data row)
        """
        log.info(
            "Fetching rows from spreadsheet '%s', sheet '%s'",
            self._spreadsheet_id, self._sheet_name,
        )

        # ── 1. Get plain cell values ──────────────────────────────────────────
        values_resp = self._fetch_values()
        all_values: List[List[str]] = values_resp if values_resp else []

        if not all_values:
            log.warning("Spreadsheet returned no data.")
            return [], []

        header = [str(c) for c in all_values[0]] if all_values else []
        self._header = header

        # ── 2. Get cell metadata (for hyperlinks) ─────────────────────────────
        hyperlink_map: Dict[int, str] = self._fetch_hyperlink_map()

        # ── 3. Build SheetRow objects ─────────────────────────────────────────
        rows: List[SheetRow] = []

        for i, raw in enumerate(all_values[DATA_START_ROW - 1:], start=DATA_START_ROW - 1):
            sheet_row = i + 1  # 1-based
            values = [str(v) for v in raw]

            # Skip completely empty rows
            if not any(v.strip() for v in values):
                continue

            # Determine folder URL
            brand_url, folder_id = self._extract_folder_info(
                values, i, hyperlink_map
            )

            rows.append(SheetRow(
                row_index=i,
                sheet_row=sheet_row,
                values=values,
                brand_url=brand_url,
                folder_id=folder_id,
            ))

        log.info("Fetched %d data rows (header excluded).", len(rows))
        return header, rows

    # ── Private helpers ───────────────────────────────────────────────────────

    def _fetch_values(self) -> List[List]:
        """Fetch all cell values as a 2-D list."""
        try:
            result = (
                self._get_service()
                .spreadsheets()
                .values()
                .get(
                    spreadsheetId=self._spreadsheet_id,
                    range=self._sheet_name,
                    valueRenderOption="FORMULA",   # keep =HYPERLINK() formulas
                )
                .execute()
            )
            return result.get("values", [])
        except HttpError as exc:
            log.error("Sheets API error fetching values: %s", exc)
            raise

    def _fetch_hyperlink_map(self) -> Dict[int, str]:
        """
        Use the spreadsheets.get endpoint to extract rich-text hyperlinks
        from the Brand column.

        Returns dict: {0-based row index → URL}
        """
        hyperlink_map: Dict[int, str] = {}

        brand_col_letter = SHEET_COLUMNS["BRAND"]

        try:
            resp = (
                self._get_service()
                .spreadsheets()
                .get(
                    spreadsheetId=self._spreadsheet_id,
                    ranges=[f"{self._sheet_name}!{brand_col_letter}:{brand_col_letter}"],
                    includeGridData=True,
                )
                .execute()
            )

            sheets = resp.get("sheets", [])
            if not sheets:
                return hyperlink_map

            grid_data = sheets[0].get("data", [])
            if not grid_data:
                return hyperlink_map

            row_data = grid_data[0].get("rowData", [])
            for r_idx, row in enumerate(row_data):
                for cell in row.get("values", []):
                    # Try hyperlink property first
                    url = cell.get("hyperlink")
                    if url:
                        hyperlink_map[r_idx] = url
                        continue

                    # Try textFormat runs
                    for run in cell.get("textFormatRuns", []):
                        link = run.get("format", {}).get("link", {}).get("uri")
                        if link:
                            hyperlink_map[r_idx] = link
                            break

        except HttpError as exc:
            log.warning(
                "Could not fetch hyperlink metadata (will rely on formula parsing): %s", exc
            )

        log.debug("Hyperlink map has %d entries.", len(hyperlink_map))
        return hyperlink_map

    def _extract_folder_info(
        self,
        values: List[str],
        row_index: int,
        hyperlink_map: Dict[int, str],
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Try multiple strategies to obtain the Drive folder URL and ID.

        Strategy order:
          1. Rich-text hyperlink from metadata
          2. =HYPERLINK() formula in the Brand cell
          3. Raw URL in the Brand cell value
        """
        # Strategy 1 — metadata hyperlink
        url = hyperlink_map.get(row_index)

        # Strategy 2 — =HYPERLINK() formula
        if not url:
            brand_cell = safe_get(values, BRAND_COLUMN_INDEX, "")
            url = extract_url_from_hyperlink_formula(brand_cell or "")

        # Strategy 3 — plain URL in cell
        if not url:
            brand_cell = safe_get(values, BRAND_COLUMN_INDEX, "")
            if brand_cell and "drive.google.com" in brand_cell:
                url = brand_cell

        if not url:
            return None, None

        folder_id = extract_folder_id(url)
        return url, folder_id

    # ── Utility ───────────────────────────────────────────────────────────────

    def get_header(self) -> List[str]:
        return self._header
