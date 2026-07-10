from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets as secrets_lib
import time
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import pandas as pd
import requests
import streamlit as st
from kiteconnect import KiteConnect

from tradingbuddy.auth.app_users import verify_password
from tradingbuddy.auth.kite_token import save_access_token, token_status
from tradingbuddy.config import get_data_root, load_config, require_env
from tradingbuddy.data.storage import Storage
from tradingbuddy.data.supabase_store import SupabaseStore
from tradingbuddy.minervini import RULE_COLUMNS, RULE_LABELS
from tradingbuddy.scan import run_scan


KITE_LOGIN_STATE_TTL_SECONDS = 20 * 60


st.set_page_config(
    page_title="TradingBuddy",
    page_icon="",
    layout="wide",
)


def main() -> None:
    _copy_streamlit_secrets_to_env()
    config = load_config()
    data_root = get_data_root(config)
    storage = Storage(data_root)

    st.title("TradingBuddy")
    st.caption("NSE EQ Minervini screener with Kite data and weekly BUY/SELL signals")

    _handle_kite_callback(config, data_root)
    role = _auth_gate(config)
    if role is None:
        st.info("Sign in to view TradingBuddy results.")
        st.stop()

    if role == "admin":
        _kite_login_panel(config, data_root)
        _scan_panel(config, storage)
    _results_panel(config, storage)
    if role == "admin":
        _rules_panel()


def _copy_streamlit_secrets_to_env() -> None:
    try:
        secrets = st.secrets
    except Exception:
        return

    for key in (
        "KITE_API_KEY",
        "KITE_API_SECRET",
        "DATA_ROOT",
        "APP_ADMIN_USER_ID",
        "APP_ADMIN_PASSWORD",
        "APP_USER_ID",
        "APP_USER_PASSWORD",
        "KITE_REDIRECT_URL",
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "GITHUB_ACTIONS_TOKEN",
        "GITHUB_REPOSITORY",
        "GITHUB_WORKFLOW_ID",
        "GITHUB_BRANCH",
        "ALLOW_STREAMLIT_FULL_SCAN",
    ):
        try:
            value = secrets.get(key)
        except Exception:
            value = None
        if value and not os.getenv(key):
            os.environ[key] = str(value)


def _auth_gate(config: dict[str, Any]) -> str | None:
    supabase = SupabaseStore.from_config(config)
    supabase_configured = supabase is not None
    admin_password = os.getenv("APP_ADMIN_PASSWORD", "").strip()
    admin_user_id = os.getenv("APP_ADMIN_USER_ID", "").strip() or "admin"
    user_id = os.getenv("APP_USER_ID", "").strip()
    user_password = os.getenv("APP_USER_PASSWORD", "").strip()
    configured = supabase_configured or bool(admin_password or (user_id and user_password))
    if not configured:
        st.sidebar.info("Admin mode is open because no app login secrets are set.")
        st.session_state["auth_role"] = "admin"
        st.session_state["auth_user_id"] = "local-admin"
        return "admin"

    role = st.session_state.get("auth_role")
    if role in {"admin", "user"}:
        signed_in_user = st.session_state.get("auth_user_id") or role
        st.sidebar.success(f"Signed in as {signed_in_user} ({role})")
        if st.sidebar.button("Sign out"):
            st.session_state.pop("auth_role", None)
            st.session_state.pop("auth_user_id", None)
            st.rerun()
        return str(role)

    st.sidebar.subheader("Login")
    with st.sidebar.form("app_login"):
        entered_user = st.text_input("User id")
        entered_password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in")

    if submitted:
        try:
            auth_result = _authenticate_app_user(
                supabase=supabase,
                user_id=entered_user,
                password=entered_password,
                admin_user_id=admin_user_id,
                admin_password=admin_password,
                fallback_user_id=user_id,
                fallback_user_password=user_password,
            )
        except Exception as exc:
            st.sidebar.error(f"Login system error: {exc}")
            return None
        if auth_result is not None:
            st.session_state["auth_role"] = auth_result["role"]
            st.session_state["auth_user_id"] = auth_result["user_id"]
            st.rerun()
        st.sidebar.error("Incorrect user id or password")

    return None


def _authenticate_app_user(
    *,
    supabase: SupabaseStore | None,
    user_id: str,
    password: str,
    admin_user_id: str,
    admin_password: str,
    fallback_user_id: str,
    fallback_user_password: str,
) -> dict[str, str] | None:
    normalized_user_id = user_id.strip()
    if not normalized_user_id or not password:
        return None

    if supabase is not None:
        app_user = supabase.load_app_user(normalized_user_id)
        if app_user and verify_password(password, str(app_user.get("password_hash") or "")):
            role = str(app_user.get("role") or "").strip()
            if role in {"admin", "user"}:
                return {"role": role, "user_id": str(app_user.get("user_id") or normalized_user_id)}

    if admin_password and normalized_user_id == admin_user_id and password == admin_password:
        return {"role": "admin", "user_id": admin_user_id}

    if fallback_user_id and fallback_user_password:
        if normalized_user_id == fallback_user_id and password == fallback_user_password:
            return {"role": "user", "user_id": fallback_user_id}

    return None


def _handle_kite_callback(config: dict[str, Any], data_root: Path) -> None:
    request_token = _query_param("request_token")
    if not request_token:
        return

    login_state = _query_param("tb_state")
    if not login_state:
        return

    secret = _kite_login_state_secret()
    if not _is_valid_kite_login_state(login_state, secret):
        st.sidebar.error("Kite callback expired or invalid. Start Kite login again from the admin screen.")
        return

    try:
        result = _save_kite_session(request_token, data_root, config)
    except Exception as exc:
        st.sidebar.error(f"Kite token save failed: {exc}")
        return

    st.session_state["auth_role"] = "admin"
    st.session_state["auth_user_id"] = "kite-callback"
    st.session_state["kite_token_saved_message"] = result
    _clear_query_params()
    st.rerun()


def _kite_login_url(api_key: str) -> str:
    login_url = KiteConnect(api_key=api_key).login_url()
    secret = _kite_login_state_secret()
    if not secret:
        return login_url

    redirect_params = urlencode({"tb_state": _create_kite_login_state(secret)})
    separator = "&" if "?" in login_url else "?"
    return f"{login_url}{separator}{urlencode({'redirect_params': redirect_params})}"


def _kite_login_state_secret() -> str:
    return os.getenv("KITE_API_SECRET", "").strip()


def _create_kite_login_state(secret: str, issued_at: int | None = None, nonce: str | None = None) -> str:
    if not secret.strip():
        return ""
    issued = int(issued_at if issued_at is not None else time.time())
    random_nonce = nonce or secrets_lib.token_urlsafe(16)
    payload = f"{issued}.{random_nonce}"
    return f"{payload}.{_kite_state_signature(payload, secret)}"


def _is_valid_kite_login_state(state: str, secret: str, now: int | None = None) -> bool:
    if not state or not secret.strip():
        return False
    try:
        issued_text, nonce, signature = state.split(".", 2)
        issued = int(issued_text)
    except ValueError:
        return False
    if not nonce or not signature:
        return False

    current = int(now if now is not None else time.time())
    if issued > current + 60:
        return False
    if current - issued > KITE_LOGIN_STATE_TTL_SECONDS:
        return False

    payload = f"{issued}.{nonce}"
    expected = _kite_state_signature(payload, secret)
    return hmac.compare_digest(signature, expected)


def _kite_state_signature(payload: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _kite_login_panel(config: dict[str, Any], data_root: Path) -> None:
    with st.sidebar:
        st.subheader("Kite")
        saved_message = st.session_state.pop("kite_token_saved_message", "")
        if saved_message:
            st.success(saved_message)
        status = _kite_token_status(data_root, config)
        if status["exists"]:
            profile = status.get("profile", {}) or {}
            user_name = profile.get("user_name") or profile.get("user_id") or "saved user"
            st.success(f"Token saved: {user_name}")
            st.caption(f"Source: {status.get('source') or '-'}")
            st.caption(f"Generated: {status.get('generated_at') or '-'}")
            st.caption(f"Expires: {status.get('expires_at') or '-'}")
        else:
            st.warning("No saved Kite token")
        if os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
            st.success("Supabase configured")
        else:
            st.caption("Supabase not configured")

    request_token = _query_param("request_token")
    kite_status = _query_param("status")
    if request_token:
        with st.sidebar:
            st.info("Kite request token detected.")
            if st.button("Save Kite access token", type="primary"):
                try:
                    result = _save_kite_session(request_token, data_root, config)
                    st.success(result)
                    _clear_query_params()
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
    elif kite_status and kite_status != "success":
        st.sidebar.error(f"Kite login failed: {kite_status}")

    with st.sidebar.expander("Kite login", expanded=not status["exists"]):
        api_key = os.getenv("KITE_API_KEY", "").strip()
        redirect_url = os.getenv("KITE_REDIRECT_URL", "").strip() or "http://localhost:8501"
        st.caption("Kite developer console redirect URL")
        st.code(redirect_url, language=None)
        st.caption("For local testing, configure the Kite app redirect URL as the local Streamlit URL. For Streamlit Cloud, use the deployed app URL.")
        if api_key:
            login_url = _kite_login_url(api_key)
            st.link_button("Login with Kite", login_url)
        else:
            st.error("KITE_API_KEY is missing.")

        with st.form("manual_request_token"):
            manual_token = st.text_input("Request token or full failed redirect URL")
            submitted = st.form_submit_button("Save token")
        if submitted:
            request_token_from_input = _extract_request_token(manual_token)
            if not request_token_from_input:
                st.error("Paste the request_token or the full Kite redirect URL containing request_token=...")
            else:
                try:
                    result = _save_kite_session(request_token_from_input, data_root, config)
                    st.success(result)
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))


def _scan_panel(config: dict[str, Any], storage: Storage) -> None:
    st.header("Scanner")
    bundle = _load_result_bundle(config, storage)
    latest = bundle["all_results"]
    latest_pass = bundle["minervini_results"]
    latest_weekly = bundle["weekly_results"]
    latest_summary = bundle["summary"]

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Cached stocks", _scanned_count(latest, latest_summary))
    col2.metric("Minervini", len(latest_pass) if not latest_pass.empty else 0)
    col3.metric("Weekly BUY/SELL", len(latest_weekly) if not latest_weekly.empty else 0)
    col4.metric("Latest candle", _latest_candle_date(latest, latest_summary))
    col5.metric("Last scan", _last_scan_time(latest_summary))
    st.caption(f"Result source: {bundle['source']}")
    if bundle["error"]:
        st.warning(str(bundle["error"]))

    if not latest_summary.empty:
        summary = latest_summary.iloc[-1].to_dict()
        st.caption(
            f"Run: {summary.get('run_id', '-')} | "
            f"Started: {summary.get('run_started_at', '-')} | "
            f"Mode: {summary.get('refresh_mode', '-')} | "
            f"Supabase: {summary.get('supabase_status', '-')}"
        )
        _show_freshness_messages(config, latest_summary)

    _github_scan_panel()

    with st.expander("Run scan in this Streamlit session", expanded=not _github_scan_configured()):
        _streamlit_session_scan_form(config, storage)


def _github_scan_panel() -> None:
    st.subheader("Durable Cloud Scan")
    if not _github_scan_configured():
        st.info(
            "Configure GITHUB_ACTIONS_TOKEN in Streamlit secrets to run scans through GitHub Actions. "
            "This is the recommended path for full NSE scans."
        )
        return

    try:
        settings = _github_scan_settings()
    except ValueError as exc:
        st.error(f"GitHub scan configuration error: {exc}")
        return

    st.caption(f"GitHub workflow: {settings['repo']} / {settings['workflow_id']} on {settings['branch']}")
    with st.form("github_scan"):
        scan_mode = st.radio(
            "Cloud scan mode",
            ["Fresh Kite refresh", "Use cached candles"],
            index=0,
            horizontal=True,
            help="Runs outside Streamlit using GitHub Actions and writes results to Supabase when complete.",
        )
        limit_symbols = st.number_input("Cloud symbol limit (0 means all)", min_value=0, max_value=10000, value=0, step=50)
        submitted = st.form_submit_button(
            "Start durable fresh scan" if scan_mode == "Fresh Kite refresh" else "Start durable cached scan",
            type="primary",
        )

    if not submitted:
        return

    try:
        workflow_url = _dispatch_github_scan(
            cached_only=scan_mode == "Use cached candles",
            max_symbols=int(limit_symbols),
        )
    except Exception as exc:
        st.error(str(exc))
        return

    st.success("GitHub Actions scan started. Refresh Results after the workflow completes.")
    st.link_button("View Workflow Runs", workflow_url)


def _streamlit_session_scan_form(config: dict[str, Any], storage: Storage) -> None:
    full_session_scan_allowed = _allow_streamlit_full_scan()
    if full_session_scan_allowed:
        st.warning("Full scans in Streamlit can stop if the browser disconnects. Prefer Durable Cloud Scan for full NSE runs.")
        default_limit = 0
        limit_help = "0 scans all symbols. Use only for local/debug runs."
    else:
        st.warning("In-session scans are for small tests only. Full NSE scans must use Durable Cloud Scan.")
        default_limit = 100
        limit_help = "Full-universe scans are disabled here to avoid browser/session cancellation."

    with st.form("run_scan"):
        scan_mode = st.radio(
            "Scan mode",
            ["Fresh Kite refresh", "Use cached candles"],
            index=0,
            horizontal=True,
            help="Fresh Kite refresh fetches the latest Kite candles before applying Minervini and weekly BUY/SELL rules.",
        )
        limit_symbols = st.number_input(
            "Session symbol limit",
            min_value=0,
            max_value=10000,
            value=default_limit,
            step=50,
            help=limit_help,
        )
        submitted = st.form_submit_button("Run fresh scan" if scan_mode == "Fresh Kite refresh" else "Run cached scan", type="primary")

    if not submitted:
        return

    if int(limit_symbols) == 0 and not full_session_scan_allowed:
        st.error(
            "Full NSE scans are disabled in the Streamlit session because they can be cancelled when the browser disconnects. "
            "Use Durable Cloud Scan, or set ALLOW_STREAMLIT_FULL_SCAN=true only for local debugging."
        )
        return

    progress_bar = st.progress(0)
    progress_text = st.empty()
    summary_box = st.empty()

    def progress(payload: dict[str, Any]) -> None:
        total = int(payload.get("total") or 0)
        completed = int(payload.get("completed") or 0)
        phase = str(payload.get("phase") or "")
        symbol = str(payload.get("current_symbol") or "")
        if total:
            progress_bar.progress(min(completed / total, 1.0))
            progress_text.write(f"{phase}: {completed}/{total} {symbol}".strip())
        else:
            progress_text.write(phase)

    try:
        result = run_scan(
            config,
            storage,
            refresh_data=scan_mode == "Fresh Kite refresh",
            max_symbols=int(limit_symbols) if int(limit_symbols) > 0 else None,
            progress_callback=progress,
        )
        progress_bar.progress(1.0)
        summary_box.success(
            "Scan complete: "
            f"{result.summary['minervini_pass_count']} passed / "
            f"{result.summary['weekly_buy_sell_count']} weekly signals / "
            f"{result.summary['symbols_scanned']} scanned / "
            f"{result.summary['symbols_updated']} updated / "
            f"{result.summary['symbols_failed']} failed / "
            f"latest candle {result.summary.get('latest_candle_date') or '-'}."
        )
        st.rerun()
    except Exception as exc:
        progress_bar.empty()
        progress_text.empty()
        st.error(str(exc))


def _github_scan_configured() -> bool:
    return bool(os.getenv("GITHUB_ACTIONS_TOKEN", "").strip())


def _github_scan_settings() -> dict[str, str]:
    branch = os.getenv("GITHUB_BRANCH", "main").strip()
    if not branch:
        raise ValueError("GITHUB_BRANCH is empty.")
    return {
        "token": os.getenv("GITHUB_ACTIONS_TOKEN", "").strip(),
        "repo": _normalize_github_repository(os.getenv("GITHUB_REPOSITORY", "careerhops/TradingBuddy")),
        "workflow_id": _normalize_github_workflow_id(os.getenv("GITHUB_WORKFLOW_ID", "run-scan.yml")),
        "branch": branch,
    }


def _normalize_github_repository(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("GITHUB_REPOSITORY is empty. Use owner/repo, for example careerhops/TradingBuddy.")

    parsed = urlparse(raw)
    if parsed.scheme:
        path = parsed.path
        if parsed.netloc.lower() == "api.github.com" and path.startswith("/repos/"):
            path = path[len("/repos/") :]
    elif raw.startswith("git@github.com:"):
        path = raw.split(":", 1)[1]
    else:
        path = raw

    path = path.strip("/")
    if path.startswith("github.com/"):
        path = path[len("github.com/") :]
    if path.startswith("repos/"):
        path = path[len("repos/") :]

    parts = [part for part in path.split("/") if part]
    if len(parts) < 2:
        raise ValueError("GITHUB_REPOSITORY must be owner/repo, for example careerhops/TradingBuddy.")
    owner = parts[0]
    repo = parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    return f"{owner}/{repo}"


def _normalize_github_workflow_id(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("GITHUB_WORKFLOW_ID is empty. Use run-scan.yml.")

    parsed = urlparse(raw)
    path = parsed.path if parsed.scheme else raw
    parts = [part for part in path.strip("/").split("/") if part]
    if "workflows" in parts:
        index = parts.index("workflows")
        if index + 1 < len(parts):
            return parts[index + 1]
    if len(parts) > 1:
        return parts[-1]
    return raw


def _github_workflow_dispatch_request(
    *,
    repo: str,
    workflow_id: str,
    branch: str,
    cached_only: bool,
    max_symbols: int,
) -> tuple[str, dict[str, Any], str]:
    normalized_repo = _normalize_github_repository(repo)
    normalized_workflow_id = _normalize_github_workflow_id(workflow_id)
    normalized_branch = str(branch or "").strip()
    if not normalized_branch:
        raise ValueError("GITHUB_BRANCH is empty.")
    safe_max_symbols = max(int(max_symbols), 0)
    url = f"https://api.github.com/repos/{normalized_repo}/actions/workflows/{normalized_workflow_id}/dispatches"
    payload = {
        "ref": normalized_branch,
        "inputs": {
            "cached_only": "true" if cached_only else "false",
            "max_symbols": str(safe_max_symbols),
        },
    }
    workflow_url = f"https://github.com/{normalized_repo}/actions/workflows/{normalized_workflow_id}"
    return url, payload, workflow_url


def _dispatch_github_scan(*, cached_only: bool, max_symbols: int) -> str:
    settings = _github_scan_settings()
    token = settings["token"]
    if not token:
        raise RuntimeError("GITHUB_ACTIONS_TOKEN is missing from Streamlit secrets.")

    url, payload, workflow_url = _github_workflow_dispatch_request(
        repo=settings["repo"],
        workflow_id=settings["workflow_id"],
        branch=settings["branch"],
        cached_only=cached_only,
        max_symbols=max_symbols,
    )
    response = requests.post(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json=payload,
        timeout=30,
    )
    if response.status_code != 204:
        message = _github_dispatch_error_message(response)
        raise RuntimeError(f"GitHub workflow dispatch failed: HTTP {response.status_code} {message}")
    return workflow_url


def _github_dispatch_error_message(response: requests.Response) -> str:
    body = response.text[:500] if response.text else response.reason
    if response.status_code == 401:
        return f"{body}. Check that GITHUB_ACTIONS_TOKEN is valid."
    if response.status_code == 403:
        return f"{body}. The token needs access to this repository and Actions read/write permission."
    if response.status_code == 404:
        return f"{body}. Check GITHUB_REPOSITORY and GITHUB_WORKFLOW_ID."
    if response.status_code == 422:
        return f"{body}. Check GITHUB_BRANCH and workflow_dispatch inputs."
    return body


def _allow_streamlit_full_scan() -> bool:
    return os.getenv("ALLOW_STREAMLIT_FULL_SCAN", "").strip().lower() in {"1", "true", "yes", "on"}


def _results_panel(config: dict[str, Any], storage: Storage) -> None:
    bundle = _load_result_bundle(config, storage)
    all_results = bundle["all_results"]
    minervini_results = bundle["minervini_results"]
    weekly_results = bundle["weekly_results"]
    overlap_history = bundle["overlap_history"]
    latest_summary = bundle["summary"]
    runs = bundle["runs"]

    st.header("Results")
    st.caption(f"Result source: {bundle['source']}")
    if not latest_summary.empty:
        summary = latest_summary.iloc[-1].to_dict()
        st.caption(
            f"Displayed run: {summary.get('run_id', '-')} | "
            f"Scan date: {summary.get('scan_date', '-')} | "
            f"Started: {summary.get('run_started_at', '-')} | "
            f"Mode: {summary.get('refresh_mode', '-')}"
        )
        _show_freshness_messages(config, latest_summary)
    if bundle["error"]:
        st.warning(str(bundle["error"]))

    if all_results.empty and minervini_results.empty and weekly_results.empty and overlap_history.empty and runs.empty:
        st.warning("No scan results yet.")
        return

    _show_tradingview_overlap_list(minervini_results, weekly_results)

    minervini_tab, weekly_tab, overlap_history_tab, diagnostics_tab, runs_tab = st.tabs(
        ["Minervini Shortlist", "Weekly BUY/SELL", "Overlap History", "All Diagnostics", "Run History"]
    )

    with minervini_tab:
        _show_result_table(
            minervini_results,
            kind="minervini",
            empty_message="No stocks currently pass all 8 Minervini rules.",
            file_name="tradingbuddy_minervini_shortlist.csv",
        )

    with weekly_tab:
        signal_filter = st.segmented_control("Signal", ["All", "BUY", "SELL"], default="All")
        frame = weekly_results.copy()
        if signal_filter in {"BUY", "SELL"} and not frame.empty:
            frame = frame[frame["signal"].astype(str).str.upper() == signal_filter]
        _show_result_table(
            frame,
            kind="weekly",
            empty_message="No fresh weekly BUY/SELL signals in the latest run.",
            file_name="tradingbuddy_weekly_buy_sell_shortlist.csv",
        )

    with overlap_history_tab:
        _show_result_table(
            overlap_history,
            kind="overlap_history",
            empty_message="No overlap history has been recorded yet.",
            file_name="tradingbuddy_overlap_history.csv",
        )

    with diagnostics_tab:
        _show_result_table(
            all_results,
            kind="diagnostics",
            empty_message="No diagnostics available. Full diagnostics are stored only with local Streamlit scan output.",
            file_name="tradingbuddy_all_scan_diagnostics.csv",
        )

    with runs_tab:
        _show_result_table(
            runs,
            kind="runs",
            empty_message="No run history yet.",
            file_name="tradingbuddy_scan_runs.csv",
        )


def _load_result_bundle(config: dict[str, Any], storage: Storage) -> dict[str, Any]:
    local_bundle = _load_local_result_bundle(storage)
    supabase_bundle = _load_supabase_result_bundle(config)
    return _choose_result_bundle(local_bundle, supabase_bundle)


def _choose_result_bundle(local_bundle: dict[str, Any], supabase_bundle: dict[str, Any]) -> dict[str, Any]:
    local_time = _bundle_started_at(local_bundle)
    supabase_time = _bundle_started_at(supabase_bundle)
    if supabase_time is not None and (local_time is None or supabase_time > local_time):
        return supabase_bundle
    if _bundle_has_results(local_bundle):
        return local_bundle
    if _bundle_has_results(supabase_bundle):
        return supabase_bundle
    return local_bundle if local_bundle["error"] else supabase_bundle


def _load_local_result_bundle(storage: Storage) -> dict[str, Any]:
    return {
        "source": "local csv",
        "all_results": storage.load_signals("latest_scan.csv"),
        "minervini_results": storage.load_signals("latest_minervini_pass.csv"),
        "weekly_results": storage.load_signals("latest_weekly_buy_sell.csv"),
        "overlap_history": storage.load_signals("overlap_history.csv"),
        "summary": storage.load_signals("latest_scan_summary.csv"),
        "runs": storage.load_signals("scan_runs.csv"),
        "error": "",
    }


def _load_supabase_result_bundle(config: dict[str, Any]) -> dict[str, Any]:
    empty = {
        "source": "supabase",
        "all_results": pd.DataFrame(),
        "minervini_results": pd.DataFrame(),
        "weekly_results": pd.DataFrame(),
        "overlap_history": pd.DataFrame(),
        "summary": pd.DataFrame(),
        "runs": pd.DataFrame(),
        "error": "",
    }
    supabase = SupabaseStore.from_config(config)
    if supabase is None:
        empty["error"] = "Supabase is not configured, so only local scan CSVs can be displayed."
        return empty
    try:
        latest_run = supabase.load_latest_scan_run()
        if not latest_run:
            return empty
        run_id = str(latest_run.get("run_id") or "")
        if not run_id:
            return empty
        empty["summary"] = pd.DataFrame([latest_run])
        empty["minervini_results"] = supabase.load_minervini_shortlist(run_id)
        empty["weekly_results"] = supabase.load_weekly_shortlist(run_id)
        try:
            empty["overlap_history"] = supabase.load_overlap_history()
        except Exception as exc:
            if _is_missing_overlap_history_table_error(exc):
                empty["error"] = "Overlap history table is not created yet. Run supabase/schema.sql in Supabase SQL editor."
            else:
                empty["error"] = f"Overlap history is not available yet: {exc}"
        empty["runs"] = supabase.load_scan_runs()
        return empty
    except Exception as exc:
        empty["error"] = f"Could not load Supabase results: {exc}"
        return empty


def _is_missing_overlap_history_table_error(exc: Exception) -> bool:
    message = str(exc)
    return "tradingbuddy_overlap_history" in message and ("PGRST205" in message or "HTTP 404" in message)


def _show_freshness_messages(config: dict[str, Any], summary: pd.DataFrame) -> None:
    for level, message in _freshness_messages(config, summary):
        if level == "warning":
            st.warning(message)
        else:
            st.info(message)


def _freshness_messages(
    config: dict[str, Any],
    summary: pd.DataFrame,
    today: pd.Timestamp | None = None,
) -> list[tuple[str, str]]:
    if summary.empty:
        return []

    row = summary.iloc[-1]
    scan_date = pd.to_datetime(row.get("scan_date"), errors="coerce")
    latest_candle_date = pd.to_datetime(row.get("latest_candle_date"), errors="coerce")
    current_day = pd.Timestamp(today).date() if today is not None else _app_today(config)
    messages: list[tuple[str, str]] = []

    if pd.notna(scan_date):
        scan_day = pd.Timestamp(scan_date).date()
        if scan_day < current_day:
            messages.append(
                (
                    "warning",
                    f"Latest completed scan is {scan_day}, not {current_day}. No completed scan has been saved for {current_day}.",
                )
            )
        elif pd.notna(latest_candle_date):
            candle_day = pd.Timestamp(latest_candle_date).date()
            if candle_day < scan_day:
                messages.append(
                    (
                        "info",
                        f"Scan ran on {scan_day}, but the latest daily candle is {candle_day}. Daily close data can lag until the trading day has a candle.",
                    )
                )

    return messages


def _app_today(config: dict[str, Any]) -> date:
    timezone_name = str(config.get("app", {}).get("timezone", "Asia/Kolkata"))
    try:
        return pd.Timestamp.now(tz=timezone_name).date()
    except Exception:
        return pd.Timestamp.now(tz="Asia/Kolkata").date()


def _bundle_has_results(bundle: dict[str, Any]) -> bool:
    return any(
        not bundle[key].empty
        for key in ("all_results", "minervini_results", "weekly_results", "overlap_history", "summary", "runs")
    )


def _bundle_started_at(bundle: dict[str, Any]) -> pd.Timestamp | None:
    summary = bundle.get("summary")
    if not isinstance(summary, pd.DataFrame) or summary.empty or "run_started_at" not in summary.columns:
        return None
    parsed = pd.to_datetime(summary["run_started_at"], errors="coerce", utc=True)
    if parsed.dropna().empty:
        return None
    return parsed.max()


def _show_result_table(frame: pd.DataFrame, kind: str, empty_message: str, file_name: str) -> None:
    if frame.empty:
        st.info(empty_message)
        return

    search = st.text_input("Search symbol/name", value="", key=f"search_{kind}")
    filtered = _filter_search(frame, search)
    st.write(f"{len(filtered)} rows")
    display = _display_frame(filtered, kind)
    st.dataframe(display, width="stretch", hide_index=True, column_config=_result_column_config(display))

    csv = filtered.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download CSV",
        data=csv,
        file_name=file_name,
        mime="text/csv",
        key=f"download_{kind}",
    )


def _show_tradingview_overlap_list(minervini_results: pd.DataFrame, weekly_results: pd.DataFrame) -> None:
    overlap = _tradingview_overlap_symbols(minervini_results, weekly_results)
    st.subheader("TradingView List")
    st.caption("Stocks that pass all Minervini rules and also have a fresh weekly BUY signal.")
    if not overlap:
        st.info("No overlapping Minervini + weekly BUY stocks in the latest scan.")
        return

    text = ",".join(overlap)
    st.text_area(
        "Comma separated symbols",
        value=text,
        height=90,
        key="tradingview_overlap_symbols",
    )
    st.download_button(
        "Download TradingView List",
        data=text.encode("utf-8"),
        file_name="tradingview_minervini_weekly_buy.txt",
        mime="text/plain",
        key="download_tradingview_overlap",
    )


def _tradingview_overlap_symbols(minervini_results: pd.DataFrame, weekly_results: pd.DataFrame) -> list[str]:
    if minervini_results.empty or weekly_results.empty:
        return []
    if "symbol" not in minervini_results.columns or "symbol" not in weekly_results.columns:
        return []

    minervini = minervini_results.copy()
    weekly = weekly_results.copy()
    minervini["exchange"] = minervini.get("exchange", "NSE").astype(str).str.upper().str.strip()
    minervini["symbol"] = minervini["symbol"].astype(str).str.upper().str.strip()
    weekly["exchange"] = weekly.get("exchange", "NSE").astype(str).str.upper().str.strip()
    weekly["symbol"] = weekly["symbol"].astype(str).str.upper().str.strip()

    if "signal" in weekly.columns:
        weekly = weekly[weekly["signal"].astype(str).str.upper() == "BUY"].copy()
    elif "latest_weekly_signal" in weekly.columns:
        weekly = weekly[weekly["latest_weekly_signal"].astype(str).str.upper() == "BUY"].copy()

    keys = set(zip(minervini["exchange"], minervini["symbol"]))
    overlap: list[str] = []
    for exchange, symbol in sorted(set(zip(weekly["exchange"], weekly["symbol"]))):
        if (exchange, symbol) in keys and exchange and symbol:
            overlap.append(f"{exchange}:{symbol}")
    return overlap


def _rules_panel() -> None:
    with st.expander("Minervini rules"):
        rules = pd.DataFrame(
            [{"rule": index + 1, "column": column, "definition": RULE_LABELS[column]} for index, column in enumerate(RULE_COLUMNS)]
        )
        st.dataframe(rules, width="stretch", hide_index=True)


def _filter_search(frame: pd.DataFrame, search: str) -> pd.DataFrame:
    if frame.empty or not search.strip() or "symbol" not in frame.columns:
        return frame
    needle = search.strip().upper()
    mask = frame["symbol"].astype(str).str.upper().str.contains(needle, na=False)
    if "name" in frame.columns:
        mask = mask | frame["name"].astype(str).str.upper().str.contains(needle, na=False)
    return frame[mask].copy()


def _display_frame(frame: pd.DataFrame, kind: str) -> pd.DataFrame:
    if frame.empty:
        return frame

    if kind == "weekly":
        columns = [
            "run_started_at",
            "tradingview_symbol",
            "name",
            "signal",
            "signal_date",
            "signal_price",
            "current_price",
            "gain_loss_pct",
            "price_source",
            "bars_since_weekly_signal",
            "passes_minervini",
            "minervini_pass_count",
        ]
    elif kind == "overlap_history":
        columns = [
            "run_started_at",
            "scan_date",
            "tradingview_symbol",
            "name",
            "signal_date",
            "signal_price",
            "scan_close_date",
            "scan_close_price",
            "gain_loss_pct",
            "price_source",
            "relative_strength_rank",
            "minervini_pass_count",
            "weekly_volume_confirmation",
            "weekly_trend_confirmation",
            "run_id",
        ]
    elif kind == "runs":
        columns = [
            "run_started_at",
            "run_completed_at",
            "scan_date",
            "refresh_mode",
            "symbols_scanned",
            "symbols_updated",
            "symbols_failed",
            "minervini_pass_count",
            "weekly_buy_sell_count",
            "overlap_count",
            "latest_candle_date",
            "ltp_status",
            "supabase_status",
            "run_id",
        ]
    else:
        columns = [
            "run_started_at",
            "tradingview_symbol",
            "name",
            "passes_minervini",
            "minervini_pass_count",
            "shortlist_date",
            "shortlisted_price",
            "current_price",
            "gain_loss_pct",
            "price_source",
            "relative_strength_rank",
            "relative_strength_return_pct",
            "latest_weekly_signal",
            "latest_weekly_signal_date",
            "fresh_weekly_buy",
            "close",
            "pct_above_52w_low",
            "pct_below_52w_high",
        ]
        columns.extend([column for column in RULE_COLUMNS if column in frame.columns])

    available = [column for column in columns if column in frame.columns]
    display = frame[available].copy()

    for column in display.columns:
        if column.endswith("_date") or column == "as_of_date":
            display[column] = pd.to_datetime(display[column], errors="coerce").dt.strftime("%Y-%m-%d")
        if column.endswith("_at"):
            display[column] = pd.to_datetime(display[column], errors="coerce").dt.strftime("%Y-%m-%d %H:%M:%S")

    numeric_columns = display.select_dtypes(include=["float", "float64", "int", "int64"]).columns
    for column in numeric_columns:
        display[column] = pd.to_numeric(display[column], errors="coerce").round(2)
    if "gain_loss_pct" in display.columns:
        display["gain_loss_pct"] = pd.to_numeric(display["gain_loss_pct"], errors="coerce").round(2)

    return display


def _result_column_config(display: pd.DataFrame) -> dict[str, Any]:
    config: dict[str, Any] = {}
    if "gain_loss_pct" in display.columns:
        config["gain_loss_pct"] = st.column_config.NumberColumn(
            "gain_loss_pct",
            format="%.2f%%",
        )
    return config


def _kite_token_status(data_root: Path, config: dict[str, Any]) -> dict[str, Any]:
    local_status = token_status(data_root)
    if local_status.get("exists"):
        return local_status

    supabase = SupabaseStore.from_config(config)
    if supabase is None:
        return local_status

    try:
        token_row = supabase.load_kite_token()
    except Exception:
        return local_status
    if not token_row:
        return local_status
    return {
        "exists": True,
        "generated_at": token_row.get("generated_at"),
        "expires_at": token_row.get("expires_at"),
        "expired": False,
        "profile": token_row.get("profile", {}),
        "source": "supabase",
    }


def _save_kite_session(request_token: str, data_root: Path, config: dict[str, Any]) -> str:
    api_key = require_env("KITE_API_KEY")
    api_secret = require_env("KITE_API_SECRET")
    kite = KiteConnect(api_key=api_key)
    session = kite.generate_session(request_token, api_secret=api_secret)
    access_token = session["access_token"]
    kite.set_access_token(access_token)
    profile = kite.profile()
    local_path = save_access_token(data_root, access_token, profile, ttl_hours=24)
    destinations = [f"local {local_path}"]
    supabase = SupabaseStore.from_config(config)
    if supabase is not None:
        supabase.save_kite_token(access_token, profile, ttl_hours=24)
        destinations.append("Supabase")
    return "Kite token saved for 24 hours to " + " and ".join(destinations)


def _query_param(name: str) -> str:
    try:
        value = st.query_params.get(name, "")
    except Exception:
        return ""
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value or "")


def _extract_request_token(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "request_token=" not in raw:
        return raw
    parsed = urlparse(raw)
    params = parse_qs(parsed.query)
    token_values = params.get("request_token") or []
    return str(token_values[0]).strip() if token_values else ""


def _clear_query_params() -> None:
    try:
        st.query_params.clear()
    except Exception:
        pass


def _latest_candle_date(frame: pd.DataFrame, summary: pd.DataFrame | None = None) -> str:
    if not frame.empty and "as_of_date" in frame.columns:
        dates = pd.to_datetime(frame["as_of_date"], errors="coerce")
        if not dates.dropna().empty:
            return str(dates.max().date())
    if summary is not None and not summary.empty and "latest_candle_date" in summary.columns:
        value = str(summary.iloc[-1].get("latest_candle_date") or "").strip()
        if value and value.lower() != "nan":
            return value
    return "-"


def _scanned_count(all_results: pd.DataFrame, summary: pd.DataFrame) -> int:
    if not all_results.empty:
        return len(all_results)
    if not summary.empty and "symbols_scanned" in summary.columns:
        value = pd.to_numeric(pd.Series([summary.iloc[-1].get("symbols_scanned")]), errors="coerce").iloc[0]
        if pd.notna(value):
            return int(value)
    return 0


def _last_scan_time(summary: pd.DataFrame) -> str:
    if summary.empty or "run_started_at" not in summary.columns:
        return "-"
    parsed = pd.to_datetime(pd.Series([summary.iloc[-1].get("run_started_at")]), errors="coerce")
    if parsed.dropna().empty:
        return "-"
    return parsed.iloc[0].strftime("%Y-%m-%d %H:%M")


if __name__ == "__main__":
    main()
