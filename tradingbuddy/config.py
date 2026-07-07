from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


def load_config(path: str | Path = "config/settings.yaml") -> dict[str, Any]:
    load_dotenv(override=True)
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}

    return config


def get_setting(name: str, default: str | None = None) -> str | None:
    """Read a setting from environment variables.

    Streamlit secrets are copied into os.environ by the app before calling this
    helper, so core code remains independent from Streamlit.
    """

    return os.getenv(name, default)


def get_data_root(config: dict[str, Any]) -> Path:
    data_cfg = config.get("data", {})
    env_name = data_cfg.get("data_root_env", "DATA_ROOT")
    root = get_setting(env_name, "data")
    path = Path(str(root))
    path.mkdir(parents=True, exist_ok=True)
    return path


def require_env(name: str) -> str:
    value = get_setting(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value

