from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


SETTINGS_PATH = Path(__file__).resolve().parents[1] / "settings.json"


def _default_settings() -> Dict[str, Any]:
    return {
        "openai_api_key": "",
        "base_url": "https://api.openai.com/v1",
        "model_name": "gpt-4o",
        "rss_sources": [],
        "telegram_channels": [],
        "telegram_api_id": "",
        "telegram_api_hash": "",
    }


def _ensure_settings_file_exists() -> None:
    if SETTINGS_PATH.exists():
        return
    SETTINGS_PATH.write_text(
        json.dumps(_default_settings(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_settings() -> Dict[str, Any]:
    _ensure_settings_file_exists()
    try:
        settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {SETTINGS_PATH}") from exc

    defaults = _default_settings()
    changed = False
    for key, value in defaults.items():
        if key not in settings:
            settings[key] = value
            changed = True
    if changed:
        save_settings(settings)

    return settings


def save_settings(settings: Dict[str, Any]) -> None:
    _ensure_settings_file_exists()
    SETTINGS_PATH.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
