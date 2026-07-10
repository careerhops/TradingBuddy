from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import requests

from tradingbuddy.config import get_setting


SCAN_RUN_COLUMNS = {
    "run_id",
    "run_started_at",
    "run_completed_at",
    "scan_date",
    "history_start_date",
    "refresh_mode",
    "symbols_scanned",
    "symbols_updated",
    "symbols_failed",
    "minervini_pass_count",
    "weekly_buy_sell_count",
    "overlap_count",
    "scan_rows_saved",
    "latest_candle_date",
}

SCAN_ROW_COLUMNS = {
    "run_id",
    "run_started_at",
    "scan_sequence",
    "exchange",
    "symbol",
    "tradingview_symbol",
    "name",
    "instrument_token",
    "fetch_status",
    "fetch_error",
    "new_rows",
    "as_of_date",
    "daily_rows",
    "close",
    "current_price",
    "price_source",
    "sma_50",
    "sma_150",
    "sma_200",
    "sma_200_prior",
    "high_52w",
    "low_52w",
    "pct_above_52w_low",
    "pct_below_52w_high",
    "relative_strength_return_pct",
    "relative_strength_rank",
    "minervini_pass_count",
    "passes_minervini",
    "rule_1_price_above_150_200_sma",
    "rule_2_sma150_above_sma200",
    "rule_3_sma200_trending_up",
    "rule_4_sma50_above_150_200",
    "rule_5_price_above_sma50",
    "rule_6_price_30pct_above_52w_low",
    "rule_7_price_within_25pct_of_52w_high",
    "rule_8_relative_strength_rank_70",
    "scan_note",
    "latest_weekly_signal",
    "latest_weekly_signal_date",
    "latest_weekly_signal_close",
    "bars_since_weekly_signal",
    "fresh_weekly_signal",
    "fresh_weekly_buy",
    "weekly_volume_confirmation",
    "weekly_volume_confirmation_ratio",
    "weekly_trend_confirmation",
    "weekly_demand_zone",
    "weekly_supply_zone",
}

MINERVINI_COLUMNS = {
    "run_id",
    "run_started_at",
    "shortlist_date",
    "exchange",
    "symbol",
    "tradingview_symbol",
    "name",
    "shortlisted_price",
    "current_price",
    "gain_loss_pct",
    "price_source",
    "as_of_date",
    "relative_strength_rank",
    "relative_strength_return_pct",
    "minervini_pass_count",
    "rule_1_price_above_150_200_sma",
    "rule_2_sma150_above_sma200",
    "rule_3_sma200_trending_up",
    "rule_4_sma50_above_150_200",
    "rule_5_price_above_sma50",
    "rule_6_price_30pct_above_52w_low",
    "rule_7_price_within_25pct_of_52w_high",
    "rule_8_relative_strength_rank_70",
    "latest_weekly_signal",
    "latest_weekly_signal_date",
}

OVERLAP_HISTORY_COLUMNS = {
    "run_id",
    "run_started_at",
    "scan_date",
    "scan_close_date",
    "exchange",
    "symbol",
    "tradingview_symbol",
    "name",
    "signal_date",
    "signal_price",
    "scan_close_price",
    "gain_loss_pct",
    "price_source",
    "minervini_pass_count",
    "relative_strength_rank",
    "weekly_volume_confirmation",
    "weekly_trend_confirmation",
}

APP_USER_COLUMNS = {
    "user_id",
    "role",
    "password_hash",
    "display_name",
    "is_active",
}

WEEKLY_COLUMNS = {
    "run_id",
    "run_started_at",
    "shortlist_date",
    "exchange",
    "symbol",
    "tradingview_symbol",
    "name",
    "signal",
    "signal_date",
    "signal_price",
    "current_price",
    "gain_loss_pct",
    "price_source",
    "bars_since_weekly_signal",
    "weekly_volume_confirmation",
    "weekly_volume_confirmation_ratio",
    "weekly_trend_confirmation",
    "weekly_demand_zone",
    "weekly_supply_zone",
    "minervini_pass_count",
    "passes_minervini",
}


class SupabaseStore:
    def __init__(
        self,
        url: str,
        service_role_key: str,
        scan_runs_table: str,
        scan_rows_table: str,
        minervini_table: str,
        weekly_table: str,
        overlap_history_table: str,
        kite_tokens_table: str,
        app_users_table: str,
    ) -> None:
        self.url = url.rstrip("/")
        self.service_role_key = service_role_key
        self.scan_runs_table = scan_runs_table
        self.scan_rows_table = scan_rows_table
        self.minervini_table = minervini_table
        self.weekly_table = weekly_table
        self.overlap_history_table = overlap_history_table
        self.kite_tokens_table = kite_tokens_table
        self.app_users_table = app_users_table

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "SupabaseStore | None":
        cfg = config.get("supabase", {}) or {}
        if not bool(cfg.get("enabled", True)):
            return None

        url = get_setting(str(cfg.get("url_env", "SUPABASE_URL"))) or ""
        key = get_setting(str(cfg.get("service_role_key_env", "SUPABASE_SERVICE_ROLE_KEY"))) or ""
        if not url.strip() or not key.strip():
            return None

        return cls(
            url=url,
            service_role_key=key,
            scan_runs_table=str(cfg.get("scan_runs_table", "tradingbuddy_scan_runs")),
            scan_rows_table=str(cfg.get("scan_rows_table", "tradingbuddy_scan_rows")),
            minervini_table=str(cfg.get("minervini_table", "tradingbuddy_minervini_shortlists")),
            weekly_table=str(cfg.get("weekly_table", "tradingbuddy_weekly_buy_sell_shortlists")),
            overlap_history_table=str(cfg.get("overlap_history_table", "tradingbuddy_overlap_history")),
            kite_tokens_table=str(cfg.get("kite_tokens_table", "tradingbuddy_kite_tokens")),
            app_users_table=str(cfg.get("app_users_table", "tradingbuddy_app_users")),
        )

    def save_scan_run(self, summary: dict[str, Any]) -> None:
        self._upsert_scan_run(summary)

    def save_scan_result(
        self,
        summary: dict[str, Any],
        minervini_frame: pd.DataFrame,
        weekly_frame: pd.DataFrame,
        overlap_history_frame: pd.DataFrame,
    ) -> None:
        pending_summary = dict(summary)
        pending_summary["run_completed_at"] = None
        self._upsert_scan_run(pending_summary)
        self.save_minervini_shortlist(minervini_frame)
        self.save_weekly_shortlist(weekly_frame)
        self.save_overlap_history(overlap_history_frame)
        self._upsert_scan_run(summary)

    def _upsert_scan_run(self, summary: dict[str, Any]) -> None:
        self._upsert(
            self.scan_runs_table,
            [_json_clean(_keep_keys(summary, SCAN_RUN_COLUMNS))],
            conflict_column="run_id",
        )

    def save_minervini_shortlist(self, frame: pd.DataFrame) -> None:
        self._post_frame(self.minervini_table, frame, MINERVINI_COLUMNS)

    def save_scan_rows(self, frame: pd.DataFrame, batch_size: int = 100) -> None:
        self._upsert_frame(
            self.scan_rows_table,
            frame,
            SCAN_ROW_COLUMNS,
            conflict_column="run_id,exchange,symbol",
            batch_size=batch_size,
        )

    def save_weekly_shortlist(self, frame: pd.DataFrame) -> None:
        self._post_frame(self.weekly_table, frame, WEEKLY_COLUMNS)

    def save_overlap_history(self, frame: pd.DataFrame) -> None:
        self._post_frame(self.overlap_history_table, frame, OVERLAP_HISTORY_COLUMNS)

    def save_kite_token(
        self,
        access_token: str,
        profile: dict[str, Any] | None = None,
        ttl_hours: int = 24,
        token_name: str = "default",
    ) -> dict[str, Any]:
        generated_at = datetime.now(timezone.utc)
        expires_at = generated_at + timedelta(hours=ttl_hours)
        payload = {
            "token_name": token_name,
            "access_token": access_token,
            "profile": profile or {},
            "generated_at": generated_at.isoformat(timespec="seconds"),
            "expires_at": expires_at.isoformat(timespec="seconds"),
            "updated_at": generated_at.isoformat(timespec="seconds"),
        }
        self._upsert(self.kite_tokens_table, [payload], conflict_column="token_name")
        return payload

    def load_kite_token(self, token_name: str = "default") -> dict[str, Any] | None:
        response = requests.get(
            f"{self.url}/rest/v1/{self.kite_tokens_table}",
            headers={
                "apikey": self.service_role_key,
                "Authorization": f"Bearer {self.service_role_key}",
            },
            params={
                "token_name": f"eq.{token_name}",
                "select": "access_token,profile,generated_at,expires_at",
                "limit": "1",
            },
            timeout=30,
        )
        if response.status_code >= 400:
            message = response.text[:500] if response.text else response.reason
            raise RuntimeError(f"Supabase token load failed: HTTP {response.status_code} {message}")

        rows = response.json()
        if not rows:
            return None
        row = rows[0]
        if _is_expired(row.get("expires_at")):
            return None
        return {
            "access_token": row.get("access_token"),
            "profile": row.get("profile") or {},
            "generated_at": row.get("generated_at"),
            "expires_at": row.get("expires_at"),
            "source": "supabase",
        }

    def load_app_user(self, user_id: str) -> dict[str, Any] | None:
        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            return None

        response = requests.get(
            f"{self.url}/rest/v1/{self.app_users_table}",
            headers={
                "apikey": self.service_role_key,
                "Authorization": f"Bearer {self.service_role_key}",
            },
            params={
                "user_id": f"eq.{normalized_user_id}",
                "is_active": "eq.true",
                "select": "user_id,role,password_hash,display_name,is_active",
                "limit": "1",
            },
            timeout=30,
        )
        if response.status_code >= 400:
            message = response.text[:500] if response.text else response.reason
            raise RuntimeError(f"Supabase app user load failed: HTTP {response.status_code} {message}")

        rows = response.json()
        if not rows:
            return None
        return _keep_keys(rows[0], APP_USER_COLUMNS)

    def load_latest_scan_run(self) -> dict[str, Any] | None:
        rows = self._get(
            self.scan_runs_table,
            params={
                "select": "*",
                "run_completed_at": "not.is.null",
                "order": "run_started_at.desc",
                "limit": "1",
            },
            error_label="Supabase latest scan run load failed",
        )
        return rows[0] if rows else None

    def load_latest_incomplete_scan_run(self, scan_date: str, refresh_mode: str = "kite_refresh") -> dict[str, Any] | None:
        rows = self._get(
            self.scan_runs_table,
            params={
                "select": "*",
                "scan_date": f"eq.{scan_date}",
                "refresh_mode": f"eq.{refresh_mode}",
                "run_completed_at": "is.null",
                "order": "scan_rows_saved.desc,run_started_at.desc",
                "limit": "1",
            },
            error_label="Supabase incomplete scan run load failed",
        )
        return rows[0] if rows else None

    def load_scan_runs(self, limit: int = 100) -> pd.DataFrame:
        rows = self._get(
            self.scan_runs_table,
            params={
                "select": "*",
                "order": "run_started_at.desc",
                "limit": str(limit),
            },
            error_label="Supabase scan runs load failed",
        )
        return pd.DataFrame(rows)

    def load_minervini_shortlist(self, run_id: str) -> pd.DataFrame:
        rows = self._get(
            self.minervini_table,
            params={
                "run_id": f"eq.{run_id}",
                "select": "*",
                "order": "relative_strength_rank.desc,symbol.asc",
            },
            error_label="Supabase Minervini shortlist load failed",
        )
        return pd.DataFrame(rows)

    def load_scan_rows(self, run_id: str) -> pd.DataFrame:
        rows = self._get_paginated(
            self.scan_rows_table,
            params={
                "run_id": f"eq.{run_id}",
                "select": "*",
                "order": "scan_sequence.asc",
            },
            error_label="Supabase scan rows load failed",
        )
        return pd.DataFrame(rows)

    def load_weekly_shortlist(self, run_id: str) -> pd.DataFrame:
        rows = self._get(
            self.weekly_table,
            params={
                "run_id": f"eq.{run_id}",
                "select": "*",
                "order": "signal.asc,symbol.asc",
            },
            error_label="Supabase weekly shortlist load failed",
        )
        return pd.DataFrame(rows)

    def load_overlap_history(self, limit: int = 500) -> pd.DataFrame:
        rows = self._get(
            self.overlap_history_table,
            params={
                "select": "*",
                "order": "scan_date.desc,symbol.asc",
                "limit": str(limit),
            },
            error_label="Supabase overlap history load failed",
        )
        return pd.DataFrame(rows)

    def _post_frame(self, table: str, frame: pd.DataFrame, allowed_columns: set[str]) -> None:
        if frame.empty:
            return
        records = [_json_clean(_keep_keys(row, allowed_columns)) for row in frame.to_dict(orient="records")]
        for start in range(0, len(records), 500):
            self._post(table, records[start : start + 500])

    def _upsert_frame(
        self,
        table: str,
        frame: pd.DataFrame,
        allowed_columns: set[str],
        conflict_column: str,
        batch_size: int = 100,
    ) -> None:
        if frame.empty:
            return
        records = [_json_clean(_keep_keys(row, allowed_columns)) for row in frame.to_dict(orient="records")]
        chunk_size = max(int(batch_size), 1)
        for start in range(0, len(records), chunk_size):
            self._upsert(table, records[start : start + chunk_size], conflict_column=conflict_column)

    def _post(self, table: str, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        response = requests.post(
            f"{self.url}/rest/v1/{table}",
            headers={
                "apikey": self.service_role_key,
                "Authorization": f"Bearer {self.service_role_key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            json=records,
            timeout=30,
        )
        if response.status_code >= 400:
            message = response.text[:500] if response.text else response.reason
            raise RuntimeError(f"Supabase insert failed for {table}: HTTP {response.status_code} {message}")

    def _get(self, table: str, params: dict[str, str], error_label: str) -> list[dict[str, Any]]:
        response = requests.get(
            f"{self.url}/rest/v1/{table}",
            headers={
                "apikey": self.service_role_key,
                "Authorization": f"Bearer {self.service_role_key}",
            },
            params=params,
            timeout=30,
        )
        if response.status_code >= 400:
            message = response.text[:500] if response.text else response.reason
            raise RuntimeError(f"{error_label}: HTTP {response.status_code} {message}")
        return response.json()

    def _get_paginated(
        self,
        table: str,
        params: dict[str, str],
        error_label: str,
        page_size: int = 1000,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        offset = 0
        size = max(int(page_size), 1)
        while True:
            page = self._get(
                table,
                params={**params, "limit": str(size), "offset": str(offset)},
                error_label=error_label,
            )
            rows.extend(page)
            if len(page) < size:
                return rows
            offset += size

    def _upsert(self, table: str, records: list[dict[str, Any]], conflict_column: str) -> None:
        if not records:
            return
        response = requests.post(
            f"{self.url}/rest/v1/{table}",
            headers={
                "apikey": self.service_role_key,
                "Authorization": f"Bearer {self.service_role_key}",
                "Content-Type": "application/json",
                "Prefer": "resolution=merge-duplicates,return=minimal",
            },
            params={"on_conflict": conflict_column},
            json=[_json_clean(row) for row in records],
            timeout=30,
        )
        if response.status_code >= 400:
            message = response.text[:500] if response.text else response.reason
            raise RuntimeError(f"Supabase upsert failed for {table}: HTTP {response.status_code} {message}")


def _keep_keys(row: dict[str, Any], allowed_columns: set[str]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key in allowed_columns}


def _json_clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_clean(item) for item in value]
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None
        return value.isoformat()
    if pd.isna(value):
        return None
    return value


def _is_expired(expires_at: object) -> bool:
    if not expires_at:
        return True
    try:
        parsed = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed <= datetime.now(timezone.utc)
