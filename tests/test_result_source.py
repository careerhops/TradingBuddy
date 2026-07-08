from __future__ import annotations

import unittest

import pandas as pd

from streamlit_app import _choose_result_bundle


def _bundle(source: str, started_at: str) -> dict[str, object]:
    return {
        "source": source,
        "all_results": pd.DataFrame(),
        "minervini_results": pd.DataFrame(),
        "weekly_results": pd.DataFrame(),
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


if __name__ == "__main__":
    unittest.main()
