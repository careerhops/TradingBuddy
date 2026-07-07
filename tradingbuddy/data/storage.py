from __future__ import annotations

from pathlib import Path

import pandas as pd


def _normalize_candle_dates(series: pd.Series) -> pd.Series:
    raw = series.astype(str).str.strip()
    raw = raw.replace({"": pd.NA, "nan": pd.NA, "NaT": pd.NA, "None": pd.NA})
    raw = raw.str.replace(
        r"^(?P<year>\d{3})-(?P<month>\d{2})-(?P<day>\d{2})$",
        r"2\g<year>-\g<month>-\g<day>",
        regex=True,
    )
    return pd.to_datetime(raw, errors="coerce")


def _clean_candles_frame(candles: pd.DataFrame) -> pd.DataFrame:
    if candles.empty:
        return candles.copy()
    cleaned = candles.copy()
    cleaned["date"] = _normalize_candle_dates(cleaned["date"])
    cleaned = cleaned[cleaned["date"].notna()].copy()
    if cleaned.empty:
        return cleaned
    return cleaned.sort_values("date").drop_duplicates(subset=["date"], keep="last")


class Storage:
    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root
        self.instruments_dir = data_root / "instruments"
        self.candles_dir = data_root / "candles"
        self.signals_dir = data_root / "signals"
        self.logs_dir = data_root / "logs"
        for path in (self.instruments_dir, self.candles_dir, self.signals_dir, self.logs_dir):
            path.mkdir(parents=True, exist_ok=True)

    def instruments_path(self) -> Path:
        return self.instruments_dir / "instruments.csv"

    def save_instruments(self, instruments: pd.DataFrame) -> Path:
        path = self.instruments_path()
        instruments.to_csv(path, index=False)
        return path

    def load_instruments(self) -> pd.DataFrame:
        path = self.instruments_path()
        if not path.exists():
            return pd.DataFrame()
        try:
            return pd.read_csv(path)
        except pd.errors.EmptyDataError:
            return pd.DataFrame()

    def candle_path(self, exchange: str, symbol: str, timeframe: str = "1D") -> Path:
        safe_symbol = str(symbol).replace("/", "_")
        directory = self.candles_dir / exchange / timeframe
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{safe_symbol}.csv"

    def save_candles(self, exchange: str, symbol: str, candles: pd.DataFrame, timeframe: str = "1D") -> None:
        if candles.empty:
            return
        path = self.candle_path(exchange, symbol, timeframe)
        cleaned = _clean_candles_frame(candles)
        if cleaned.empty:
            return
        cleaned.to_csv(path, index=False)

    def load_candles(self, exchange: str, symbol: str, timeframe: str = "1D") -> pd.DataFrame:
        path = self.candle_path(exchange, symbol, timeframe)
        if not path.exists():
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
        try:
            candles = pd.read_csv(path)
        except pd.errors.EmptyDataError:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
        cleaned = _clean_candles_frame(candles)
        if cleaned.empty:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
        return cleaned.reset_index(drop=True)

    def merge_and_save_candles(
        self,
        exchange: str,
        symbol: str,
        new_candles: pd.DataFrame,
        timeframe: str = "1D",
    ) -> pd.DataFrame:
        existing = self.load_candles(exchange, symbol, timeframe)
        if existing.empty and new_candles.empty:
            return existing
        if existing.empty:
            merged = new_candles.copy()
        elif new_candles.empty:
            merged = existing.copy()
        else:
            merged = pd.concat([existing, new_candles], ignore_index=True)
        merged = _clean_candles_frame(merged)
        self.save_candles(exchange, symbol, merged, timeframe)
        return merged.reset_index(drop=True)

    def save_signals(self, name: str, signals: pd.DataFrame) -> Path:
        path = self.signals_dir / name
        signals.to_csv(path, index=False)
        return path

    def load_signals(self, name: str) -> pd.DataFrame:
        path = self.signals_dir / name
        if not path.exists():
            return pd.DataFrame()
        try:
            return pd.read_csv(path)
        except pd.errors.EmptyDataError:
            return pd.DataFrame()

    def append_scan_run(self, summary: dict[str, object]) -> Path:
        path = self.signals_dir / "scan_runs.csv"
        row = pd.DataFrame([summary])
        if path.exists():
            try:
                existing = pd.read_csv(path)
            except pd.errors.EmptyDataError:
                existing = pd.DataFrame()
            frame = pd.concat([existing, row], ignore_index=True)
        else:
            frame = row
        frame.to_csv(path, index=False)
        return path
