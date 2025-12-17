from __future__ import annotations

import base64
import re
from typing import Any, Dict, Optional, Tuple

import openai
import requests


def _safe_filename(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"\s+", "-", text)
    # HTTP headers are typically latin-1; keep filename ASCII-only to avoid upload failures.
    text = re.sub(r"[^a-z0-9\-]+", "", text)
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
    gcp_project_id: Optional[str] = None,
    gcp_location: str = "us-central1",
    gcp_credentials_path: Optional[str] = None,
) -> Tuple[bytes, str]:
    """
    Returns (image_bytes, filename).
    Supports:
    - provider="openai": OpenAI Images API (or compatible, if supported)
    - provider="vertex_imagen": Google Vertex AI Imagen
    """
    if provider not in {"openai", "vertex_imagen"}:
        raise ValueError('image provider must be "openai" or "vertex_imagen"')
    if not model_name:
        raise ValueError("image model_name is required")
    if not prompt.strip():
        raise ValueError("image prompt is empty")

    try:
        filename = _safe_filename(prompt)

        if provider == "openai":
            if not api_key:
                raise ValueError("image api_key is required")
            client = openai.OpenAI(api_key=api_key, base_url=base_url)
            # Prefer base64 response to avoid extra download step.
            try:
                resp = client.images.generate(
                    model=model_name,
                    prompt=prompt,
                    size=size,
                    response_format="b64_json",
                )
            except Exception as exc:
                msg = str(exc)
                if "Unknown parameter: 'response_format'" not in msg:
                    raise
                resp = client.images.generate(
                    model=model_name,
                    prompt=prompt,
                    size=size,
                )

            first = resp.data[0]

            b64 = getattr(first, "b64_json", None)
            if b64:
                return base64.b64decode(b64), filename

            url = getattr(first, "url", None)
            if url:
                r = requests.get(url, timeout=120)
                r.raise_for_status()
                return r.content, filename

            raise RuntimeError("Images API returned no b64_json or url")

        # provider == "vertex_imagen"
        if not gcp_project_id:
            raise ValueError("gcp_project_id is required for vertex_imagen")
        if not gcp_credentials_path:
            raise ValueError("gcp_credentials_path is required for vertex_imagen")

        from google.oauth2 import service_account
        import vertexai
        from vertexai.preview.vision_models import ImageGenerationModel

        credentials = service_account.Credentials.from_service_account_file(gcp_credentials_path)
        vertexai.init(project=gcp_project_id, location=gcp_location, credentials=credentials)

        model = ImageGenerationModel.from_pretrained(model_name)
        images = model.generate_images(prompt=prompt, number_of_images=1)
        if not images:
            raise RuntimeError("Vertex Imagen returned no images")
        image = images[0]

        # Best-effort extraction of bytes (SDK versions differ)
        if hasattr(image, "image_bytes"):
            return image.image_bytes, filename  # type: ignore[attr-defined]
        if hasattr(image, "_image_bytes"):
            return image._image_bytes, filename  # type: ignore[attr-defined]

        # Fallback: save to bytes via temp file
        import io

        buf = io.BytesIO()
        image.save(buf)  # type: ignore[attr-defined]
        return buf.getvalue(), filename
    except Exception as exc:
        raise RuntimeError(
            f"Image generation error: {exc}."
        ) from exc
