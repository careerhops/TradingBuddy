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
            scan_rows_table="scan_rows",
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

    def _upsert(self, table: str, records: list[dict[str, object]], conflict_column: str) -> None:
        self.calls.append((f"upsert:{table}:{conflict_column}", len(records)))

    def _get(self, table: str, params: dict[str, str], error_label: str) -> list[dict[str, object]]:
        self.latest_params = params
        return []


class PagingSupabaseStore(RecordingSupabaseStore):
    def __init__(self, total_rows: int) -> None:
        super().__init__()
        self.total_rows = total_rows
        self.get_calls: list[dict[str, str]] = []

    def _get(self, table: str, params: dict[str, str], error_label: str) -> list[dict[str, object]]:
        self.get_calls.append(params)
        offset = int(params.get("offset", 0))
        limit = int(params.get("limit", 1000))
        end = min(offset + limit, self.total_rows)
        return [{"scan_sequence": index + 1, "symbol": f"SYM{index}"} for index in range(offset, end)]


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

    def test_latest_incomplete_scan_run_filters_current_kite_run(self) -> None:
        store = RecordingSupabaseStore()

        store.load_latest_incomplete_scan_run("2026-07-10")

        self.assertIsNotNone(store.latest_params)
        self.assertEqual(store.latest_params.get("scan_date"), "eq.2026-07-10")
        self.assertEqual(store.latest_params.get("refresh_mode"), "eq.kite_refresh")
        self.assertEqual(store.latest_params.get("run_completed_at"), "is.null")

    def test_load_scan_rows_paginates_past_1000_rows(self) -> None:
        store = PagingSupabaseStore(total_rows=2305)

        rows = store.load_scan_rows("run-1")

        self.assertEqual(len(rows), 2305)
        self.assertEqual([call.get("offset") for call in store.get_calls], ["0", "1000", "2000"])
        self.assertEqual([call.get("limit") for call in store.get_calls], ["1000", "1000", "1000"])

    def test_save_scan_rows_upserts_in_100_row_batches(self) -> None:
        store = RecordingSupabaseStore()
        frame = pd.DataFrame(
            [
                {
                    "run_id": "run-1",
                    "run_started_at": "2026-07-10T08:10:00+05:30",
                    "scan_sequence": index + 1,
                    "exchange": "NSE",
                    "symbol": f"SYM{index}",
                    "tradingview_symbol": f"NSE:SYM{index}",
                }
                for index in range(450)
            ]
        )

        store.save_scan_rows(frame, batch_size=100)

        self.assertEqual(
            store.calls,
            [
                ("upsert:scan_rows:run_id,exchange,symbol", 100),
                ("upsert:scan_rows:run_id,exchange,symbol", 100),
                ("upsert:scan_rows:run_id,exchange,symbol", 100),
                ("upsert:scan_rows:run_id,exchange,symbol", 100),
                ("upsert:scan_rows:run_id,exchange,symbol", 50),
            ],
        )


if __name__ == "__main__":
    unittest.main()
