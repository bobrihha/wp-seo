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

    wp_post_status = (settings.get("wp_post_status") or "draft").strip().lower()
    allowed_statuses = {"draft", "publish", "private", "pending", "future"}
    if wp_post_status not in allowed_statuses:
        wp_post_status = "draft"

    post_data: Dict[str, Any] = {
        "title": seo_title,
        "content": html_content,
        "status": wp_post_status,
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

    def _resolve_image_api_key(provider: str) -> str:
        provider = (provider or "").strip()
        if provider == "openai":
            return (
                (settings.get("openai_image_api_key") or "").strip()
                or (settings.get("image_api_key") or "").strip()
                or (settings.get("openai_api_key") or "").strip()
            )
        if provider == "flux":
            return (settings.get("flux_image_api_key") or "").strip()
        return (settings.get("image_api_key") or "").strip()

    def _build_paragraph_image_prompt(*, paragraph_text: str, index: int) -> str:
        title = (article_data.get("seo_title") or "").strip()
        keyword = (article_data.get("focus_keyword") or "").strip()
        text = (paragraph_text or "").strip()
        if len(text) > 600:
            text = text[:600].rsplit(" ", 1)[0] + "…"
        template = (
            (settings.get("image_prompt_template") or "").strip() if settings.get("image_prompt_use_custom") else ""
        )
        if template:
            try:
                base = template.format(title=title, keyword=keyword).strip()
            except Exception:
                base = template
            return f"{base}\n\nПараграф #{index + 1}: {text}".strip()
        return (
            "Сгенерируй иллюстрацию для параграфа статьи (без текста на изображении). "
            "Стиль: современная веб-иллюстрация/рендер, чистые формы, аккуратные детали, высокий контраст. "
            "Без логотипов, водяных знаков и узнаваемых брендов.\n"
            f"Статья: {title}\n"
            f"Ключевое слово: {keyword}\n"
            f"Параграф #{index + 1}: {text}"
        )

    # Optional: generate + upload featured image
    if settings.get("image_enabled", True):
        image_provider = settings.get("image_provider", "openai")
        image_api_key = _resolve_image_api_key(image_provider)
        image_base_url = settings.get("image_base_url") or settings.get("base_url")
        image_model_name = settings.get("image_model_name", "gpt-image-1")
        image_size = settings.get("image_size", "1024x1024")
        gcp_project_id = (settings.get("gcp_project_id") or "").strip() or None
        gcp_location = settings.get("gcp_location") or "us-central1"
        gcp_credentials_path = (settings.get("gcp_credentials_path") or "").strip() or None

        template = settings.get("image_prompt_template") if settings.get("image_prompt_use_custom") else None
        image_prompt = build_image_prompt(article_data, template=template)
        image_bytes, filename = generate_cover_image(
            provider=image_provider,
            api_key=image_api_key,
            base_url=image_base_url,
            model_name=image_model_name,
            size=image_size,
            force_aspect_crop=bool(settings.get("image_force_aspect_crop", False)),
            prompt=image_prompt,
            gcp_project_id=gcp_project_id,
            gcp_location=gcp_location,
            gcp_credentials_path=gcp_credentials_path,
        )

        media_id, media_url = _upload_media(
            rest_base=rest_base,
            site_root=site_root,
            headers=headers,
            filename=filename,
            content_bytes=image_bytes,
            alt_text=seo_title,
        )
        if media_id:
            post_data["featured_media"] = media_id
            if media_url and isinstance(post_data.get("content"), str) and not post_data["content"].lstrip().startswith(
                "<img"
            ):
                post_data["content"] = (
                    f"<p><img class=\"ai-cover\" src=\"{media_url}\" alt=\"{seo_title}\" /></p>\n"
                    + post_data["content"]
                )

    last_response: Optional[requests.Response] = None

    # Optional: generate + upload inline images for paragraphs (done on publish, not in UI)
    if settings.get("image_per_paragraph_enabled", False) and isinstance(post_data.get("content"), str):
        try:
            max_images = int(settings.get("image_per_paragraph_max", 3) or 0)
        except (TypeError, ValueError):
            max_images = 0

        if max_images > 0:
            image_provider = settings.get("image_provider", "openai")
            image_api_key = _resolve_image_api_key(image_provider)
            image_base_url = settings.get("image_base_url") or settings.get("base_url")
            image_model_name = settings.get("image_model_name", "gpt-image-1")
            image_size = settings.get("image_size", "1024x1024")
            gcp_project_id = (settings.get("gcp_project_id") or "").strip() or None
            gcp_location = settings.get("gcp_location") or "us-central1"
            gcp_credentials_path = (settings.get("gcp_credentials_path") or "").strip() or None

            soup = BeautifulSoup(post_data["content"], "html.parser")
            paragraphs = soup.find_all("p")

            inserted = 0
            for idx, p in enumerate(paragraphs):
                if inserted >= max_images:
                    break
                if p.find("img") is not None:
                    continue
                text = p.get_text(" ", strip=True)
                if not text or len(text) < 60:
                    continue

                prompt = _build_paragraph_image_prompt(paragraph_text=text, index=idx)
                image_bytes, filename = generate_cover_image(
                    provider=image_provider,
                    api_key=image_api_key,
                    base_url=image_base_url,
                    model_name=image_model_name,
                    size=image_size,
                    force_aspect_crop=bool(settings.get("image_force_aspect_crop", False)),
                    prompt=prompt,
                    gcp_project_id=gcp_project_id,
                    gcp_location=gcp_location,
                    gcp_credentials_path=gcp_credentials_path,
                )
                media_id, media_url = _upload_media(
                    rest_base=rest_base,
                    site_root=site_root,
                    headers=headers,
                    filename=filename,
                    content_bytes=image_bytes,
                    alt_text=seo_title,
                )
                if not media_id or not media_url:
                    continue

                img_tag = soup.new_tag("img")
                img_tag["class"] = "ai-inline"
                img_tag["src"] = media_url
                img_tag["alt"] = seo_title
                wrapper = soup.new_tag("p")
                wrapper.append(img_tag)
                p.insert_after(wrapper)
                inserted += 1

            if soup.body is not None:
                post_data["content"] = soup.body.decode_contents()
            else:
                post_data["content"] = str(soup)

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
) -> tuple[int, Optional[str]]:
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

    last_resp: Optional[requests.Response] = None
    last_exc: Optional[Exception] = None
    for endpoint in media_endpoints:
        try:
            resp = requests.post(endpoint, headers=media_headers, files=files, timeout=120)
        except Exception as exc:
            last_exc = exc
            continue

        last_resp = resp
        if resp.status_code in (200, 201):
            try:
                data = resp.json()
                media_id = int(data.get("id"))
                media_url = data.get("source_url") or data.get("guid", {}).get("rendered")
            except Exception:
                media_id = None
                media_url = None

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

            return media_id, str(media_url) if media_url else None

        # If REST exists but request is forbidden/unauthorized/etc, surface it immediately.
        if resp.status_code not in (404,):
            raise RuntimeError(f"WP media upload failed ({resp.status_code}): {resp.text}\nEndpoint: {endpoint}")

    if last_resp is not None:
        raise RuntimeError(
            f"WP media upload failed ({last_resp.status_code}): {last_resp.text}\n"
            f"Endpoint: {last_resp.request.url}"
        )
    if last_exc is not None:
        raise RuntimeError(
            "WP media upload failed: request did not complete.\n"
            f"Last error: {type(last_exc).__name__}: {last_exc}\n"
            f"Tried endpoints: {', '.join(media_endpoints)}"
        )
    raise RuntimeError(f"WP media upload failed: no response received. Tried endpoints: {', '.join(media_endpoints)}")
