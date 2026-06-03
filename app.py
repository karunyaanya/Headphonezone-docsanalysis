"""
app.py
------
Main Streamlit entry point for the Import Document Verification System.

Run locally:
    streamlit run app.py

Deployed on Render:
    See render.yaml
"""

import io
import time
from datetime import datetime
from typing import List, Optional

import pandas as pd
import streamlit as st

from auth import (
    exchange_code_for_token,
    get_auth_url,
    get_credentials,
    get_user_info,
    is_authenticated,
    logout,
)
from config import (
    APP_ICON,
    APP_NAME,
    DOCUMENT_COLUMNS,
    EXPORT_DATE_FORMAT,
)
from dashboard import (
    ProgressEvent,
    RowResult,
    ScanSummary,
    VerificationOrchestrator,
)
from logger import get_logger
from utils import extract_spreadsheet_id

log = get_logger("app")


# ──────────────────────────────────────────────────────────────────────────────
# Streamlit page configuration
# ──────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title=APP_NAME,
    page_icon=APP_ICON,
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* General */
    .main .block-container { padding-top: 1.5rem; padding-bottom: 2rem; }
    h1 { font-size: 1.7rem !important; }

    /* Metric cards */
    div[data-testid="metric-container"] {
        background: #f8f9fb;
        border: 1px solid #e0e4ea;
        border-radius: 10px;
        padding: 0.8rem 1rem;
    }
    div[data-testid="metric-container"] label { color: #555 !important; font-size: 0.78rem !important; }

    /* Status badges */
    .badge-completed    { background:#d1f0d8; color:#1a7a36; padding:2px 8px; border-radius:4px; font-size:0.78rem; font-weight:600; }
    .badge-incomplete   { background:#fff3cd; color:#856404; padding:2px 8px; border-radius:4px; font-size:0.78rem; font-weight:600; }
    .badge-error        { background:#fde0e0; color:#a00; padding:2px 8px; border-radius:4px; font-size:0.78rem; font-weight:600; }
    .badge-missing      { background:#e2e3e5; color:#383d41; padding:2px 8px; border-radius:4px; font-size:0.78rem; font-weight:600; }

    /* Live log */
    .live-log {
        background:#1e1e2e;
        color:#cdd6f4;
        font-family: 'Courier New', monospace;
        font-size: 0.78rem;
        padding: 10px 14px;
        border-radius: 8px;
        max-height: 220px;
        overflow-y: auto;
    }
    .log-ok     { color: #a6e3a1; }
    .log-warn   { color: #f38ba8; }
    .log-info   { color: #89b4fa; }

    /* Sidebar */
    section[data-testid="stSidebar"] { background: #f0f2f8; }
    section[data-testid="stSidebar"] .block-container { padding-top: 1rem; }
</style>
""", unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────────────────────────
# Session state helpers
# ──────────────────────────────────────────────────────────────────────────────

def _init_session():
    defaults = {
        "scan_results":   None,
        "scan_summary":   None,
        "scan_log":       [],
        "scanning":       False,
        "scan_progress":  0,
        "scan_total":     0,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ──────────────────────────────────────────────────────────────────────────────
# OAuth callback handler
# ──────────────────────────────────────────────────────────────────────────────

def _handle_oauth_callback():
    """
    Detect an OAuth redirect (code param in query string) and exchange
    the code for credentials.
    """
    params = st.query_params
    code   = params.get("code")
    if code and not is_authenticated():
        with st.spinner("Completing Google Sign-In…"):
            ok = exchange_code_for_token(code)
        # Clear the code from the URL
        st.query_params.clear()
        if ok:
            st.success("Signed in successfully!")
            log.info("OAuth callback completed successfully.")
        else:
            st.error("Authentication failed. Please try again.")
        st.rerun()


# ──────────────────────────────────────────────────────────────────────────────
# Sidebar
# ──────────────────────────────────────────────────────────────────────────────

def render_sidebar() -> Optional[str]:
    """
    Render sidebar UI.
    Returns the spreadsheet URL if the user has submitted one, else None.
    """
    with st.sidebar:
        st.markdown(f"## {APP_ICON} {APP_NAME}")
        st.divider()

        # ── Auth section ──────────────────────────────────────────────────────
        if not is_authenticated():
            st.markdown("### 🔐 Sign In")
            st.markdown(
                "Sign in with your Google Workspace account "
                "to access your Sheets and Drive folders."
            )
            try:
                auth_url = get_auth_url()
                st.link_button("Sign in with Google", auth_url, use_container_width=True)
            except EnvironmentError as exc:
                st.error(f"⚠️ OAuth not configured: {exc}")
            return None

        # ── User info ─────────────────────────────────────────────────────────
        user = get_user_info()
        if user.get("picture"):
            col1, col2 = st.columns([1, 3])
            with col1:
                st.image(user["picture"], width=40)
            with col2:
                st.markdown(f"**{user.get('name', 'User')}**")
                st.caption(user.get("email", ""))
        else:
            st.markdown(f"👤 **{user.get('email', 'Signed in')}**")

        if st.button("Logout", use_container_width=True):
            logout()
            st.rerun()

        st.divider()

        # ── Sheet URL input ───────────────────────────────────────────────────
        st.markdown("### 📊 Google Sheet")
        sheet_url = st.text_area(
            "Paste your Google Sheet URL:",
            height=80,
            placeholder="https://docs.google.com/spreadsheets/d/…",
            key="sheet_url_input",
        )

        write_back = st.checkbox(
            "✏️ Write results back to sheet",
            value=True,
            help="Mark document columns with 'X' when documents are found.",
        )
        st.session_state["write_back"] = write_back

        # ── Scan button ───────────────────────────────────────────────────────
        scan_clicked = st.button(
            "🔍 Start Scan",
            use_container_width=True,
            type="primary",
            disabled=st.session_state.get("scanning", False),
        )

        st.divider()

        # ── Export buttons ────────────────────────────────────────────────────
        st.markdown("### 📥 Export")
        if st.session_state.get("scan_results"):
            _render_export_buttons()
        else:
            st.caption("Run a scan to enable exports.")

        st.divider()
        st.caption(f"Import Document Verifier · v1.0.0")

    if scan_clicked:
        if not sheet_url or not sheet_url.strip():
            st.sidebar.error("Please enter a Google Sheet URL.")
            return None
        if not extract_spreadsheet_id(sheet_url):
            st.sidebar.error("Invalid Google Sheets URL.")
            return None
        return sheet_url.strip()

    return None


# ──────────────────────────────────────────────────────────────────────────────
# Export helpers
# ──────────────────────────────────────────────────────────────────────────────

def _render_export_buttons():
    results: List[RowResult] = st.session_state["scan_results"]
    df = _results_to_dataframe(results)
    ts = datetime.now().strftime(EXPORT_DATE_FORMAT)

    # CSV
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️ Export CSV",
        data=csv_bytes,
        file_name=f"verification_report_{ts}.csv",
        mime="text/csv",
        use_container_width=True,
    )

    # Excel
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Results", index=False)
        _write_summary_sheet(writer, st.session_state.get("scan_summary"))
    buf.seek(0)
    st.download_button(
        "⬇️ Export Excel",
        data=buf,
        file_name=f"verification_report_{ts}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )


def _results_to_dataframe(results: List[RowResult]) -> pd.DataFrame:
    rows = []
    for r in results:
        row = {
            "Sheet Row":  r.sheet_row,
            "Brand":      r.brand_name,
            "Folder URL": r.brand_url or "",
            "Status":     r.display_status,
            "Found Docs": ", ".join(r.found_docs),
            "Missing Docs": ", ".join(r.missing_docs),
        }
        for doc in DOCUMENT_COLUMNS:
            row[doc] = "X" if r.doc_results.get(doc) else ""
        rows.append(row)
    return pd.DataFrame(rows)


def _write_summary_sheet(writer, summary: Optional[ScanSummary]):
    if summary is None:
        return
    data = {
        "Metric": [
            "Total Rows", "Scanned", "Completed", "Incomplete",
            "Permission Errors", "Folder Missing", "No Hyperlink",
            "Documents Found", "Documents Missing",
            "Elapsed (s)",
        ],
        "Value": [
            summary.total_rows, summary.scanned, summary.completed,
            summary.incomplete, summary.permission_errors,
            summary.folder_missing, summary.no_hyperlink,
            summary.docs_found, summary.docs_missing,
            round(summary.elapsed_seconds, 1),
        ],
    }
    pd.DataFrame(data).to_excel(writer, sheet_name="Summary", index=False)


# ──────────────────────────────────────────────────────────────────────────────
# Main dashboard
# ──────────────────────────────────────────────────────────────────────────────

def render_dashboard():
    st.markdown(f"# {APP_ICON} {APP_NAME}")

    summary: Optional[ScanSummary] = st.session_state.get("scan_summary")
    results: Optional[List[RowResult]] = st.session_state.get("scan_results")

    # ── KPI cards ─────────────────────────────────────────────────────────────
    if summary:
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("📦 Total Brands",      summary.total_rows)
        c2.metric("✅ Completed",          summary.completed)
        c3.metric("⏳ Incomplete",         summary.incomplete)
        c4.metric("📄 Documents Found",    summary.docs_found)
        c5.metric("❌ Documents Missing",  summary.docs_missing)
        st.caption(
            f"Scan completed in {summary.elapsed_seconds:.1f}s · "
            f"{summary.permission_errors} permission error(s) · "
            f"{summary.folder_missing} missing folder(s)"
        )
        st.divider()

    # ── Results table ─────────────────────────────────────────────────────────
    if results:
        _render_results_table(results)
    else:
        _render_empty_state()


def _render_empty_state():
    st.info(
        "👈 Enter your Google Sheet URL in the sidebar and click **Start Scan** to begin.",
        icon="ℹ️",
    )
    st.markdown("""
    #### How it works
    1. Paste your Google Sheet URL in the sidebar.
    2. Click **Start Scan**.
    3. The app reads every Brand row, opens its Drive folder, detects which documents are present, and marks columns `PI · SWIFT · INV · PL · AWB · INS · BOE · FC · GP · OOC · EWAY · BOE ACK · COSTING` with **X**.
    4. Download the report as CSV or Excel.
    """)


def _render_results_table(results: List[RowResult]):
    st.markdown("### 📋 Verification Results")

    # ── Filter controls ───────────────────────────────────────────────────────
    col_f1, col_f2, col_f3 = st.columns([2, 2, 2])
    with col_f1:
        status_filter = st.multiselect(
            "Filter by Status",
            options=["Completed", "Incomplete", "Permission Error", "Folder Missing",
                     "No Hyperlink", "Empty Folder"],
            default=[],
            placeholder="All statuses",
        )
    with col_f2:
        missing_doc_filter = st.selectbox(
            "Show rows missing this document",
            options=["(All)"] + DOCUMENT_COLUMNS,
        )
    with col_f3:
        brand_search = st.text_input("Search Brand", placeholder="Type to filter…")

    # ── Apply filters ─────────────────────────────────────────────────────────
    filtered = results
    if status_filter:
        filtered = [r for r in filtered if r.display_status in status_filter]
    if missing_doc_filter != "(All)":
        filtered = [r for r in filtered if not r.doc_results.get(missing_doc_filter, True)]
    if brand_search:
        filtered = [r for r in filtered if brand_search.upper() in r.brand_name.upper()]

    st.caption(f"Showing {len(filtered)} of {len(results)} rows")

    # ── Build display dataframe ───────────────────────────────────────────────
    df_rows = []
    for r in filtered:
        row = {
            "Row":    r.sheet_row,
            "Brand":  r.brand_name,
            "Status": r.display_status,
        }
        for doc in DOCUMENT_COLUMNS:
            row[doc] = "✓" if r.doc_results.get(doc) else "—"
        row["Missing"] = ", ".join(r.missing_docs) if r.missing_docs else "—"
        df_rows.append(row)

    if not df_rows:
        st.warning("No rows match the selected filters.")
        return

    df = pd.DataFrame(df_rows)

    # Colour-code Status column
    def style_status(val):
        colors = {
            "Completed":        "background-color:#d1f0d8",
            "Incomplete":       "background-color:#fff3cd",
            "Permission Error": "background-color:#fde0e0",
            "Folder Missing":   "background-color:#fde0e0",
            "No Hyperlink":     "background-color:#e9ecef",
            "Empty Folder":     "background-color:#e9ecef",
        }
        return colors.get(val, "")

    styled = df.style.applymap(style_status, subset=["Status"])
    st.dataframe(styled, use_container_width=True, hide_index=True, height=450)


# ──────────────────────────────────────────────────────────────────────────────
# Scanning UI
# ──────────────────────────────────────────────────────────────────────────────

def run_scan(sheet_url: str):
    """
    Execute the verification pipeline with live progress updates.
    """
    log.info("Scan initiated for URL: %s", sheet_url)
    st.session_state["scanning"]      = True
    st.session_state["scan_results"]  = None
    st.session_state["scan_summary"]  = None
    st.session_state["scan_log"]      = []

    creds      = get_credentials()
    write_back = st.session_state.get("write_back", True)

    try:
        orchestrator = VerificationOrchestrator(
            credentials=creds,
            spreadsheet_url=sheet_url,
            write_back=write_back,
        )
    except ValueError as exc:
        st.error(f"❌ {exc}")
        st.session_state["scanning"] = False
        return

    # ── Live progress UI ──────────────────────────────────────────────────────
    progress_bar  = st.progress(0, text="Initialising…")
    status_text   = st.empty()
    log_container = st.empty()
    log_lines: List[str] = []

    def _refresh_log():
        # Show last 15 log lines
        lines_html = "".join(
            f'<div class="log-{"ok" if "✓" in l else "warn" if "⚠" in l else "info"}">'
            f'{l}</div>'
            for l in log_lines[-15:]
        )
        log_container.markdown(
            f'<div class="live-log">{lines_html}</div>',
            unsafe_allow_html=True,
        )

    try:
        for event in orchestrator.run():
            if event.total > 0:
                pct = int(event.current / event.total * 100)
                progress_bar.progress(
                    pct / 100,
                    text=f"Scanning {event.current} / {event.total} rows…",
                )
            status_text.markdown(f"**{event.message}**")

            if event.row_result:
                r = event.row_result
                icon = "✓" if r.display_status == "Completed" else "⚠"
                log_lines.append(
                    f"{icon} Row {r.sheet_row} · {r.brand_name or '(no brand)'} · "
                    f"{r.display_status} · "
                    f"Found: {', '.join(r.found_docs) or '—'}"
                )
                _refresh_log()

            if event.is_final and event.summary:
                st.session_state["scan_results"] = event.summary.results
                st.session_state["scan_summary"] = event.summary

    except Exception as exc:
        log.error("Scan failed: %s", exc, exc_info=True)
        st.error(f"❌ Scan failed: {exc}")

    finally:
        st.session_state["scanning"] = False
        progress_bar.empty()
        status_text.empty()
        log_container.empty()

    st.rerun()


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

def main():
    _init_session()
    _handle_oauth_callback()

    sheet_url = render_sidebar()

    if not is_authenticated():
        st.markdown(f"# {APP_ICON} {APP_NAME}")
        st.markdown("---")
        st.info("👈 Please **Sign in with Google** from the sidebar to get started.")
        return

    if sheet_url:
        run_scan(sheet_url)
    else:
        render_dashboard()


if __name__ == "__main__":
    main()
