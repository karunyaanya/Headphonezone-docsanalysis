"""
sheet_writer.py
---------------
Writes document verification results back to the Google Sheet via batch updates.

Rules:
  • Only writes to the 13 document columns (PI … COSTING).
  • Never touches other columns (Ref No, Brand, Currency, Remarks, etc.).
  • Uses batch updates (batchUpdate) for performance — one API call per BATCH_SIZE rows.
  • Writes "X" when a document is found, leaves the cell blank (empty string) otherwise.
"""

from typing import Dict, List, Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials

from config import (
    SHEET_COLUMNS,
    DOCUMENT_COLUMNS,
    DOCUMENT_FOUND_MARKER,
    BATCH_SIZE,
)
from logger import get_logger

log = get_logger("sheet_writer")


# ──────────────────────────────────────────────────────────────────────────────
# SheetWriter
# ──────────────────────────────────────────────────────────────────────────────

class SheetWriter:

    def __init__(
        self,
        credentials: Credentials,
        spreadsheet_id: str,
        sheet_name: str = "Sheet1",
    ):
        self._credentials    = credentials
        self._spreadsheet_id = spreadsheet_id
        self._sheet_name     = sheet_name
        self._service        = None
        # Accumulate pending writes; flush every BATCH_SIZE entries
        self._pending: List[Dict[str, Any]] = []

    # ── Service ───────────────────────────────────────────────────────────────

    def _get_service(self):
        if self._service is None:
            self._service = build("sheets", "v4", credentials=self._credentials)
        return self._service

    # ── Public API ────────────────────────────────────────────────────────────

    def queue_row_update(
        self,
        sheet_row: int,                          # 1-based sheet row number
        doc_results: Dict[str, bool],            # {"PI": True, "SWIFT": False, …}
    ) -> None:
        """
        Add a row update to the pending queue.
        Flushes automatically when the queue reaches BATCH_SIZE.
        """
        data = []

        for doc_type in DOCUMENT_COLUMNS:
            col_letter = SHEET_COLUMNS.get(doc_type)
            if col_letter is None:
                continue   # doc type not in column map — skip

            cell_range = f"{self._sheet_name}!{col_letter}{sheet_row}"
            value = DOCUMENT_FOUND_MARKER if doc_results.get(doc_type) else ""

            data.append({
                "range":  cell_range,
                "values": [[value]],
            })

        if data:
            self._pending.append({
                "sheet_row": sheet_row,
                "data":      data,
            })

        if len(self._pending) >= BATCH_SIZE:
            self.flush()

    def flush(self) -> int:
        """
        Write all pending updates to the sheet in a single batchUpdate call.
        Returns the number of rows flushed.
        """
        if not self._pending:
            return 0

        all_data = []
        rows_to_flush = list(self._pending)
        self._pending.clear()

        for entry in rows_to_flush:
            all_data.extend(entry["data"])

        try:
            self._get_service().spreadsheets().values().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={
                    "valueInputOption": "RAW",
                    "data": all_data,
                },
            ).execute()

            row_nums = [str(e["sheet_row"]) for e in rows_to_flush]
            log.info(
                "Batch update successful — wrote %d cells across rows: %s",
                len(all_data),
                ", ".join(row_nums),
            )
            return len(rows_to_flush)

        except HttpError as exc:
            log.error("Batch update failed: %s", exc, exc_info=True)
            # Re-queue the failed entries so the caller can retry or report
            self._pending.extend(rows_to_flush)
            raise

    def write_single_row(
        self,
        sheet_row: int,
        doc_results: Dict[str, bool],
    ) -> None:
        """
        Convenience: queue a row and immediately flush it.
        Useful for real-time progress updates.
        """
        self.queue_row_update(sheet_row, doc_results)
        self.flush()

    def pending_count(self) -> int:
        return len(self._pending)
