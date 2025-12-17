from __future__ import annotations

import base64
from urllib.parse import urlparse, urlunparse
from typing import Any, Dict, Optional

import requests
from bs4 import BeautifulSoup

from modules.image_generator import build_image_prompt, generate_cover_image


def _normalize_site_root(url: str) -> str:
    parsed = urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        return url.strip().rstrip("/")
    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", "")).rstrip("/")


def _discover_rest_base(wp_url: str) -> Optional[str]:
    """
    Tries to find the REST API base URL from the site's HTML:
    <link rel="https://api.w.org/" href="https://example.com/wp-json/" />
    Returns base ending with /wp-json/ (no trailing slash normalization beyond that).
    """
    try:
        resp = requests.get(wp_url, timeout=20, headers={"Accept": "text/html"})
        if resp.status_code >= 400 or not resp.text:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        link = soup.find("link", attrs={"rel": "https://api.w.org/"})
        href = link.get("href") if link else None
        if not href:
            return None
        return str(href).rstrip("/") + "/"
    except Exception:
        return None


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

    post_data: Dict[str, Any] = {
        "title": seo_title,
        "content": html_content,
        "status": "draft",
        "meta": {
            "_yoast_wpseo_title": seo_title,
            "_yoast_wpseo_metadesc": seo_description,
            "_yoast_wpseo_focuskw": focus_keyword,
        },
    }

    # Some sites change REST prefix or have wp_url set to a subpage; try to discover correct base.
    site_root = _normalize_site_root(wp_url)
    rest_base = _discover_rest_base(wp_url) or f"{site_root}/wp-json/"

    endpoints = [
        f"{rest_base.rstrip('/')}/wp/v2/posts",
        f"{site_root}/?rest_route=/wp/v2/posts",
    ]

    # Optional: generate + upload featured image
    if settings.get("image_enabled", True):
        image_provider = settings.get("image_provider", "openai")
        image_api_key = settings.get("image_api_key") or settings.get("openai_api_key", "")
        image_base_url = settings.get("image_base_url") or settings.get("base_url")
        image_model_name = settings.get("image_model_name", "gpt-image-1")
        image_size = settings.get("image_size", "1024x1024")
        gcp_project_id = (settings.get("gcp_project_id") or "").strip() or None
        gcp_location = settings.get("gcp_location") or "us-central1"
        gcp_credentials_path = (settings.get("gcp_credentials_path") or "").strip() or None

        image_prompt = build_image_prompt(article_data)
        image_bytes, filename = generate_cover_image(
            provider=image_provider,
            api_key=image_api_key,
            base_url=image_base_url,
            model_name=image_model_name,
            size=image_size,
            prompt=image_prompt,
            gcp_project_id=gcp_project_id,
            gcp_location=gcp_location,
            gcp_credentials_path=gcp_credentials_path,
        )

        media_id = _upload_media(
            rest_base=rest_base,
            site_root=site_root,
            headers=headers,
            filename=filename,
            content_bytes=image_bytes,
            alt_text=seo_title,
        )
        if media_id:
            post_data["featured_media"] = media_id

    last_response: Optional[requests.Response] = None
    for endpoint in endpoints:
        try:
            last_response = requests.post(endpoint, json=post_data, headers=headers, timeout=60)
        except Exception:
            continue

        if last_response.status_code in (200, 201):
            data: Optional[Dict[str, Any]]
            try:
                data = last_response.json()
            except Exception:
                data = None

            if isinstance(data, dict) and data.get("link"):
                return str(data["link"])
            return endpoint

        if last_response.status_code not in (404,):
            break

    if last_response is None:
        raise RuntimeError("Ошибка публикации WP: не удалось выполнить запрос (проверьте URL сайта).")

    raise RuntimeError(
        f"Ошибка публикации WP ({last_response.status_code}): {last_response.text}\n"
        f"Endpoint: {last_response.request.url}"
    )


def _upload_media(
    *,
    rest_base: str,
    site_root: str,
    headers: Dict[str, str],
    filename: str,
    content_bytes: bytes,
    alt_text: str = "",
) -> Optional[int]:
    """
    Uploads media via WordPress REST API and returns attachment id.
    Requires user capability 'upload_files'.
    """
    media_endpoints = [
        f"{rest_base.rstrip('/')}/wp/v2/media",
        f"{site_root}/?rest_route=/wp/v2/media",
    ]

    media_headers = dict(headers)
    media_headers.pop("Content-Type", None)
    media_headers["Content-Disposition"] = f'attachment; filename="{filename}"'

    files = {"file": (filename, content_bytes, "image/png")}

    for endpoint in media_endpoints:
        try:
            resp = requests.post(endpoint, headers=media_headers, files=files, timeout=120)
        except Exception:
            continue

        if resp.status_code in (200, 201):
            try:
                data = resp.json()
                media_id = int(data.get("id"))
            except Exception:
                media_id = None

            if media_id and alt_text:
                try:
                    requests.post(
                        f"{rest_base.rstrip('/')}/wp/v2/media/{media_id}",
                        headers=headers,
                        json={"alt_text": alt_text},
                        timeout=60,
                    )
                except Exception:
                    pass

            return media_id

    return None
