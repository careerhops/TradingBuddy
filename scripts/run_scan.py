from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbuddy.config import get_data_root, load_config  # noqa: E402
from tradingbuddy.data.storage import Storage  # noqa: E402
from tradingbuddy.scan import run_scan  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the TradingBuddy scan outside Streamlit.")
    parser.add_argument("--max-symbols", type=int, default=0, help="Optional symbol limit for test runs.")
    parser.add_argument("--require-supabase", action="store_true", help="Fail unless the scan result is saved to Supabase.")
    args = parser.parse_args()

    config = load_config()
    storage = Storage(get_data_root(config))

    result = run_scan(
        config,
        storage,
        refresh_data=True,
        max_symbols=args.max_symbols if args.max_symbols > 0 else None,
        progress_callback=_progress,
    )
    summary = result.summary
    print(
        "Scan complete: "
        f"{summary['symbols_scanned']} scanned, "
        f"{summary['minervini_pass_count']} Minervini, "
        f"{summary['weekly_buy_sell_count']} weekly BUY/SELL, "
        f"Supabase={summary.get('supabase_status', '-')}"
    )
    if args.require_supabase and summary.get("supabase_status") != "saved":
        raise SystemExit(f"Supabase save was required but finished as {summary.get('supabase_status', '-')}")


def _progress(payload: dict[str, Any]) -> None:
    total = int(payload.get("total") or 0)
    completed = int(payload.get("completed") or 0)
    phase = str(payload.get("phase") or "")
    symbol = str(payload.get("current_symbol") or "")
    if total and (completed == 0 or completed == total or completed % 100 == 0):
        print(f"{phase}: {completed}/{total} {symbol}".strip(), flush=True)
    elif not total:
        print(phase, flush=True)


if __name__ == "__main__":
    main()
