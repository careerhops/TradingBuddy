from __future__ import annotations

import unittest

import pandas as pd

from streamlit_app import (
    _choose_result_bundle,
    _freshness_messages,
    _github_workflow_dispatch_request,
    _normalize_github_repository,
    _normalize_github_workflow_id,
)


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

    def test_github_workflow_dispatch_request_uses_scan_inputs(self) -> None:
        url, payload, workflow_url = _github_workflow_dispatch_request(
            repo="careerhops/TradingBuddy",
            workflow_id="run-scan.yml",
            branch="main",
            cached_only=False,
            max_symbols=0,
        )

        self.assertEqual(
            url,
            "https://api.github.com/repos/careerhops/TradingBuddy/actions/workflows/run-scan.yml/dispatches",
        )
        self.assertEqual(payload["ref"], "main")
        self.assertEqual(payload["inputs"], {"cached_only": "false", "max_symbols": "0"})
        self.assertEqual(workflow_url, "https://github.com/careerhops/TradingBuddy/actions/workflows/run-scan.yml")

    def test_github_workflow_dispatch_request_accepts_github_urls(self) -> None:
        url, payload, workflow_url = _github_workflow_dispatch_request(
            repo="https://github.com/careerhops/TradingBuddy",
            workflow_id="https://github.com/careerhops/TradingBuddy/actions/workflows/run-scan.yml",
            branch="main",
            cached_only=True,
            max_symbols=50,
        )

        self.assertEqual(
            url,
            "https://api.github.com/repos/careerhops/TradingBuddy/actions/workflows/run-scan.yml/dispatches",
        )
        self.assertEqual(payload["inputs"], {"cached_only": "true", "max_symbols": "50"})
        self.assertEqual(workflow_url, "https://github.com/careerhops/TradingBuddy/actions/workflows/run-scan.yml")

    def test_github_config_normalizers_accept_common_values(self) -> None:
        self.assertEqual(_normalize_github_repository("git@github.com:careerhops/TradingBuddy.git"), "careerhops/TradingBuddy")
        self.assertEqual(_normalize_github_repository("https://api.github.com/repos/careerhops/TradingBuddy"), "careerhops/TradingBuddy")
        self.assertEqual(_normalize_github_workflow_id(".github/workflows/run-scan.yml"), "run-scan.yml")
        self.assertEqual(_normalize_github_workflow_id("309067668"), "309067668")

    def test_github_repository_normalizer_rejects_invalid_value(self) -> None:
        with self.assertRaises(ValueError):
            _normalize_github_repository("TradingBuddy")


if __name__ == "__main__":
    unittest.main()
