from __future__ import annotations

import base64
from typing import Any, Dict, Optional

import requests


def publish_to_wordpress(settings: dict, article_data: Dict[str, Any]) -> str:
    """
    Отправляет статью в WordPress через REST API.
    Заполняет поля Yoast SEO (Title, Description, Keyword).
    Возвращает ссылку на созданный пост.
    """
    wp_url = (settings.get("wp_url", "") or "").rstrip("/")
    wp_user = settings.get("wp_user", "") or ""
    wp_password = settings.get("wp_password", "") or ""

    if not wp_url or not wp_user or not wp_password:
        raise ValueError("Не заполнены настройки WordPress (URL, Логин или Пароль приложения).")

    creds = f"{wp_user}:{wp_password}"
    token = base64.b64encode(creds.encode("utf-8")).decode("utf-8")
    headers = {
        "Authorization": f"Basic {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    seo_title = article_data.get("seo_title", "") or "Новая статья AI"
    seo_description = article_data.get("seo_description", "") or ""
    focus_keyword = article_data.get("focus_keyword", "") or ""
    html_content = article_data.get("html_content", "") or ""

    post_data = {
        "title": seo_title,
        "content": html_content,
        "status": "draft",
        "meta": {
            "_yoast_wpseo_title": seo_title,
            "_yoast_wpseo_metadesc": seo_description,
            "_yoast_wpseo_focuskw": focus_keyword,
        },
    }

    endpoint = f"{wp_url}/wp-json/wp/v2/posts"
    response = requests.post(endpoint, json=post_data, headers=headers, timeout=60)

    if response.status_code in (200, 201):
        data: Optional[Dict[str, Any]]
        try:
            data = response.json()
        except Exception:
            data = None

        if isinstance(data, dict) and data.get("link"):
            return str(data["link"])
        return endpoint

    raise RuntimeError(f"Ошибка публикации WP ({response.status_code}): {response.text}")

