from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


RULE_COLUMNS = (
    "rule_1_price_above_150_200_sma",
    "rule_2_sma150_above_sma200",
    "rule_3_sma200_trending_up",
    "rule_4_sma50_above_150_200",
    "rule_5_price_above_sma50",
    "rule_6_price_30pct_above_52w_low",
    "rule_7_price_within_25pct_of_52w_high",
    "rule_8_relative_strength_rank_70",
)

RULE_LABELS = {
    "rule_1_price_above_150_200_sma": "Close is above 150-day and 200-day SMA",
    "rule_2_sma150_above_sma200": "150-day SMA is above 200-day SMA",
    "rule_3_sma200_trending_up": "200-day SMA is trending up",
    "rule_4_sma50_above_150_200": "50-day SMA is above 150-day and 200-day SMA",
    "rule_5_price_above_sma50": "Close is above 50-day SMA",
    "rule_6_price_30pct_above_52w_low": "Close is at least 30% above 52-week low",
    "rule_7_price_within_25pct_of_52w_high": "Close is within 25% of 52-week high",
    "rule_8_relative_strength_rank_70": "Relative strength rank is at least 70",
}


def build_minervini_snapshot(daily: pd.DataFrame, config: dict[str, Any]) -> dict[str, Any]:
    cfg = config.get("minervini", {}) or {}
    minimum_history_days = int(cfg.get("minimum_history_days", 252))
    trend_lookback = int(cfg.get("sma_200_trend_lookback_days", 21))
    min_above_low_pct = float(cfg.get("minimum_above_52w_low_pct", 30.0))
    max_below_high_pct = float(cfg.get("maximum_below_52w_high_pct", 25.0))
    rs_lookback = int(cfg.get("relative_strength_lookback_days", 252))

    frame = _prepare_daily(daily)
    if len(frame) < minimum_history_days:
        row = _empty_snapshot("insufficient_history")
        row["daily_rows"] = int(len(frame))
        return row

    close = frame["close"]
    latest = frame.iloc[-1]
    latest_close = float(latest["close"])
    latest_date = pd.Timestamp(latest["date"])

    sma_50 = close.rolling(50, min_periods=50).mean()
    sma_150 = close.rolling(150, min_periods=150).mean()
    sma_200 = close.rolling(200, min_periods=200).mean()
    high_52w = frame["high"].rolling(252, min_periods=minimum_history_days).max()
    low_52w = frame["low"].rolling(252, min_periods=minimum_history_days).min()

    latest_sma_50 = _to_float(sma_50.iloc[-1])
    latest_sma_150 = _to_float(sma_150.iloc[-1])
    latest_sma_200 = _to_float(sma_200.iloc[-1])
    prior_sma_200 = _to_float(sma_200.iloc[-1 - trend_lookback]) if len(sma_200) > trend_lookback else None
    latest_high_52w = _to_float(high_52w.iloc[-1])
    latest_low_52w = _to_float(low_52w.iloc[-1])

    pct_above_low = (
        ((latest_close - latest_low_52w) / latest_low_52w) * 100.0
        if latest_low_52w and latest_low_52w > 0
        else None
    )
    pct_below_high = (
        ((latest_high_52w - latest_close) / latest_high_52w) * 100.0
        if latest_high_52w and latest_high_52w > 0
        else None
    )

    row = {
        "as_of_date": latest_date,
        "daily_rows": int(len(frame)),
        "close": latest_close,
        "sma_50": latest_sma_50,
        "sma_150": latest_sma_150,
        "sma_200": latest_sma_200,
        "sma_200_prior": prior_sma_200,
        "high_52w": latest_high_52w,
        "low_52w": latest_low_52w,
        "pct_above_52w_low": pct_above_low,
        "pct_below_52w_high": pct_below_high,
        "relative_strength_return_pct": _return_between(close, rs_lookback, 0),
        "scan_note": "",
    }

    row["rule_1_price_above_150_200_sma"] = _gt(latest_close, latest_sma_150) and _gt(latest_close, latest_sma_200)
    row["rule_2_sma150_above_sma200"] = _gt(latest_sma_150, latest_sma_200)
    row["rule_3_sma200_trending_up"] = _gt(latest_sma_200, prior_sma_200)
    row["rule_4_sma50_above_150_200"] = _gt(latest_sma_50, latest_sma_150) and _gt(latest_sma_50, latest_sma_200)
    row["rule_5_price_above_sma50"] = _gt(latest_close, latest_sma_50)
    row["rule_6_price_30pct_above_52w_low"] = pct_above_low is not None and pct_above_low >= min_above_low_pct
    row["rule_7_price_within_25pct_of_52w_high"] = pct_below_high is not None and pct_below_high <= max_below_high_pct
    row["rule_8_relative_strength_rank_70"] = False
    row["relative_strength_rank"] = np.nan
    row["minervini_pass_count"] = 0
    row["passes_minervini"] = False
    return row


def score_minervini_universe(rows: list[dict[str, Any]], config: dict[str, Any]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame

    cfg = config.get("minervini", {}) or {}
    min_rs_rank = float(cfg.get("minimum_relative_strength_rank", 70.0))

    returns = pd.to_numeric(frame.get("relative_strength_return_pct"), errors="coerce")
    frame["relative_strength_rank"] = returns.rank(pct=True, ascending=True, method="average") * 100.0
    frame["rule_8_relative_strength_rank_70"] = frame["relative_strength_rank"] >= min_rs_rank

    for column in RULE_COLUMNS:
        if column not in frame.columns:
            frame[column] = False
        frame[column] = frame[column].fillna(False).astype(bool)

    frame["minervini_pass_count"] = frame[list(RULE_COLUMNS)].sum(axis=1).astype(int)
    frame["passes_minervini"] = frame["minervini_pass_count"] == len(RULE_COLUMNS)
    return frame


def _prepare_daily(daily: pd.DataFrame) -> pd.DataFrame:
    if daily.empty:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    frame = daily.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["date", "open", "high", "low", "close", "volume"])
    return frame.sort_values("date").reset_index(drop=True)


def _empty_snapshot(note: str) -> dict[str, Any]:
    row: dict[str, Any] = {
        "as_of_date": pd.NaT,
        "daily_rows": 0,
        "close": np.nan,
        "sma_50": np.nan,
        "sma_150": np.nan,
        "sma_200": np.nan,
        "sma_200_prior": np.nan,
        "high_52w": np.nan,
        "low_52w": np.nan,
        "pct_above_52w_low": np.nan,
        "pct_below_52w_high": np.nan,
        "relative_strength_return_pct": np.nan,
        "relative_strength_rank": np.nan,
        "scan_note": note,
        "minervini_pass_count": 0,
        "passes_minervini": False,
    }
    for column in RULE_COLUMNS:
        row[column] = False
    return row


def _return_between(close: pd.Series, lookback_days: int, skip_recent_days: int) -> float | None:
    end_index = len(close) - 1 - int(skip_recent_days)
    start_index = end_index - int(lookback_days)
    if start_index < 0 or end_index < 0 or end_index >= len(close):
        return None
    start_value = float(close.iloc[start_index])
    end_value = float(close.iloc[end_index])
    if start_value <= 0:
        return None
    return ((end_value / start_value) - 1.0) * 100.0


def _to_float(value: object) -> float | None:
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _gt(left: float | None, right: float | None) -> bool:
    return left is not None and right is not None and float(left) > float(right)
