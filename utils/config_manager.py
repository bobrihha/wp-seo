from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


SETTINGS_PATH = Path(__file__).resolve().parents[1] / "settings.json"


def _default_settings() -> Dict[str, Any]:
    return {
        "wp_url": "",
        "wp_user": "",
        "wp_password": "",
        "wp_post_status": "draft",
        "openai_api_key": "",
        "base_url": "https://api.openai.com/v1",
        "model_name": "gpt-4o",
        "gemini_api_key": "",
        "gemini_model_name": "",
        "article_system_prompt": "",
        "site_language": "ru",
        "content_style": "professional",
        "content_format": "article",
        "author_mood": "neutral",
        "target_length_chars": 6000,
        "headings_h2_count": 4,
        "headings_h3_count": 6,
        "image_enabled": True,
        "image_provider": "openai",
        "image_api_key": "",
        "openai_image_api_key": "",
        "flux_image_api_key": "",
        "flux_image_base_url": "",
        "image_base_url": "https://api.openai.com/v1",
        "image_model_name": "gpt-image-1",
        "image_size": "1024x1024",
        "image_show_preview": False,
        "image_per_paragraph_enabled": False,
        "image_per_paragraph_max": 3,
        "image_prompt_use_custom": False,
        "image_prompt_template": "",
        "image_force_aspect_crop": False,
        "gcp_project_id": "",
        "gcp_location": "us-central1",
        "gcp_credentials_path": "",
        "rss_sources": [],
        "youtube_channels": [],
        "telegram_channels": [],
        "telegram_api_id": "",
        "telegram_api_hash": "",
        "telegram_session_path": "secrets/telethon.session",
        "ad_code": "",
        "ad_paragraph": 3,
        "youtube_embed_enabled": True,

        # --- Autopilot ---
        "autopilot_enabled": False,
        "autopilot_rss_enabled": True,
        "autopilot_youtube_enabled": False,
        "autopilot_telegram_enabled": False,
        "autopilot_rss_mode": "draft",
        "autopilot_youtube_mode": "draft",
        "autopilot_telegram_mode": "draft",
        "autopilot_rss_poll_minutes": 10,
        "autopilot_youtube_poll_minutes": 10,
        "autopilot_telegram_poll_minutes": 10,
        "autopilot_daily_limit_total": 10,
        "autopilot_max_per_run": 5,
        "autopilot_rss_limit_per_feed": 3,
        "autopilot_youtube_limit_per_channel": 3,
        "autopilot_telegram_limit_per_channel": 3,
        "youtube_api_key": "",
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
