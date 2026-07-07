from __future__ import annotations

import unittest

import pandas as pd

from tradingbuddy.minervini import RULE_COLUMNS, build_minervini_snapshot, score_minervini_universe


def _config() -> dict:
    return {
        "minervini": {
            "minimum_history_days": 252,
            "sma_200_trend_lookback_days": 21,
            "minimum_above_52w_low_pct": 30.0,
            "maximum_below_52w_high_pct": 25.0,
            "minimum_relative_strength_rank": 70.0,
            "relative_strength_lookback_days": 252,
        }
    }


def _trend_frame(start_price: float, end_price: float, rows: int = 320) -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-01", periods=rows)
    close = pd.Series(
        [start_price + ((end_price - start_price) * index / (rows - 1)) for index in range(rows)],
        dtype="float64",
    )
    return pd.DataFrame(
        {
            "date": dates,
            "open": close * 0.995,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 100000,
        }
    )


class MinerviniTests(unittest.TestCase):
    def test_strong_trend_passes_all_rules_after_rs_rank(self) -> None:
        strong = build_minervini_snapshot(_trend_frame(50, 160), _config())
        weak = build_minervini_snapshot(_trend_frame(80, 120), _config())
        strong["symbol"] = "STRONG"
        weak["symbol"] = "WEAK"

        scored = score_minervini_universe([strong, weak], _config())
        row = scored[scored["symbol"] == "STRONG"].iloc[0]

        self.assertTrue(bool(row["passes_minervini"]))
        self.assertEqual(int(row["minervini_pass_count"]), len(RULE_COLUMNS))
        self.assertGreaterEqual(float(row["relative_strength_rank"]), 70.0)

    def test_price_below_50_day_average_fails_rule_5(self) -> None:
        frame = _trend_frame(50, 160)
        frame.loc[frame.index[-1], ["open", "high", "low", "close"]] = [80, 82, 78, 80]

        snapshot = build_minervini_snapshot(frame, _config())

        self.assertFalse(bool(snapshot["rule_5_price_above_sma50"]))
        self.assertFalse(bool(snapshot["passes_minervini"]))


if __name__ == "__main__":
    unittest.main()

