from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def token_path(data_root: Path) -> Path:
    directory = data_root / "secrets"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "kite_access_token.json"


def save_access_token(
    data_root: Path,
    access_token: str,
    profile: dict[str, Any] | None = None,
    ttl_hours: int = 24,
) -> Path:
    path = token_path(data_root)
    generated_at = datetime.now(timezone.utc)
    expires_at = generated_at + timedelta(hours=ttl_hours)
    payload = {
        "access_token": access_token,
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "expires_at": expires_at.isoformat(timespec="seconds"),
        "profile": profile or {},
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_access_token(data_root: Path) -> str | None:
    path = token_path(data_root)
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        if _is_expired(payload.get("expires_at")):
            return None
        token = payload.get("access_token")
        if token:
            return str(token)

    return None


def token_status(data_root: Path) -> dict[str, Any]:
    path = token_path(data_root)
    if not path.exists():
        return {"exists": False, "generated_at": None, "expires_at": None, "expired": False, "profile": {}, "source": "local"}

    payload = json.loads(path.read_text(encoding="utf-8"))
    expired = _is_expired(payload.get("expires_at"))
    return {
        "exists": not expired,
        "generated_at": payload.get("generated_at"),
        "expires_at": payload.get("expires_at"),
        "expired": expired,
        "profile": payload.get("profile", {}),
        "source": "local",
    }


def _is_expired(expires_at: object) -> bool:
    if not expires_at:
        return False
    try:
        parsed = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed <= datetime.now(timezone.utc)
