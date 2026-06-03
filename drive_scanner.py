"""
drive_scanner.py
----------------
Scans Google Drive folders and returns a list of filenames.

Features:
  • Folder ID validation and access checks
  • File listing via Drive API v3
  • Simple in-memory LRU cache to avoid re-scanning the same folder
  • Graceful handling of permission errors, missing folders, empty folders
"""

import time
from functools import lru_cache
from typing import List, Optional, Tuple
from enum import Enum

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials

from config import API_SLEEP_SECONDS
from logger import get_logger

log = get_logger("drive_scanner")


# ──────────────────────────────────────────────────────────────────────────────
# Status enum
# ──────────────────────────────────────────────────────────────────────────────

class FolderStatus(str, Enum):
    OK               = "OK"
    PERMISSION_ERROR = "Permission Error"
    FOLDER_MISSING   = "Folder Missing"
    EMPTY            = "Empty Folder"
    INVALID_ID       = "Invalid Folder ID"
    UNKNOWN_ERROR    = "Unknown Error"


# ──────────────────────────────────────────────────────────────────────────────
# ScanResult data class
# ──────────────────────────────────────────────────────────────────────────────

class ScanResult:
    __slots__ = ("folder_id", "status", "filenames", "error_message")

    def __init__(
        self,
        folder_id: Optional[str],
        status: FolderStatus,
        filenames: List[str],
        error_message: str = "",
    ):
        self.folder_id     = folder_id
        self.status        = status
        self.filenames     = filenames
        self.error_message = error_message

    @property
    def is_ok(self) -> bool:
        return self.status == FolderStatus.OK

    def __repr__(self):
        return (
            f"<ScanResult status={self.status} "
            f"files={len(self.filenames)} folder={self.folder_id}>"
        )


# ──────────────────────────────────────────────────────────────────────────────
# DriveScanner
# ──────────────────────────────────────────────────────────────────────────────

class DriveScanner:

    def __init__(self, credentials: Credentials):
        self._credentials = credentials
        self._service     = None
        self._cache: dict = {}   # folder_id → ScanResult

    # ── Service ───────────────────────────────────────────────────────────────

    def _get_service(self):
        if self._service is None:
            self._service = build("drive", "v3", credentials=self._credentials)
        return self._service

    # ── Public: scan a folder ─────────────────────────────────────────────────

    def scan_folder(self, folder_id: Optional[str]) -> ScanResult:
        """
        List all files directly inside a Drive folder.

        Returns a ScanResult with status and list of filenames.
        Results are cached for the lifetime of this DriveScanner instance.
        """
        if not folder_id:
            return ScanResult(None, FolderStatus.INVALID_ID, [], "No folder ID provided")

        # Return cached result
        if folder_id in self._cache:
            log.debug("Cache hit for folder '%s'", folder_id)
            return self._cache[folder_id]

        result = self._do_scan(folder_id)
        self._cache[folder_id] = result
        return result

    def clear_cache(self) -> None:
        """Clear the in-memory folder cache."""
        self._cache.clear()
        log.debug("Folder cache cleared.")

    # ── Private helpers ───────────────────────────────────────────────────────

    def _do_scan(self, folder_id: str) -> ScanResult:
        """Perform the actual Drive API call."""
        time.sleep(API_SLEEP_SECONDS)   # respect API quota

        try:
            # Verify the folder exists and is accessible
            self._get_service().files().get(
                fileId=folder_id,
                fields="id,name,mimeType",
            ).execute()

        except HttpError as exc:
            status_code = exc.resp.status if exc.resp else 0
            log.warning(
                "Drive API error accessing folder '%s': %s", folder_id, exc
            )
            if status_code == 404:
                return ScanResult(folder_id, FolderStatus.FOLDER_MISSING, [],
                                  f"Folder not found: {folder_id}")
            if status_code in (401, 403):
                return ScanResult(folder_id, FolderStatus.PERMISSION_ERROR, [],
                                  f"Permission denied for folder: {folder_id}")
            return ScanResult(folder_id, FolderStatus.UNKNOWN_ERROR, [],
                              str(exc))

        # ── List files inside the folder ──────────────────────────────────────
        filenames: List[str] = []
        page_token = None

        try:
            while True:
                query = f"'{folder_id}' in parents and trashed = false"
                kwargs = dict(
                    q=query,
                    fields="nextPageToken, files(id, name)",
                    pageSize=1000,
                    orderBy="name",
                )
                if page_token:
                    kwargs["pageToken"] = page_token

                resp = self._get_service().files().list(**kwargs).execute()
                files = resp.get("files", [])
                filenames.extend(f["name"] for f in files)

                page_token = resp.get("nextPageToken")
                if not page_token:
                    break

        except HttpError as exc:
            log.error("Error listing files in folder '%s': %s", folder_id, exc)
            return ScanResult(folder_id, FolderStatus.UNKNOWN_ERROR, [], str(exc))

        log.info(
            "Scanned folder '%s' — found %d file(s): %s",
            folder_id, len(filenames), filenames,
        )

        if not filenames:
            return ScanResult(folder_id, FolderStatus.EMPTY, [])

        return ScanResult(folder_id, FolderStatus.OK, filenames)
