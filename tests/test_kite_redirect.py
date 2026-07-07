from __future__ import annotations

import unittest

from streamlit_app import _extract_request_token


class KiteRedirectTests(unittest.TestCase):
    def test_extract_request_token_from_full_redirect_url(self) -> None:
        url = "http://localhost:8501/?status=success&request_token=abc123&action=login"

        self.assertEqual(_extract_request_token(url), "abc123")

    def test_plain_request_token_is_accepted(self) -> None:
        self.assertEqual(_extract_request_token("abc123"), "abc123")


if __name__ == "__main__":
    unittest.main()

