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
    "latest_candle_date",
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
        minervini_table: str,
        weekly_table: str,
        kite_tokens_table: str,
    ) -> None:
        self.url = url.rstrip("/")
        self.service_role_key = service_role_key
        self.scan_runs_table = scan_runs_table
        self.minervini_table = minervini_table
        self.weekly_table = weekly_table
        self.kite_tokens_table = kite_tokens_table

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
            minervini_table=str(cfg.get("minervini_table", "tradingbuddy_minervini_shortlists")),
            weekly_table=str(cfg.get("weekly_table", "tradingbuddy_weekly_buy_sell_shortlists")),
            kite_tokens_table=str(cfg.get("kite_tokens_table", "tradingbuddy_kite_tokens")),
        )

    def save_scan_run(self, summary: dict[str, Any]) -> None:
        self._post(self.scan_runs_table, [_json_clean(_keep_keys(summary, SCAN_RUN_COLUMNS))])

    def save_minervini_shortlist(self, frame: pd.DataFrame) -> None:
        self._post_frame(self.minervini_table, frame, MINERVINI_COLUMNS)

    def save_weekly_shortlist(self, frame: pd.DataFrame) -> None:
        self._post_frame(self.weekly_table, frame, WEEKLY_COLUMNS)

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

    def _post_frame(self, table: str, frame: pd.DataFrame, allowed_columns: set[str]) -> None:
        if frame.empty:
            return
        records = [_json_clean(_keep_keys(row, allowed_columns)) for row in frame.to_dict(orient="records")]
        for start in range(0, len(records), 500):
            self._post(table, records[start : start + 500])

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
