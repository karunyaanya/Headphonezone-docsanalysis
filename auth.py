"""
auth.py
-------
Google OAuth 2.0 authentication - fixed for Streamlit + Render redirect handling.
"""

import os
from typing import Optional, Dict, Any

import streamlit as st
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

from config import SCOPES, REDIRECT_URI
from logger import get_logger

log = get_logger("auth")


def _get_client_config() -> Dict[str, Any]:
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

    client_id     = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    redirect      = os.environ.get("REDIRECT_URI", REDIRECT_URI)

    if not client_id or not client_secret:
        raise EnvironmentError(
            "Google OAuth credentials not found. "
            "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET."
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


def _build_flow() -> Flow:
    config = _get_client_config()
    redirect = _get_redirect_uri()

    flow = Flow.from_client_config(
        config,
        scopes=SCOPES,
        redirect_uri=redirect,
    )

    return flow


def get_auth_url() -> str:
    flow = _build_flow()

    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )

    st.session_state["oauth_state"] = state

    # Store PKCE verifier if generated
    if hasattr(flow, "code_verifier"):
        st.session_state["code_verifier"] = flow.code_verifier

    log.info("Generated OAuth URL (state=%s)", state)

    return auth_url


def exchange_code_for_token(code: str) -> tuple:
    """
    Exchange auth code for credentials.
    Returns (True, "") on success, (False, error_message) on failure.
    """

    if st.session_state.get("_code_exchanged") == code:
        log.info("Code already exchanged, skipping.")
        return True, ""

    try:
        flow = _build_flow()

        # Restore PKCE verifier
        code_verifier = st.session_state.get("code_verifier")
        if code_verifier:
            flow.code_verifier = code_verifier

        flow.fetch_token(code=code)

        creds = flow.credentials

        _store_credentials(creds)
        _fetch_and_store_user_info(creds)

        st.session_state["_code_exchanged"] = code

        log.info("OAuth token exchange successful.")

        return True, ""

    except Exception as exc:
        error_msg = str(exc)

        log.error(
            "Token exchange failed: %s",
            error_msg,
            exc_info=True
        )

        st.session_state.pop("credentials", None)
        st.session_state.pop("_code_exchanged", None)

        if "redirect_uri_mismatch" in error_msg.lower():
            return False, (
                "❌ Redirect URI mismatch. "
                "Make sure REDIRECT_URI in Render exactly matches "
                "the Authorized Redirect URI in Google Cloud Console.\n\n"
                f"Current REDIRECT_URI: `{_get_redirect_uri()}`"
            )

        if "invalid_grant" in error_msg.lower():
            return False, (
                "❌ OAuth verification failed. "
                "Please sign in again."
            )

        return False, f"❌ Authentication error: {error_msg}"

def get_credentials() -> Optional[Credentials]:
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

        if creds.expired and creds.refresh_token:
            log.info("Refreshing expired access token.")
            creds.refresh(Request())
            _store_credentials(creds)

        return creds
    except Exception as exc:
        log.error("Failed to restore credentials: %s", exc, exc_info=True)
        return None


def is_authenticated() -> bool:
    return get_credentials() is not None


def logout() -> None:
    for key in ["credentials", "user_info", "oauth_state", "_code_exchanged"]:
        st.session_state.pop(key, None)
    log.info("User logged out.")


def get_user_info() -> Dict[str, str]:
    return st.session_state.get("user_info", {})


def _store_credentials(creds: Credentials) -> None:
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
    try:
        service = build("oauth2", "v2", credentials=creds)
        info = service.userinfo().get().execute()
        st.session_state["user_info"] = {
            "email":   info.get("email", ""),
            "name":    info.get("name", ""),
            "picture": info.get("picture", ""),
        }
        log.info("Authenticated: %s", info.get("email"))
    except Exception as exc:
        log.warning("Could not fetch user info: %s", exc)
        st.session_state["user_info"] = {}
