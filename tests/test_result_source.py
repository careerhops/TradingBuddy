from __future__ import annotations

import unittest

import pandas as pd

from streamlit_app import _choose_result_bundle, _freshness_messages


def _bundle(source: str, started_at: str) -> dict[str, object]:
    return {
        "source": source,
        "all_results": pd.DataFrame(),
        "minervini_results": pd.DataFrame(),
        "weekly_results": pd.DataFrame(),
        "overlap_history": pd.DataFrame(),
        "summary": pd.DataFrame([{"run_started_at": started_at, "run_id": source}]),
        "runs": pd.DataFrame(),
        "error": "",
    }


class ResultSourceTests(unittest.TestCase):
    def test_newer_supabase_results_win_over_stale_local_results(self) -> None:
        local = _bundle("local csv", "2026-07-07T09:00:00+05:30")
        supabase = _bundle("supabase", "2026-07-07T17:00:00+00:00")

        chosen = _choose_result_bundle(local, supabase)

        self.assertEqual(chosen["source"], "supabase")

    def test_freshness_warns_when_latest_completed_scan_is_previous_day(self) -> None:
        summary = pd.DataFrame(
            [
                {
                    "scan_date": "2026-07-09",
                    "latest_candle_date": "2026-07-09",
                }
            ]
        )

        messages = _freshness_messages({}, summary, today=pd.Timestamp("2026-07-10"))

        self.assertEqual(messages[0][0], "warning")
        self.assertIn("No completed scan has been saved for 2026-07-10", messages[0][1])

    def test_freshness_notes_when_daily_candle_lags_scan_day(self) -> None:
        summary = pd.DataFrame(
            [
                {
                    "scan_date": "2026-07-10",
                    "latest_candle_date": "2026-07-09",
                }
            ]
        )

        messages = _freshness_messages({}, summary, today=pd.Timestamp("2026-07-10"))

        self.assertEqual(messages[0][0], "info")
        self.assertIn("latest daily candle is 2026-07-09", messages[0][1])


if __name__ == "__main__":
    unittest.main()
