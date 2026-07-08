from __future__ import annotations

import unittest

from streamlit_app import _create_kite_login_state, _extract_request_token, _is_valid_kite_login_state


class KiteRedirectTests(unittest.TestCase):
    def test_extract_request_token_from_full_redirect_url(self) -> None:
        url = "http://localhost:8501/?status=success&request_token=abc123&action=login"

        self.assertEqual(_extract_request_token(url), "abc123")

    def test_plain_request_token_is_accepted(self) -> None:
        self.assertEqual(_extract_request_token("abc123"), "abc123")

    def test_signed_kite_login_state_validates_before_expiry(self) -> None:
        state = _create_kite_login_state("secret", issued_at=1000, nonce="nonce")

        self.assertTrue(_is_valid_kite_login_state(state, "secret", now=1100))

    def test_signed_kite_login_state_rejects_tampering(self) -> None:
        state = _create_kite_login_state("secret", issued_at=1000, nonce="nonce")

        self.assertFalse(_is_valid_kite_login_state(f"{state}x", "secret", now=1100))

    def test_signed_kite_login_state_rejects_expired_state(self) -> None:
        state = _create_kite_login_state("secret", issued_at=1000, nonce="nonce")

        self.assertFalse(_is_valid_kite_login_state(state, "secret", now=2500))


if __name__ == "__main__":
    unittest.main()
