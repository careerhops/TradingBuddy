from __future__ import annotations

import unittest

import pandas as pd

from streamlit_app import _tradingview_overlap_symbols


class TradingViewOverlapTests(unittest.TestCase):
    def test_overlap_symbols_include_only_minervini_and_weekly_buy(self) -> None:
        minervini = pd.DataFrame(
            [
                {"exchange": "NSE", "symbol": "ABC"},
                {"exchange": "NSE", "symbol": "DEF"},
            ]
        )
        weekly = pd.DataFrame(
            [
                {"exchange": "NSE", "symbol": "ABC", "signal": "BUY"},
                {"exchange": "NSE", "symbol": "DEF", "signal": "SELL"},
                {"exchange": "NSE", "symbol": "XYZ", "signal": "BUY"},
            ]
        )

        self.assertEqual(_tradingview_overlap_symbols(minervini, weekly), ["NSE:ABC"])


if __name__ == "__main__":
    unittest.main()

