from __future__ import annotations

import unittest

import pandas as pd

from tradingbuddy.scan import (
    _build_minervini_shortlist,
    _build_overlap_history,
    _build_weekly_shortlist,
    _daily_close_on_date,
    _fetch_start_date,
)


class ScanShortlistTests(unittest.TestCase):
    def test_minervini_and_weekly_shortlists_are_separate_with_gain_loss(self) -> None:
        rows = pd.DataFrame(
            [
                {
                    "run_id": "run-1",
                    "run_started_at": "2026-07-07T20:00:00+05:30",
                    "exchange": "NSE",
                    "symbol": "ABC",
                    "tradingview_symbol": "NSE:ABC",
                    "name": "ABC Ltd",
                    "passes_minervini": True,
                    "minervini_pass_count": 8,
                    "as_of_date": pd.Timestamp("2026-07-07"),
                    "close": 100.0,
                    "current_price": 110.0,
                    "price_source": "kite_ltp",
                    "latest_weekly_signal": "BUY",
                    "latest_weekly_signal_date": pd.Timestamp("2026-07-06"),
                    "latest_weekly_signal_close": 95.0,
                    "fresh_weekly_signal": True,
                    "fresh_weekly_buy": True,
                    "bars_since_weekly_signal": 0,
                },
                {
                    "run_id": "run-1",
                    "run_started_at": "2026-07-07T20:00:00+05:30",
                    "exchange": "NSE",
                    "symbol": "XYZ",
                    "tradingview_symbol": "NSE:XYZ",
                    "name": "XYZ Ltd",
                    "passes_minervini": False,
                    "minervini_pass_count": 5,
                    "as_of_date": pd.Timestamp("2026-07-07"),
                    "close": 50.0,
                    "current_price": 55.0,
                    "price_source": "kite_ltp",
                    "latest_weekly_signal": "NONE",
                    "latest_weekly_signal_date": pd.NaT,
                    "latest_weekly_signal_close": pd.NA,
                    "fresh_weekly_signal": False,
                    "fresh_weekly_buy": False,
                    "bars_since_weekly_signal": pd.NA,
                },
            ]
        )

        minervini = _build_minervini_shortlist(rows)
        weekly = _build_weekly_shortlist(rows)

        self.assertEqual(minervini["symbol"].tolist(), ["ABC"])
        self.assertAlmostEqual(float(minervini.iloc[0]["gain_loss_pct"]), 10.0)
        self.assertEqual(weekly["symbol"].tolist(), ["ABC"])
        self.assertEqual(weekly.iloc[0]["signal"], "BUY")
        self.assertAlmostEqual(float(weekly.iloc[0]["gain_loss_pct"]), 15.7894736842)

        overlap = _build_overlap_history(rows)
        self.assertEqual(overlap["symbol"].tolist(), ["ABC"])
        self.assertEqual(float(overlap.iloc[0]["signal_price"]), 95.0)
        self.assertEqual(float(overlap.iloc[0]["scan_close_price"]), 100.0)
        self.assertAlmostEqual(float(overlap.iloc[0]["gain_loss_pct"]), 5.2631578947)

    def test_fetch_start_date_refetches_latest_cached_date_for_overwrite(self) -> None:
        existing = pd.DataFrame({"date": [pd.Timestamp("2026-07-06"), pd.Timestamp("2026-07-07")]})

        from_date = _fetch_start_date(existing, pd.Timestamp("2024-07-07").date())

        self.assertEqual(from_date, pd.Timestamp("2026-07-07").date())

    def test_signal_price_uses_daily_close_for_signal_date(self) -> None:
        daily = pd.DataFrame(
            [
                {"date": pd.Timestamp("2026-07-06"), "close": 624.55},
                {"date": pd.Timestamp("2026-07-07"), "close": 649.85},
            ]
        )

        signal_close = _daily_close_on_date(daily, pd.Timestamp("2026-07-06"))

        self.assertEqual(signal_close, 624.55)


if __name__ == "__main__":
    unittest.main()
