from __future__ import annotations

import unittest

from tradingbuddy.auth.app_users import hash_password, verify_password
from streamlit_app import _authenticate_app_user


class FakeSupabase:
    def __init__(self, rows: dict[str, dict[str, object]]) -> None:
        self.rows = rows

    def load_app_user(self, user_id: str) -> dict[str, object] | None:
        return self.rows.get(user_id)


class AppUserTests(unittest.TestCase):
    def test_hash_password_verifies_only_matching_password(self) -> None:
        password_hash = hash_password("strong-password")

        self.assertTrue(verify_password("strong-password", password_hash))
        self.assertFalse(verify_password("wrong-password", password_hash))

    def test_supabase_admin_user_authenticates_with_role(self) -> None:
        password_hash = hash_password("admin-password")
        supabase = FakeSupabase(
            {
                "admin": {
                    "user_id": "admin",
                    "role": "admin",
                    "password_hash": password_hash,
                    "is_active": True,
                }
            }
        )

        result = _authenticate_app_user(
            supabase=supabase,  # type: ignore[arg-type]
            user_id="admin",
            password="admin-password",
            admin_user_id="local-admin",
            admin_password="",
            fallback_user_id="",
            fallback_user_password="",
        )

        self.assertEqual(result, {"role": "admin", "user_id": "admin"})

    def test_supabase_viewer_user_authenticates_with_user_role(self) -> None:
        password_hash = hash_password("viewer-password")
        supabase = FakeSupabase(
            {
                "viewer": {
                    "user_id": "viewer",
                    "role": "user",
                    "password_hash": password_hash,
                    "is_active": True,
                }
            }
        )

        result = _authenticate_app_user(
            supabase=supabase,  # type: ignore[arg-type]
            user_id="viewer",
            password="viewer-password",
            admin_user_id="local-admin",
            admin_password="",
            fallback_user_id="",
            fallback_user_password="",
        )

        self.assertEqual(result, {"role": "user", "user_id": "viewer"})

    def test_local_fallback_still_supports_private_runs(self) -> None:
        result = _authenticate_app_user(
            supabase=None,
            user_id="admin",
            password="admin-password",
            admin_user_id="admin",
            admin_password="admin-password",
            fallback_user_id="viewer",
            fallback_user_password="viewer-password",
        )

        self.assertEqual(result, {"role": "admin", "user_id": "admin"})


if __name__ == "__main__":
    unittest.main()
