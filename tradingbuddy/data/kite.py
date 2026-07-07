from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
from kiteconnect import KiteConnect

from tradingbuddy.config import require_env


class KiteDataProvider:
    """Thin wrapper around Zerodha Kite Connect for EOD screening."""

    def __init__(self, access_token: str | None = None) -> None:
        api_key = require_env("KITE_API_KEY")
        access_token = access_token or require_env("KITE_ACCESS_TOKEN")
        self.kite = KiteConnect(api_key=api_key)
        self.kite.set_access_token(access_token)

    def validate_session(self) -> dict[str, Any]:
        return self.kite.profile()

    def instruments(self, exchange: str = "NSE") -> pd.DataFrame:
        return pd.DataFrame(self.kite.instruments(exchange))

    def daily_candles(
        self,
        instrument_token: int,
        from_date: date,
        to_date: date,
    ) -> pd.DataFrame:
        candles = self.kite.historical_data(
            instrument_token=instrument_token,
            from_date=from_date,
            to_date=to_date,
            interval="day",
            continuous=False,
            oi=False,
        )
        frame = pd.DataFrame(candles)
        if frame.empty:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

        frame["date"] = pd.to_datetime(frame["date"]).dt.tz_localize(None)
        return frame[["date", "open", "high", "low", "close", "volume"]]

    def ltp(self, instruments: list[str]) -> dict[str, float]:
        if not instruments:
            return {}
        prices: dict[str, float] = {}
        for start in range(0, len(instruments), 100):
            payload = self.kite.ltp(instruments[start : start + 100])
            for key, value in payload.items():
                try:
                    prices[str(key)] = float(value.get("last_price"))
                except (TypeError, ValueError, AttributeError):
                    continue
        return prices
