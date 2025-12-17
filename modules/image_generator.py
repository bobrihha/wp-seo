from __future__ import annotations

import base64
import re
from typing import Any, Dict, Optional, Tuple

import openai


def _safe_filename(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[^a-z0-9а-яё\-]+", "", text, flags=re.IGNORECASE)
    text = text.strip("-") or "cover"
    return f"{text[:80]}.png"


def build_image_prompt(article_data: Dict[str, Any]) -> str:
    title = (article_data.get("seo_title") or "").strip()
    keyword = (article_data.get("focus_keyword") or "").strip()
    return (
        "Сгенерируй уникальную обложку для статьи (без текста на изображении). "
        "Стиль: современная веб-иллюстрация, чистые формы, высокий контраст, аккуратные детали. "
        "Без логотипов, водяных знаков и узнаваемых брендов. "
        f"Тема статьи: {title}. "
        f"Ключевое слово: {keyword}."
    )


def generate_cover_image(
    *,
    provider: str,
    api_key: str,
    model_name: str,
    prompt: str,
    base_url: Optional[str] = None,
    size: str = "1024x1024",
) -> Tuple[bytes, str]:
    """
    Returns (image_bytes, filename).
    Currently supports OpenAI-compatible Images API.
    """
    if provider != "openai":
        raise ValueError('image provider must be "openai" for now')
    if not api_key:
        raise ValueError("image api_key is required")
    if not model_name:
        raise ValueError("image model_name is required")
    if not prompt.strip():
        raise ValueError("image prompt is empty")

    try:
        client = openai.OpenAI(api_key=api_key, base_url=base_url)
        # Prefer base64 response to avoid extra download step.
        resp = client.images.generate(
            model=model_name,
            prompt=prompt,
            size=size,
            response_format="b64_json",
        )
        b64 = resp.data[0].b64_json  # type: ignore[attr-defined]
        image_bytes = base64.b64decode(b64)
        filename = _safe_filename(prompt)
        return image_bytes, filename
    except Exception as exc:
        raise RuntimeError(f"Image generation error: {exc}") from exc

