"""
dashboard.py
------------
Orchestration layer: ties together SheetReader, DriveScanner,
DocumentMatcher, and SheetWriter.

Runs the full verification pipeline and emits live progress events
via a generator so Streamlit can update the UI in real time.
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Dict, Generator, List, Optional, Tuple

from google.oauth2.credentials import Credentials

from config import (
    DOCUMENT_COLUMNS,
    MAX_CONCURRENT_SCANS,
)
from document_matcher import match_documents
from drive_scanner import DriveScanner, FolderStatus
from sheet_reader import SheetReader, SheetRow
from sheet_writer import SheetWriter
from utils import extract_spreadsheet_id
from logger import get_logger

log = get_logger("dashboard")


# ──────────────────────────────────────────────────────────────────────────────
# Result data structures
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class RowResult:
    sheet_row:     int
    brand_name:    str
    folder_id:     Optional[str]
    brand_url:     Optional[str]
    folder_status: FolderStatus
    doc_results:   Dict[str, bool] = field(default_factory=dict)
    error_message: str = ""

    @property
    def found_count(self) -> int:
        return sum(1 for v in self.doc_results.values() if v)

    @property
    def missing_count(self) -> int:
        return sum(1 for v in self.doc_results.values() if not v)

    @property
    def found_docs(self) -> List[str]:
        return [k for k, v in self.doc_results.items() if v]

    @property
    def missing_docs(self) -> List[str]:
        return [k for k, v in self.doc_results.items() if not v]

    @property
    def display_status(self) -> str:
        if self.folder_status == FolderStatus.PERMISSION_ERROR:
            return "Permission Error"
        if self.folder_status == FolderStatus.FOLDER_MISSING:
            return "Folder Missing"
        if self.folder_status == FolderStatus.INVALID_ID:
            return "No Hyperlink"
        if self.folder_status == FolderStatus.EMPTY:
            return "Empty Folder"
        if all(self.doc_results.values()):
            return "Completed"
        return "Incomplete"

    @property
    def status_color(self) -> str:
        mapping = {
            "Completed":        "green",
            "Incomplete":       "orange",
            "Permission Error": "red",
            "Folder Missing":   "red",
            "No Hyperlink":     "grey",
            "Empty Folder":     "grey",
        }
        return mapping.get(self.display_status, "grey")


@dataclass
class ScanSummary:
    total_rows:       int = 0
    scanned:          int = 0
    completed:        int = 0
    incomplete:       int = 0
    permission_errors:int = 0
    folder_missing:   int = 0
    no_hyperlink:     int = 0
    docs_found:       int = 0
    docs_missing:     int = 0
    elapsed_seconds:  float = 0.0
    results:          List[RowResult] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────────
# Progress event (used by the generator)
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ProgressEvent:
    current:      int
    total:        int
    message:      str
    row_result:   Optional[RowResult] = None
    is_final:     bool = False
    summary:      Optional[ScanSummary] = None


# ──────────────────────────────────────────────────────────────────────────────
# Orchestrator
# ──────────────────────────────────────────────────────────────────────────────

class VerificationOrchestrator:

    def __init__(
        self,
        credentials: Credentials,
        spreadsheet_url: str,
        write_back: bool = True,
        sheet_name: Optional[str] = None,
    ):
        self._credentials     = credentials
        self._spreadsheet_url = spreadsheet_url
        self._write_back      = write_back
        self._sheet_name      = sheet_name

        spreadsheet_id = extract_spreadsheet_id(spreadsheet_url)
        if not spreadsheet_id:
            raise ValueError(f"Could not extract spreadsheet ID from: {spreadsheet_url}")

        self._spreadsheet_id = spreadsheet_id
        self._reader         = SheetReader(credentials, spreadsheet_id)
        self._scanner        = DriveScanner(credentials)
        self._writer         = SheetWriter(credentials, spreadsheet_id) if write_back else None

    # ──────────────────────────────────────────────────────────────────────────
    # Main entry point — generator for live progress
    # ──────────────────────────────────────────────────────────────────────────

    def run(self) -> Generator[ProgressEvent, None, None]:
        """
        Run the full verification pipeline.

        Yields ProgressEvent objects as each row is processed.
        The final event has is_final=True and contains the complete ScanSummary.
        """
        t_start = time.time()

        # ── Discover sheet name ───────────────────────────────────────────────
        if self._sheet_name:
            self._reader._sheet_name = self._sheet_name
        else:
            self._reader.discover_sheet_name()

        if self._writer:
            self._writer._sheet_name = self._reader._sheet_name

        # ── Fetch rows ────────────────────────────────────────────────────────
        yield ProgressEvent(0, 0, "Reading spreadsheet rows…")

        try:
            _header, rows = self._reader.fetch_rows()
        except Exception as exc:
            log.error("Failed to fetch sheet rows: %s", exc, exc_info=True)
            raise

        total = len(rows)
        log.info("Starting scan of %d rows.", total)

        summary = ScanSummary(total_rows=total)
        results: List[RowResult] = []

        # ── Process rows with a thread pool ───────────────────────────────────
        futures = {}
        completed_count = 0

        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_SCANS) as executor:
            for row in rows:
                future = executor.submit(self._process_row, row)
                futures[future] = row

            for future in as_completed(futures):
                completed_count += 1
                row = futures[future]

                try:
                    row_result = future.result()
                except Exception as exc:
                    log.error(
                        "Unhandled error for row %d (%s): %s",
                        row.sheet_row, row.brand_name, exc, exc_info=True,
                    )
                    row_result = RowResult(
                        sheet_row=row.sheet_row,
                        brand_name=row.brand_name,
                        folder_id=row.folder_id,
                        brand_url=row.brand_url,
                        folder_status=FolderStatus.UNKNOWN_ERROR,
                        error_message=str(exc),
                    )

                results.append(row_result)
                self._update_summary(summary, row_result)

                # Write-back to sheet
                if self._write_back and self._writer and row_result.doc_results:
                    try:
                        self._writer.queue_row_update(row_result.sheet_row, row_result.doc_results)
                    except Exception as exc:
                        log.error("Write-back failed for row %d: %s", row_result.sheet_row, exc)

                yield ProgressEvent(
                    current=completed_count,
                    total=total,
                    message=f"Scanned {row_result.brand_name or 'row ' + str(row_result.sheet_row)}",
                    row_result=row_result,
                )

        # ── Flush remaining writes ────────────────────────────────────────────
        if self._write_back and self._writer:
            try:
                self._writer.flush()
            except Exception as exc:
                log.error("Final flush failed: %s", exc)

        # ── Build summary ─────────────────────────────────────────────────────
        # Sort results by original sheet order
        results.sort(key=lambda r: r.sheet_row)
        summary.results        = results
        summary.scanned        = completed_count
        summary.elapsed_seconds = time.time() - t_start

        log.info(
            "Scan complete. %d rows in %.1fs. Found=%d Missing=%d",
            summary.scanned,
            summary.elapsed_seconds,
            summary.docs_found,
            summary.docs_missing,
        )

        yield ProgressEvent(
            current=total,
            total=total,
            message="Scan complete.",
            is_final=True,
            summary=summary,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Per-row processing (runs in thread pool)
    # ──────────────────────────────────────────────────────────────────────────

    def _process_row(self, row: SheetRow) -> RowResult:
        """Scan the Drive folder and match documents for one sheet row."""
        log.info("Processing row %d — brand: '%s'", row.sheet_row, row.brand_name)

        if not row.folder_id:
            return RowResult(
                sheet_row=row.sheet_row,
                brand_name=row.brand_name,
                folder_id=None,
                brand_url=row.brand_url,
                folder_status=FolderStatus.INVALID_ID,
                doc_results={doc: False for doc in DOCUMENT_COLUMNS},
                error_message="No Drive folder hyperlink found in Brand cell.",
            )

        scan = self._scanner.scan_folder(row.folder_id)

        if not scan.is_ok:
            return RowResult(
                sheet_row=row.sheet_row,
                brand_name=row.brand_name,
                folder_id=row.folder_id,
                brand_url=row.brand_url,
                folder_status=scan.status,
                doc_results={doc: False for doc in DOCUMENT_COLUMNS},
                error_message=scan.error_message,
            )

        doc_results = match_documents(scan.filenames)

        return RowResult(
            sheet_row=row.sheet_row,
            brand_name=row.brand_name,
            folder_id=row.folder_id,
            brand_url=row.brand_url,
            folder_status=scan.status,
            doc_results=doc_results,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Summary helpers
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _update_summary(summary: ScanSummary, r: RowResult) -> None:
        ds = r.display_status
        if ds == "Completed":
            summary.completed += 1
        elif ds == "Incomplete":
            summary.incomplete += 1
        elif ds == "Permission Error":
            summary.permission_errors += 1
        elif ds == "Folder Missing":
            summary.folder_missing += 1
        elif ds in ("No Hyperlink", "Empty Folder"):
            summary.no_hyperlink += 1

        summary.docs_found   += r.found_count
        summary.docs_missing += r.missing_count
