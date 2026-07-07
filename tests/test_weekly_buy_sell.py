from __future__ import annotations

import unittest

import pandas as pd

from tradingbuddy.strategy.weekly_buy_sell import run_weekly_buy_sell


def _config() -> dict:
    return {
        "strategy": {
            "sensitivity": 3,
            "fvg_lookback": 5,
            "prevent_repeated_direction": True,
        }
    }


def _weekly_candles(rows: list[tuple[str, float, float, float, float, int]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])


class WeeklyBuySellTests(unittest.TestCase):
    def test_buy_and_sell_match_stock_signals_parity_case(self) -> None:
        candles = _weekly_candles(
            [
                ("2024-01-05", 9, 10, 8, 9, 1000),
                ("2024-01-12", 10, 11, 9, 10, 1100),
                ("2024-01-19", 11, 12, 10, 11, 1200),
                ("2024-01-26", 11.5, 12.5, 10.5, 11.5, 1300),
                ("2024-02-02", 13, 14, 13, 14, 1400),
                ("2024-02-09", 8.2, 9, 7, 8, 1500),
            ]
        )

        result = run_weekly_buy_sell(candles, _config())
        signals = result[result["signal"].isin(["BUY", "SELL"])][["date", "signal"]].copy()
        signals["date"] = signals["date"].dt.strftime("%Y-%m-%d")

        self.assertEqual(
            signals.to_dict(orient="records"),
            [
                {"date": "2024-02-02", "signal": "BUY"},
                {"date": "2024-02-09", "signal": "SELL"},
            ],
        )


if __name__ == "__main__":
    unittest.main()

