from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tradingbuddy.auth.kite_token import load_access_token, save_access_token, token_path, token_status


class KiteTokenTests(unittest.TestCase):
    def test_saved_token_loads_before_expiry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_access_token(root, "token-1", {"user_id": "abc"}, ttl_hours=24)

            self.assertEqual(load_access_token(root), "token-1")
            status = token_status(root)
            self.assertTrue(status["exists"])
            self.assertFalse(status["expired"])
            self.assertIsNotNone(status["expires_at"])

    def test_expired_token_is_not_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = token_path(root)
            payload = {
                "access_token": "expired",
                "generated_at": (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(),
                "expires_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
                "profile": {},
            }
            path.write_text(json.dumps(payload), encoding="utf-8")

            self.assertIsNone(load_access_token(root))
            status = token_status(root)
            self.assertFalse(status["exists"])
            self.assertTrue(status["expired"])


if __name__ == "__main__":
    unittest.main()

