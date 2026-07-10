from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import pandas as pd

from tradingbuddy.auth.kite_token import load_access_token
from tradingbuddy.data.kite import KiteDataProvider
from tradingbuddy.data.storage import Storage
from tradingbuddy.data.supabase_store import SupabaseStore
from tradingbuddy.minervini import build_minervini_snapshot, score_minervini_universe
from tradingbuddy.resample import resample_daily_to_weekly
from tradingbuddy.strategy.weekly_buy_sell import run_weekly_buy_sell
from tradingbuddy.universe import build_universe


ProgressCallback = Callable[[dict[str, Any]], None]

OVERLAP_HISTORY_COLUMNS = [
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
]


@dataclass(frozen=True)
class ScanResult:
    summary: dict[str, Any]
    all_results: pd.DataFrame
    passed_results: pd.DataFrame
    weekly_results: pd.DataFrame
    overlap_history: pd.DataFrame


def run_scan(
    config: dict[str, Any],
    storage: Storage,
    refresh_data: bool = True,
    max_symbols: int | None = None,
    progress_callback: ProgressCallback | None = None,
) -> ScanResult:
    run_started = _now(config)
    run_id = f"{run_started.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    data_root = storage.data_root
    history_years = int(config.get("data", {}).get("history_years", 2))
    today = run_started.date()
    start_date = today - timedelta(days=365 * history_years)

    provider: KiteDataProvider | None = None
    if refresh_data:
        _emit(progress_callback, phase="Validating Kite session", completed=0, total=0)
        access_token = _load_kite_access_token(data_root, config)
        if not access_token:
            raise RuntimeError("Kite access token not found. Use the Kite Login panel first.")
        provider = KiteDataProvider(access_token=access_token)
        provider.validate_session()

        _emit(progress_callback, phase="Loading Kite NSE instruments", completed=0, total=0)
        instruments = provider.instruments("NSE")
        storage.save_instruments(instruments)
    else:
        _emit(progress_callback, phase="Loading cached instruments", completed=0, total=0)
        instruments = storage.load_instruments()
        if instruments.empty:
            raise RuntimeError("No cached instruments found. Run once with Kite data refresh enabled.")

    universe = build_universe(instruments, config)
    if max_symbols is not None and max_symbols > 0:
        universe = universe.head(int(max_symbols)).copy()

    request_sleep = float(config.get("data", {}).get("request_sleep_seconds", 0.35))
    rows: list[dict[str, Any]] = []
    updated_symbols = 0
    failed_symbols = 0
    failure_examples: list[str] = []

    _emit(progress_callback, phase="Universe ready", completed=0, total=len(universe))
    for completed, (_, instrument) in enumerate(universe.iterrows(), start=1):
        exchange = str(instrument.get("exchange", "NSE")).upper()
        symbol = str(instrument.get("tradingsymbol", "")).upper().strip()
        name = str(instrument.get("name", symbol) or symbol).strip() or symbol
        token = instrument.get("instrument_token")

        _emit(
            progress_callback,
            phase="Fetching candles" if refresh_data else "Using cached candles",
            completed=completed - 1,
            total=len(universe),
            current_symbol=symbol,
        )

        existing = storage.load_candles(exchange, symbol, "1D")
        fetch_status = "cached"
        fetch_error = ""
        new_rows = 0

        if refresh_data:
            try:
                if pd.isna(token):
                    raise RuntimeError("Missing instrument_token")
                from_date = _fetch_start_date(existing, start_date)
                if from_date <= today:
                    assert provider is not None
                    new_daily = provider.daily_candles(int(token), from_date, today)
                    new_rows = len(new_daily)
                    daily = storage.merge_and_save_candles(exchange, symbol, new_daily, "1D")
                    fetch_status = "updated" if new_rows else "already_current"
                    if new_rows:
                        updated_symbols += 1
                    if request_sleep > 0:
                        time.sleep(request_sleep)
                else:
                    daily = existing
                    fetch_status = "already_current"
            except Exception as exc:
                failed_symbols += 1
                fetch_status = "failed"
                fetch_error = str(exc)
                if len(failure_examples) < 5:
                    failure_examples.append(f"{symbol}: {fetch_error[:180]}")
                daily = existing
        else:
            daily = existing

        history = _trim_history(daily, start_date)
        minervini_row = build_minervini_snapshot(history, config)
        weekly_row = latest_weekly_signal(history, config)

        rows.append(
            {
                "exchange": exchange,
                "symbol": symbol,
                "tradingview_symbol": f"{exchange}:{symbol}",
                "name": name,
                "instrument_token": token,
                "fetch_status": fetch_status,
                "fetch_error": fetch_error,
                "new_rows": int(new_rows),
                **minervini_row,
                **weekly_row,
            }
        )

        _emit(
            progress_callback,
            phase="Scanned",
            completed=completed,
            total=len(universe),
            current_symbol=symbol,
        )

    if refresh_data:
        _validate_refresh_quality(
            universe_size=len(universe),
            updated_symbols=updated_symbols,
            failed_symbols=failed_symbols,
            failure_examples=failure_examples,
        )

    all_results = score_minervini_universe(rows, config)
    all_results = _attach_run_columns(all_results, run_id, run_started)
    if not all_results.empty:
        all_results = all_results.sort_values(
            ["passes_minervini", "minervini_pass_count", "relative_strength_rank", "symbol"],
            ascending=[False, False, False, True],
            na_position="last",
        ).reset_index(drop=True)
    passed_results = _build_minervini_shortlist(all_results)
    weekly_results = _build_weekly_shortlist(all_results)
    overlap_history = _build_overlap_history(all_results)

    ltp_status = "not_requested"
    if provider is not None:
        ltp_status = _apply_kite_ltp(provider, passed_results, weekly_results)

    all_path = storage.save_signals("latest_scan.csv", all_results)
    pass_path = storage.save_signals("latest_minervini_pass.csv", passed_results)
    weekly_path = storage.save_signals("latest_weekly_buy_sell.csv", weekly_results)
    overlap_path = storage.save_signals("latest_overlap_history.csv", overlap_history)
    storage.append_signals("overlap_history.csv", overlap_history)
    latest_date = (
        str(pd.to_datetime(all_results["as_of_date"], errors="coerce").max().date())
        if not all_results.empty and pd.to_datetime(all_results["as_of_date"], errors="coerce").notna().any()
        else ""
    )
    run_completed = _now(config)
    summary = {
        "run_id": run_id,
        "run_started_at": run_started.isoformat(),
        "run_completed_at": run_completed.isoformat(),
        "scan_date": str(today),
        "history_start_date": str(start_date),
        "symbols_scanned": int(len(universe)),
        "symbols_updated": int(updated_symbols),
        "symbols_failed": int(failed_symbols),
        "minervini_pass_count": int(len(passed_results)),
        "weekly_buy_sell_count": int(len(weekly_results)),
        "overlap_count": int(len(overlap_history)),
        "latest_candle_date": latest_date,
        "refresh_mode": "kite_refresh" if refresh_data else "cached_only",
        "ltp_status": ltp_status,
        "all_results_path": str(all_path),
        "passed_results_path": str(pass_path),
        "weekly_results_path": str(weekly_path),
        "overlap_history_path": str(overlap_path),
        "supabase_status": "not_configured",
    }
    supabase = SupabaseStore.from_config(config)
    if supabase is not None:
        try:
            supabase.save_scan_result(summary, passed_results, weekly_results, overlap_history)
            summary["supabase_status"] = "saved"
        except Exception as exc:
            summary["supabase_status"] = f"failed: {exc}"

    storage.save_signals("latest_scan_summary.csv", pd.DataFrame([summary]))
    storage.append_scan_run(summary)

    _emit(progress_callback, phase="Complete", completed=len(universe), total=len(universe), summary=summary)
    return ScanResult(
        summary=summary,
        all_results=all_results,
        passed_results=passed_results,
        weekly_results=weekly_results,
        overlap_history=overlap_history,
    )


def latest_weekly_signal(daily: pd.DataFrame, config: dict[str, Any]) -> dict[str, Any]:
    defaults = {
        "latest_weekly_signal": "NONE",
        "latest_weekly_signal_date": pd.NaT,
        "latest_weekly_signal_close": pd.NA,
        "bars_since_weekly_signal": pd.NA,
        "fresh_weekly_signal": False,
        "fresh_weekly_buy": False,
        "weekly_volume_confirmation": False,
        "weekly_volume_confirmation_ratio": pd.NA,
        "weekly_trend_confirmation": False,
        "weekly_demand_zone": pd.NA,
        "weekly_supply_zone": pd.NA,
    }
    if daily.empty:
        return defaults

    strategy_cfg = config.get("strategy", {}) or {}
    weekly = resample_daily_to_weekly(
        daily,
        weekly_anchor=strategy_cfg.get("weekly_anchor", "W-MON"),
        use_completed_weeks_only=bool(strategy_cfg.get("use_completed_weeks_only", False)),
    )
    if weekly.empty:
        return defaults

    output = run_weekly_buy_sell(weekly, config)
    signals = output[output["signal"].astype(str).str.upper().isin(["BUY", "SELL"])].copy()
    if signals.empty:
        return defaults

    latest = signals.sort_values("date").iloc[-1]
    latest_index = int(latest.name)
    bars_since = int((len(output) - 1) - latest_index)
    max_age = max(int(config.get("signals", {}).get("fresh_weekly_signal_age_bars", 1)), 1)
    latest_signal = str(latest.get("signal", "NONE")).upper()
    signal_date = latest.get("date", pd.NaT)
    signal_close = _daily_close_on_date(daily, signal_date)

    return {
        "latest_weekly_signal": latest_signal,
        "latest_weekly_signal_date": signal_date,
        "latest_weekly_signal_close": signal_close,
        "bars_since_weekly_signal": bars_since,
        "fresh_weekly_signal": bool(latest_signal in {"BUY", "SELL"} and bars_since <= max_age - 1),
        "fresh_weekly_buy": bool(latest_signal == "BUY" and bars_since <= max_age - 1),
        "weekly_volume_confirmation": bool(latest.get("volume_confirmation", False)),
        "weekly_volume_confirmation_ratio": _to_float(latest.get("volume_confirmation_ratio")),
        "weekly_trend_confirmation": bool(latest.get("trend_confirmation", False)),
        "weekly_demand_zone": _to_float(latest.get("demand_zone")),
        "weekly_supply_zone": _to_float(latest.get("supply_zone")),
    }


def _daily_close_on_date(daily: pd.DataFrame, target_date: object) -> Any:
    if daily.empty or "date" not in daily.columns or "close" not in daily.columns:
        return pd.NA
    parsed_target = pd.to_datetime(target_date, errors="coerce")
    if pd.isna(parsed_target):
        return pd.NA

    frame = daily[["date", "close"]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame[frame["date"].notna()].sort_values("date")
    if frame.empty:
        return pd.NA

    exact = frame[frame["date"].dt.normalize() == pd.Timestamp(parsed_target).normalize()]
    if exact.empty:
        return pd.NA
    return _to_float(exact.iloc[-1]["close"])


def _fetch_start_date(existing: pd.DataFrame, start_date: date) -> date:
    if existing.empty:
        return start_date
    last_date = pd.to_datetime(existing["date"], errors="coerce").max()
    if pd.isna(last_date):
        return start_date
    return max(start_date, pd.Timestamp(last_date).date())


def _trim_history(daily: pd.DataFrame, start_date: date) -> pd.DataFrame:
    if daily.empty:
        return daily
    frame = daily.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame[frame["date"].notna()]
    frame = frame[frame["date"].dt.date >= start_date]
    return frame.sort_values("date").reset_index(drop=True)


def _emit(callback: ProgressCallback | None, **payload: Any) -> None:
    if callback:
        callback(payload)


def _load_kite_access_token(data_root: Path, config: dict[str, Any]) -> str | None:
    token = load_access_token(data_root)
    if token:
        return token

    supabase = SupabaseStore.from_config(config)
    if supabase is None:
        return None
    token_row = supabase.load_kite_token()
    if not token_row:
        return None
    token = token_row.get("access_token")
    return str(token) if token else None


def _now(config: dict[str, Any]) -> datetime:
    timezone_name = str(config.get("app", {}).get("timezone", "Asia/Kolkata"))
    return datetime.now(ZoneInfo(timezone_name))


def _attach_run_columns(frame: pd.DataFrame, run_id: str, run_started: datetime) -> pd.DataFrame:
    if frame.empty:
        return frame
    enriched = frame.copy()
    enriched["run_id"] = run_id
    enriched["run_started_at"] = run_started.isoformat()
    enriched["current_price"] = pd.to_numeric(enriched.get("close"), errors="coerce")
    enriched["price_source"] = "latest_close"
    return enriched


def _build_minervini_shortlist(all_results: pd.DataFrame) -> pd.DataFrame:
    if all_results.empty:
        return pd.DataFrame()
    frame = all_results[all_results["passes_minervini"].fillna(False).astype(bool)].copy()
    if frame.empty:
        return frame
    frame["shortlist_date"] = pd.to_datetime(frame["as_of_date"], errors="coerce").dt.date.astype("string")
    frame["shortlisted_price"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = _add_gain_loss(frame, "shortlisted_price")
    return frame.reset_index(drop=True)


def _build_weekly_shortlist(all_results: pd.DataFrame) -> pd.DataFrame:
    if all_results.empty:
        return pd.DataFrame()
    signal = all_results["latest_weekly_signal"].astype(str).str.upper()
    fresh = all_results["fresh_weekly_signal"].fillna(False).astype(bool)
    frame = all_results[signal.isin(["BUY", "SELL"]) & fresh].copy()
    if frame.empty:
        return frame
    frame["signal"] = frame["latest_weekly_signal"].astype(str).str.upper()
    frame["signal_date"] = pd.to_datetime(frame["latest_weekly_signal_date"], errors="coerce").dt.date.astype("string")
    frame["signal_price"] = pd.to_numeric(frame["latest_weekly_signal_close"], errors="coerce")
    frame["shortlist_date"] = frame["signal_date"]
    frame["shortlisted_price"] = frame["signal_price"]
    frame = _add_gain_loss(frame, "signal_price")
    return frame.reset_index(drop=True)


def _build_overlap_history(all_results: pd.DataFrame) -> pd.DataFrame:
    if all_results.empty:
        return pd.DataFrame(columns=OVERLAP_HISTORY_COLUMNS)
    required_columns = {"passes_minervini", "fresh_weekly_buy", "latest_weekly_signal"}
    if not required_columns.issubset(set(all_results.columns)):
        return pd.DataFrame(columns=OVERLAP_HISTORY_COLUMNS)

    frame = all_results[
        all_results["passes_minervini"].fillna(False).astype(bool)
        & all_results["fresh_weekly_buy"].fillna(False).astype(bool)
        & (all_results["latest_weekly_signal"].astype(str).str.upper() == "BUY")
    ].copy()
    if frame.empty:
        return pd.DataFrame(columns=OVERLAP_HISTORY_COLUMNS)

    frame["scan_date"] = pd.to_datetime(frame["as_of_date"], errors="coerce").dt.date.astype("string")
    frame["scan_close_date"] = frame["scan_date"]
    frame["signal_date"] = pd.to_datetime(frame["latest_weekly_signal_date"], errors="coerce").dt.date.astype("string")
    frame["signal_price"] = pd.to_numeric(frame["latest_weekly_signal_close"], errors="coerce")
    frame["scan_close_price"] = pd.to_numeric(frame["close"], errors="coerce")
    frame["current_price"] = frame["scan_close_price"]
    frame["price_source"] = "daily_close"
    frame = _add_gain_loss(frame, "signal_price")

    available = [column for column in OVERLAP_HISTORY_COLUMNS if column in frame.columns]
    return frame[available].reset_index(drop=True)


def _validate_refresh_quality(
    universe_size: int,
    updated_symbols: int,
    failed_symbols: int,
    failure_examples: list[str] | None = None,
) -> None:
    if universe_size <= 0:
        return

    examples = "; ".join(failure_examples or [])
    suffix = f" Sample errors: {examples}" if examples else ""
    if updated_symbols == 0:
        raise RuntimeError(
            "Kite refresh did not return candle rows for any symbol, so cached results were not saved as a fresh scan."
            + suffix
        )

    failure_rate = failed_symbols / universe_size
    if failure_rate >= 0.25:
        raise RuntimeError(
            f"Kite refresh failed for {failed_symbols}/{universe_size} symbols ({failure_rate:.0%}), "
            "so cached results were not saved as a fresh scan."
            + suffix
        )


def _apply_kite_ltp(provider: KiteDataProvider, *frames: pd.DataFrame) -> str:
    instruments: set[str] = set()
    for frame in frames:
        if frame.empty:
            continue
        for _, row in frame.iterrows():
            exchange = str(row.get("exchange", "")).strip().upper()
            symbol = str(row.get("symbol", "")).strip().upper()
            if exchange and symbol:
                instruments.add(f"{exchange}:{symbol}")

    if not instruments:
        return "no_shortlist_symbols"

    try:
        prices = provider.ltp(sorted(instruments))
    except Exception as exc:
        return f"failed: {exc}"

    for frame in frames:
        if frame.empty:
            continue
        for index, row in frame.iterrows():
            key = f"{str(row.get('exchange', '')).strip().upper()}:{str(row.get('symbol', '')).strip().upper()}"
            if key in prices:
                frame.at[index, "current_price"] = prices[key]
                frame.at[index, "price_source"] = "kite_ltp"
        base_column = "signal_price" if "signal_price" in frame.columns else "shortlisted_price"
        updated = _add_gain_loss(frame, base_column)
        for column in ("current_price", "price_source", "gain_loss_pct"):
            frame[column] = updated[column]

    return f"saved_{len(prices)}_prices"


def _add_gain_loss(frame: pd.DataFrame, base_column: str) -> pd.DataFrame:
    enriched = frame.copy()
    base = pd.to_numeric(enriched.get(base_column), errors="coerce")
    current = pd.to_numeric(enriched.get("current_price"), errors="coerce")
    enriched["gain_loss_pct"] = ((current - base) / base) * 100.0
    enriched.loc[base.isna() | (base == 0) | current.isna(), "gain_loss_pct"] = pd.NA
    return enriched


def _to_float(value: object) -> float | pd.NA:
    try:
        if pd.isna(value):
            return pd.NA
        return float(value)
    except (TypeError, ValueError):
        return pd.NA
