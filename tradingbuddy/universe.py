from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbuddy.symbols import (
    NSE_TRADED_ALLOWED_SUFFIXES,
    has_nse_series_suffix,
    is_nse_traded_equity_style_series,
)


def _apply_traded_universe_filters(frame: pd.DataFrame, universe_cfg: dict[str, Any]) -> pd.DataFrame:
    traded_cfg = universe_cfg.get("approximate_nse_traded_universe", {}) or {}
    if not bool(traded_cfg.get("enabled", False)):
        return frame

    working = frame.copy()
    if bool(traded_cfg.get("require_nonblank_name", True)) and "name" in working.columns:
        working["name"] = working["name"].fillna("").astype(str).str.strip()
        working = working[working["name"] != ""]

    allowed_suffixes = tuple(traded_cfg.get("allowed_series_suffixes", NSE_TRADED_ALLOWED_SUFFIXES) or NSE_TRADED_ALLOWED_SUFFIXES)
    if "tradingsymbol" in working.columns:
        working = working[
            is_nse_traded_equity_style_series(
                working["tradingsymbol"],
                working["name"] if "name" in working.columns else pd.Series("", index=working.index),
                allowed_suffixes=allowed_suffixes,
            )
        ]

    return working


def build_universe(instruments: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    universe_cfg = config.get("universe", {})
    exchanges = set(universe_cfg.get("exchanges", ["NSE"]))
    instrument_types = set(universe_cfg.get("instrument_types", ["EQ"]))
    exclude_series_suffixes = tuple(universe_cfg.get("exclude_series_suffixes", []) or [])
    allow_symbols = {str(symbol).upper() for symbol in (universe_cfg.get("allow_symbols", []) or [])}
    block_symbols = {str(symbol).upper() for symbol in (universe_cfg.get("block_symbols", []) or [])}
    max_symbols = universe_cfg.get("max_symbols")

    if instruments.empty:
        return instruments

    frame = instruments.copy()
    frame = frame[frame["exchange"].astype(str).str.upper().isin(exchanges)]

    if "instrument_type" in frame.columns:
        frame = frame[frame["instrument_type"].astype(str).str.upper().isin(instrument_types)]

    if "segment" in frame.columns:
        frame = frame[frame["segment"].astype(str).str.upper() != "INDICES"]

    if "tradingsymbol" in frame.columns:
        frame["tradingsymbol"] = frame["tradingsymbol"].fillna("").astype(str).str.upper().str.strip()
        frame = frame[frame["tradingsymbol"] != ""]
        if exclude_series_suffixes:
            frame = frame[~frame["tradingsymbol"].apply(lambda symbol: has_nse_series_suffix(symbol, exclude_series_suffixes))]
        frame = frame[~frame["tradingsymbol"].isin(block_symbols)]
        if allow_symbols:
            frame = frame[frame["tradingsymbol"].isin(allow_symbols)]

    if "name" in frame.columns:
        frame["name"] = frame["name"].fillna("").astype(str).str.strip()
    else:
        frame["name"] = ""

    frame = _apply_traded_universe_filters(frame, universe_cfg)
    frame = frame.sort_values(["exchange", "tradingsymbol"])

    if max_symbols:
        frame = frame.head(int(max_symbols))

    return frame.reset_index(drop=True)

