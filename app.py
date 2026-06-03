"""
app.py - Import Document Verification System
"""

import io
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
from config import APP_ICON, APP_NAME, DOCUMENT_COLUMNS, EXPORT_DATE_FORMAT
from dashboard import VerificationOrchestrator, RowResult, ScanSummary
from logger import get_logger
from utils import extract_spreadsheet_id

log = get_logger("app")

st.set_page_config(
    page_title=APP_NAME,
    page_icon=APP_ICON,
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .main .block-container { padding-top: 1.5rem; padding-bottom: 2rem; }
    div[data-testid="metric-container"] {
        background: #f8f9fb;
        border: 1px solid #e0e4ea;
        border-radius: 10px;
        padding: 0.8rem 1rem;
    }
    .live-log {
        background:#1e1e2e; color:#cdd6f4;
        font-family: 'Courier New', monospace; font-size: 0.78rem;
        padding: 10px 14px; border-radius: 8px;
        max-height: 220px; overflow-y: auto;
    }
    .log-ok   { color: #a6e3a1; }
    .log-warn { color: #f38ba8; }
    .log-info { color: #89b4fa; }
    section[data-testid="stSidebar"] { background: #f0f2f8; }
</style>
""", unsafe_allow_html=True)


# ── Session state ─────────────────────────────────────────────────────────────

def _init_session():
    defaults = {
        "scan_results": None,
        "scan_summary": None,
        "scanning":     False,
        "auth_error":   "",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ── OAuth callback ─────────────────────────────────────────────────────────────

def _handle_oauth_callback():
    """
    Detect ?code=... in the URL and exchange it once.
    Uses a flag to prevent re-running on Streamlit reruns.
    """
    params = st.query_params

    # Already authenticated — clear any stale code from URL
    if is_authenticated():
        if "code" in params:
            st.query_params.clear()
        return

    code  = params.get("code")
    error = params.get("error")

    if error:
        st.query_params.clear()
        st.session_state["auth_error"] = f"Google sign-in was cancelled or denied: {error}"
        return

    if code:
        # Show spinner while exchanging
        with st.spinner("Completing Google Sign-In…"):
            ok = exchange_code_for_token(code)

        # Clear code from URL regardless of outcome
        st.query_params.clear()

        if ok:
            st.session_state["auth_error"] = ""
            log.info("Sign-in complete, rerunning.")
            st.rerun()
        else:
            st.session_state["auth_error"] = (
                "Authentication failed. Please try signing in again."
            )


# ── Sidebar ───────────────────────────────────────────────────────────────────

def render_sidebar() -> Optional[str]:
    with st.sidebar:
        st.markdown(f"## {APP_ICON} {APP_NAME}")
        st.divider()

        # ── Not signed in ─────────────────────────────────────────────────────
        if not is_authenticated():
            st.markdown("### 🔐 Sign In")
            st.markdown("Sign in with your Google Workspace account.")

            if st.session_state.get("auth_error"):
                st.error(st.session_state["auth_error"])

            try:
                auth_url = get_auth_url()
                st.link_button(
                    "Sign in with Google", auth_url,
                    use_container_width=True,
                )
            except EnvironmentError as exc:
                st.error(f"⚠️ OAuth not configured:\n\n{exc}")
            return None

        # ── Signed in ─────────────────────────────────────────────────────────
        user = get_user_info()
        st.markdown(f"👤 **{user.get('name', 'User')}**")
        st.caption(user.get("email", ""))

        if st.button("Logout", use_container_width=True):
            logout()
            st.rerun()

        st.divider()

        # ── Sheet URL ─────────────────────────────────────────────────────────
        st.markdown("### 📊 Google Sheet")
        sheet_url = st.text_area(
            "Paste your Google Sheet URL:",
            height=90,
            placeholder="https://docs.google.com/spreadsheets/d/…",
            key="sheet_url_input",
        )
        write_back = st.checkbox(
            "✏️ Write results back to sheet",
            value=True,
            help="Marks document columns with 'X' when found.",
        )
        st.session_state["write_back"] = write_back

        scan_clicked = st.button(
            "🔍 Start Scan",
            use_container_width=True,
            type="primary",
            disabled=st.session_state.get("scanning", False),
        )

        st.divider()
        st.markdown("### 📥 Export")
        if st.session_state.get("scan_results"):
            _render_export_buttons()
        else:
            st.caption("Run a scan to enable exports.")

        st.divider()
        st.caption("Import Document Verifier · v1.0.0")

    if scan_clicked:
        url = (sheet_url or "").strip()
        if not url:
            st.sidebar.error("Please enter a Google Sheet URL.")
            return None
        if not extract_spreadsheet_id(url):
            st.sidebar.error("Invalid Google Sheets URL.")
            return None
        return url

    return None


# ── Export ────────────────────────────────────────────────────────────────────

def _render_export_buttons():
    results: List[RowResult] = st.session_state["scan_results"]
    df = _results_to_dataframe(results)
    ts = datetime.now().strftime(EXPORT_DATE_FORMAT)

    st.download_button(
        "⬇️ Export CSV",
        data=df.to_csv(index=False).encode("utf-8"),
        file_name=f"verification_{ts}.csv",
        mime="text/csv",
        use_container_width=True,
    )

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Results", index=False)
        _write_summary_sheet(writer, st.session_state.get("scan_summary"))
    buf.seek(0)
    st.download_button(
        "⬇️ Export Excel",
        data=buf,
        file_name=f"verification_{ts}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )


def _results_to_dataframe(results: List[RowResult]) -> pd.DataFrame:
    rows = []
    for r in results:
        row = {
            "Sheet Row":    r.sheet_row,
            "Brand":        r.brand_name,
            "Folder URL":   r.brand_url or "",
            "Status":       r.display_status,
            "Found Docs":   ", ".join(r.found_docs),
            "Missing Docs": ", ".join(r.missing_docs),
        }
        for doc in DOCUMENT_COLUMNS:
            row[doc] = "X" if r.doc_results.get(doc) else ""
        rows.append(row)
    return pd.DataFrame(rows)


def _write_summary_sheet(writer, summary: Optional[ScanSummary]):
    if not summary:
        return
    pd.DataFrame({
        "Metric": ["Total Rows", "Completed", "Incomplete",
                   "Permission Errors", "Folder Missing",
                   "Docs Found", "Docs Missing", "Elapsed (s)"],
        "Value":  [summary.total_rows, summary.completed, summary.incomplete,
                   summary.permission_errors, summary.folder_missing,
                   summary.docs_found, summary.docs_missing,
                   round(summary.elapsed_seconds, 1)],
    }).to_excel(writer, sheet_name="Summary", index=False)


# ── Dashboard ─────────────────────────────────────────────────────────────────

def render_dashboard():
    st.markdown(f"# {APP_ICON} {APP_NAME}")

    summary: Optional[ScanSummary] = st.session_state.get("scan_summary")
    results: Optional[List[RowResult]] = st.session_state.get("scan_results")

    if summary:
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("📦 Total Brands",     summary.total_rows)
        c2.metric("✅ Completed",         summary.completed)
        c3.metric("⏳ Incomplete",        summary.incomplete)
        c4.metric("📄 Docs Found",        summary.docs_found)
        c5.metric("❌ Docs Missing",      summary.docs_missing)
        st.caption(
            f"Completed in {summary.elapsed_seconds:.1f}s · "
            f"{summary.permission_errors} permission error(s) · "
            f"{summary.folder_missing} missing folder(s)"
        )
        st.divider()

    if results:
        _render_results_table(results)
    else:
        st.info("👈 Paste your Google Sheet URL in the sidebar and click **Start Scan**.", icon="ℹ️")
        st.markdown("""
**How it works:**
1. Paste your Google Sheet URL in the sidebar
2. Click **Start Scan**
3. The app reads every Brand row, opens its Drive folder, and marks document columns with **X**
4. Download the full report as CSV or Excel
        """)


def _render_results_table(results: List[RowResult]):
    st.markdown("### 📋 Verification Results")

    col_f1, col_f2, col_f3 = st.columns([2, 2, 2])
    with col_f1:
        status_filter = st.multiselect(
            "Filter by Status",
            ["Completed", "Incomplete", "Permission Error",
             "Folder Missing", "No Hyperlink", "Empty Folder"],
            default=[],
        )
    with col_f2:
        missing_doc = st.selectbox("Missing document", ["(All)"] + DOCUMENT_COLUMNS)
    with col_f3:
        brand_search = st.text_input("Search Brand", placeholder="Type to filter…")

    filtered = results
    if status_filter:
        filtered = [r for r in filtered if r.display_status in status_filter]
    if missing_doc != "(All)":
        filtered = [r for r in filtered if not r.doc_results.get(missing_doc, True)]
    if brand_search:
        filtered = [r for r in filtered if brand_search.upper() in r.brand_name.upper()]

    st.caption(f"Showing {len(filtered)} of {len(results)} rows")

    df_rows = []
    for r in filtered:
        row = {"Row": r.sheet_row, "Brand": r.brand_name, "Status": r.display_status}
        for doc in DOCUMENT_COLUMNS:
            row[doc] = "✓" if r.doc_results.get(doc) else "—"
        row["Missing"] = ", ".join(r.missing_docs) or "—"
        df_rows.append(row)

    if not df_rows:
        st.warning("No rows match the selected filters.")
        return

    df = pd.DataFrame(df_rows)

    def style_status(val):
        return {
            "Completed":        "background-color:#d1f0d8",
            "Incomplete":       "background-color:#fff3cd",
            "Permission Error": "background-color:#fde0e0",
            "Folder Missing":   "background-color:#fde0e0",
        }.get(val, "background-color:#e9ecef")

    st.dataframe(
        df.style.applymap(style_status, subset=["Status"]),
        use_container_width=True,
        hide_index=True,
        height=450,
    )


# ── Scan runner ───────────────────────────────────────────────────────────────

def run_scan(sheet_url: str):
    log.info("Scan started: %s", sheet_url)
    st.session_state["scanning"]     = True
    st.session_state["scan_results"] = None
    st.session_state["scan_summary"] = None

    creds = get_credentials()
    try:
        orchestrator = VerificationOrchestrator(
            credentials=creds,
            spreadsheet_url=sheet_url,
            write_back=st.session_state.get("write_back", True),
        )
    except ValueError as exc:
        st.error(f"❌ {exc}")
        st.session_state["scanning"] = False
        return

    progress_bar  = st.progress(0, text="Initialising…")
    status_text   = st.empty()
    log_container = st.empty()
    log_lines: List[str] = []

    def refresh_log():
        lines_html = "".join(
            f'<div class="log-{"ok" if "✓" in l else "warn" if "⚠" in l else "info"}">{l}</div>'
            for l in log_lines[-15:]
        )
        log_container.markdown(
            f'<div class="live-log">{lines_html}</div>',
            unsafe_allow_html=True,
        )

    try:
        for event in orchestrator.run():
            if event.total > 0:
                progress_bar.progress(
                    event.current / event.total,
                    text=f"Scanning {event.current} / {event.total} rows…",
                )
            status_text.markdown(f"**{event.message}**")

            if event.row_result:
                r = event.row_result
                icon = "✓" if r.display_status == "Completed" else "⚠"
                log_lines.append(
                    f"{icon} Row {r.sheet_row} · {r.brand_name or '—'} · "
                    f"{r.display_status} · Found: {', '.join(r.found_docs) or '—'}"
                )
                refresh_log()

            if event.is_final and event.summary:
                st.session_state["scan_results"] = event.summary.results
                st.session_state["scan_summary"] = event.summary

    except Exception as exc:
        log.error("Scan failed: %s", exc, exc_info=True)
        st.error(f"❌ Scan error: {exc}")
    finally:
        st.session_state["scanning"] = False
        progress_bar.empty()
        status_text.empty()
        log_container.empty()

    st.rerun()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    _init_session()
    _handle_oauth_callback()   # ← must run before render_sidebar

    sheet_url = render_sidebar()

    if not is_authenticated():
        st.markdown(f"# {APP_ICON} {APP_NAME}")
        st.divider()
        st.info("👈 Please **Sign in with Google** from the sidebar to get started.")
        return

    if sheet_url:
        run_scan(sheet_url)
    else:
        render_dashboard()


if __name__ == "__main__":
    main()
