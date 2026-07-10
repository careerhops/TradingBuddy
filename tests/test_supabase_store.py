from __future__ import annotations

import unittest

import pandas as pd

from tradingbuddy.data.supabase_store import SupabaseStore


class RecordingSupabaseStore(SupabaseStore):
    def __init__(self) -> None:
        super().__init__(
            url="https://example.supabase.co",
            service_role_key="service-role",
            scan_runs_table="scan_runs",
            minervini_table="minervini",
            weekly_table="weekly",
            overlap_history_table="overlap",
            kite_tokens_table="tokens",
            app_users_table="users",
        )
        self.calls: list[tuple[str, object]] = []
        self.latest_params: dict[str, str] | None = None

    def _upsert_scan_run(self, summary: dict[str, object]) -> None:
        self.calls.append(("run", summary.get("run_completed_at")))

    def save_minervini_shortlist(self, frame: pd.DataFrame) -> None:
        self.calls.append(("minervini", len(frame)))

    def save_weekly_shortlist(self, frame: pd.DataFrame) -> None:
        self.calls.append(("weekly", len(frame)))

    def save_overlap_history(self, frame: pd.DataFrame) -> None:
        self.calls.append(("overlap", len(frame)))

    def _get(self, table: str, params: dict[str, str], error_label: str) -> list[dict[str, object]]:
        self.latest_params = params
        return []


class SupabaseStoreTests(unittest.TestCase):
    def test_save_scan_result_marks_completed_after_child_tables(self) -> None:
        store = RecordingSupabaseStore()
        summary = {"run_id": "run-1", "run_completed_at": "2026-07-10T08:10:00+05:30"}

        store.save_scan_result(
            summary,
            minervini_frame=pd.DataFrame([{"symbol": "AZAD"}]),
            weekly_frame=pd.DataFrame([{"symbol": "AZAD"}]),
            overlap_history_frame=pd.DataFrame([{"symbol": "AZAD"}]),
        )

        self.assertEqual(
            store.calls,
            [
                ("run", None),
                ("minervini", 1),
                ("weekly", 1),
                ("overlap", 1),
                ("run", "2026-07-10T08:10:00+05:30"),
            ],
        )

    def test_latest_scan_run_ignores_incomplete_runs(self) -> None:
        store = RecordingSupabaseStore()

        store.load_latest_scan_run()

        self.assertIsNotNone(store.latest_params)
        self.assertEqual(store.latest_params.get("run_completed_at"), "not.is.null")


if __name__ == "__main__":
    unittest.main()
