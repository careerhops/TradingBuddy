from __future__ import annotations

import getpass
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbuddy.auth.app_users import hash_password  # noqa: E402


def main() -> None:
    password = getpass.getpass("Password to hash: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        raise SystemExit("Passwords do not match")
    print(hash_password(password))


if __name__ == "__main__":
    main()
