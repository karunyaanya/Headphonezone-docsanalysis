"""
auth.py
-------
Google OAuth 2.0 authentication for the Import Document Verification System.

Flow:
  1. Build an authorisation URL.
  2. User is redirected to Google and grants access.
  3. Google returns an authorisation code via the redirect URI.
  4. Exchange the code for access + refresh tokens.
  5. Store credentials in st.session_state.
  6. Refresh tokens automatically when expired.
"""

import json
import os
import time
from typing import Optional, Dict, Any

import streamlit as st
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

from config import SCOPES, REDIRECT_URI
from logger import get_logger

log = get_logger("auth")


# ──────────────────────────────────────────────────────────────────────────────
# OAuth client config (loaded from Streamlit secrets or environment)
# ──────────────────────────────────────────────────────────────────────────────

def _get_client_config() -> Dict[str, Any]:
    """
    Build the OAuth client_config dict expected by google_auth_oauthlib.

    Priority:
      1. st.secrets["google_oauth"] dict
      2. GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET environment variables
    """
    # ── Try Streamlit secrets first ──────────────────────────────────────────
    try:
        sec = st.secrets["google_oauth"]
        return {
            "web": {
                "client_id":     sec["client_id"],
                "client_secret": sec["client_secret"],
                "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
                "token_uri":     "https://oauth2.googleapis.com/token",
                "redirect_uris": [sec.get("redirect_uri", REDIRECT_URI)],
            }
        }
    except (KeyError, FileNotFoundError):
        pass

    # ── Fall back to environment variables ───────────────────────────────────
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    redirect = os.environ.get("REDIRECT_URI", REDIRECT_URI)

    if not client_id or not client_secret:
        raise EnvironmentError(
            "Google OAuth credentials not found. "
            "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET environment "
            "variables, or configure [google_oauth] in .streamlit/secrets.toml."
        )

    return {
        "web": {
            "client_id":     client_id,
            "client_secret": client_secret,
            "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
            "token_uri":     "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect],
        }
    }


# ──────────────────────────────────────────────────────────────────────────────
# Build OAuth Flow
# ──────────────────────────────────────────────────────────────────────────────

def _build_flow() -> Flow:
    config = _get_client_config()
    redirect = config["web"]["redirect_uris"][0]
    flow = Flow.from_client_config(
        config,
        scopes=SCOPES,
        redirect_uri=redirect,
    )
    return flow


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def get_auth_url() -> str:
    """
    Generate the Google OAuth authorisation URL.
    Stores the flow state in session_state so it survives the redirect.
    """
    flow = _build_flow()
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    st.session_state["oauth_state"] = state
    log.info("Generated OAuth authorisation URL (state=%s)", state)
    return auth_url


def exchange_code_for_token(code: str) -> bool:
    """
    Exchange an authorisation code for credentials.
    Stores the credentials in st.session_state["credentials"].

    Returns True on success, False on failure.
    """
    try:
        flow = _build_flow()
        flow.fetch_token(code=code)
        creds = flow.credentials
        _store_credentials(creds)
        _fetch_and_store_user_info(creds)
        log.info("OAuth token exchange successful.")
        return True
    except Exception as exc:
        log.error("OAuth token exchange failed: %s", exc, exc_info=True)
        st.session_state.pop("credentials", None)
        return False


def get_credentials() -> Optional[Credentials]:
    """
    Return valid Google credentials from session state, refreshing if needed.
    Returns None if the user is not authenticated.
    """
    creds_dict = st.session_state.get("credentials")
    if not creds_dict:
        return None

    try:
        creds = Credentials(
            token=creds_dict["token"],
            refresh_token=creds_dict.get("refresh_token"),
            token_uri=creds_dict.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=creds_dict.get("client_id"),
            client_secret=creds_dict.get("client_secret"),
            scopes=creds_dict.get("scopes"),
        )

        # Refresh if expired
        if creds.expired and creds.refresh_token:
            log.info("Refreshing expired access token.")
            creds.refresh(Request())
            _store_credentials(creds)

        return creds
    except Exception as exc:
        log.error("Failed to restore credentials: %s", exc, exc_info=True)
        return None


def is_authenticated() -> bool:
    """Return True if the user has valid credentials in session state."""
    return get_credentials() is not None


def logout() -> None:
    """Clear all authentication state from the session."""
    for key in ["credentials", "user_info", "oauth_state"]:
        st.session_state.pop(key, None)
    log.info("User logged out.")


def get_user_info() -> Dict[str, str]:
    """Return stored user info (email, name, picture)."""
    return st.session_state.get("user_info", {})


# ──────────────────────────────────────────────────────────────────────────────
# Private helpers
# ──────────────────────────────────────────────────────────────────────────────

def _store_credentials(creds: Credentials) -> None:
    """Serialise credentials into session state."""
    st.session_state["credentials"] = {
        "token":         creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri":     creds.token_uri,
        "client_id":     creds.client_id,
        "client_secret": creds.client_secret,
        "scopes":        list(creds.scopes) if creds.scopes else SCOPES,
        "expiry":        creds.expiry.isoformat() if creds.expiry else None,
    }


def _fetch_and_store_user_info(creds: Credentials) -> None:
    """Fetch the authenticated user's profile and store it in session state."""
    try:
        service = build("oauth2", "v2", credentials=creds)
        info = service.userinfo().get().execute()
        st.session_state["user_info"] = {
            "email":   info.get("email", ""),
            "name":    info.get("name", ""),
            "picture": info.get("picture", ""),
        }
        log.info("Authenticated user: %s", info.get("email"))
    except Exception as exc:
        log.warning("Could not fetch user info: %s", exc)
        st.session_state["user_info"] = {}
