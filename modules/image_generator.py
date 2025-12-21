from __future__ import annotations

import base64
import io
import re
from typing import Any, Dict, Optional, Tuple

import openai
import requests


DEFAULT_IMAGE_PROMPT_TEMPLATE = (
    "Сгенерируй уникальную обложку для статьи (без текста на изображении). "
    "Стиль: современная веб-иллюстрация, чистые формы, высокий контраст, аккуратные детали. "
    "Без логотипов, водяных знаков и узнаваемых брендов. "
    "Тема статьи: {title}. "
    "Ключевое слово: {keyword}."
)


def _safe_filename(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"\s+", "-", text)
    # HTTP headers are typically latin-1; keep filename ASCII-only to avoid upload failures.
    text = re.sub(r"[^a-z0-9\-]+", "", text)
    text = text.strip("-") or "cover"
    return f"{text[:80]}.png"


def build_image_prompt(article_data: Dict[str, Any], *, template: Optional[str] = None) -> str:
    title = (article_data.get("seo_title") or "").strip()
    keyword = (article_data.get("focus_keyword") or "").strip()
    tmpl = (template or "").strip() or DEFAULT_IMAGE_PROMPT_TEMPLATE
    try:
        return tmpl.format(title=title, keyword=keyword).strip()
    except Exception:
        return f"{tmpl}\n\nТема статьи: {title}\nКлючевое слово: {keyword}".strip()


def _normalize_size_for_openai(*, model_name: str, size: str) -> str:
    """
    Some OpenAI image models support only a subset of sizes.
    - For gpt-image-1, common supported sizes are 1024x1024, 1536x1024, 1024x1536.
      UI exposes 1792x1024 / 1024x1792 (DALL·E 3 style), so we map them to the closest gpt-image-1 sizes.
    """
    model = (model_name or "").strip().lower()
    requested = (size or "").strip().lower()
    if model == "gpt-image-1":
        mapping = {
            "1792x1024": "1536x1024",
            "1024x1792": "1024x1536",
        }
        return mapping.get(requested, requested)
    return requested


def _aspect_ratio_for_size(size: str) -> Optional[str]:
    s = (size or "").strip()
    if s == "1024x1024":
        return "1:1"
    if s == "1792x1024":
        return "16:9"
    if s == "1024x1792":
        return "9:16"
    return None


def _desired_ratio_from_size(size: str) -> Optional[float]:
    try:
        w_s, h_s = (size or "").lower().split("x", 1)
        w = int(w_s)
        h = int(h_s)
        if w <= 0 or h <= 0:
            return None
        return w / h
    except Exception:
        return None


def _coerce_image_aspect(image_bytes: bytes, *, desired_ratio: Optional[float]) -> bytes:
    """
    Best-effort post-processing: if the provider returned a wrong aspect ratio (e.g. 1024x1024),
    crop the image to match the requested ratio (center-crop). Keeps original pixel density.
    """
    if not image_bytes or not desired_ratio:
        return image_bytes

    try:
        from PIL import Image
    except Exception:
        return image_bytes

    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            w, h = img.size
            if not w or not h:
                return image_bytes
            current_ratio = w / h
            if abs(current_ratio - desired_ratio) < 0.02:
                return image_bytes

            if current_ratio > desired_ratio:
                # too wide -> crop width
                new_w = int(h * desired_ratio)
                if new_w <= 0 or new_w > w:
                    return image_bytes
                left = (w - new_w) // 2
                box = (left, 0, left + new_w, h)
            else:
                # too tall -> crop height
                new_h = int(w / desired_ratio)
                if new_h <= 0 or new_h > h:
                    return image_bytes
                top = (h - new_h) // 2
                box = (0, top, w, top + new_h)

            cropped = img.crop(box)
            out = io.BytesIO()
            cropped.save(out, format="PNG")
            return out.getvalue()
    except Exception:
        return image_bytes


def generate_cover_image(
    *,
    provider: str,
    api_key: str,
    model_name: str,
    prompt: str,
    base_url: Optional[str] = None,
    size: str = "1024x1024",
    force_aspect_crop: bool = False,
    gcp_project_id: Optional[str] = None,
    gcp_location: str = "us-central1",
    gcp_credentials_path: Optional[str] = None,
) -> Tuple[bytes, str]:
    """
    Returns (image_bytes, filename).
    Supports:
    - provider="openai": OpenAI Images API (or compatible, if supported)
    - provider="vertex_imagen": Google Vertex AI Imagen
    - provider="flux": reserved (not implemented yet)
    """
    if provider not in {"openai", "vertex_imagen", "flux"}:
        raise ValueError('image provider must be one of: "openai", "vertex_imagen", "flux"')
    if not model_name:
        raise ValueError("image model_name is required")
    if not prompt.strip():
        raise ValueError("image prompt is empty")

    try:
        filename = _safe_filename(prompt)
        desired_ratio = _desired_ratio_from_size(size)

        if provider == "openai":
            if not api_key:
                raise ValueError("image api_key is required")
            client = openai.OpenAI(api_key=api_key, base_url=base_url)
            effective_size = _normalize_size_for_openai(model_name=model_name, size=size)
            # Prefer base64 response to avoid extra download step.
            try:
                resp = client.images.generate(
                    model=model_name,
                    prompt=prompt,
                    size=effective_size,
                    response_format="b64_json",
                )
            except Exception as exc:
                msg = str(exc)
                if "Unknown parameter: 'response_format'" not in msg:
                    raise
                resp = client.images.generate(
                    model=model_name,
                    prompt=prompt,
                    size=effective_size,
                )

            first = resp.data[0]

            b64 = getattr(first, "b64_json", None)
            if b64:
                img_bytes = base64.b64decode(b64)
                if force_aspect_crop:
                    img_bytes = _coerce_image_aspect(img_bytes, desired_ratio=desired_ratio)
                return img_bytes, filename

            url = getattr(first, "url", None)
            if url:
                r = requests.get(url, timeout=120)
                r.raise_for_status()
                img_bytes = r.content
                if force_aspect_crop:
                    img_bytes = _coerce_image_aspect(img_bytes, desired_ratio=desired_ratio)
                return img_bytes, filename

            raise RuntimeError("Images API returned no b64_json or url")

        if provider == "flux":
            raise NotImplementedError(f'Image provider "{provider}" is not implemented yet')

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
        aspect_ratio = _aspect_ratio_for_size(size)
        try:
            if aspect_ratio:
                images = model.generate_images(prompt=prompt, number_of_images=1, aspect_ratio=aspect_ratio)
            else:
                images = model.generate_images(prompt=prompt, number_of_images=1)
        except TypeError:
            # Some SDK versions may accept width/height instead of aspect_ratio
            try:
                if "x" in (size or ""):
                    w_s, h_s = (size or "").split("x", 1)
                    w = int(w_s)
                    h = int(h_s)
                    images = model.generate_images(prompt=prompt, number_of_images=1, width=w, height=h)
                else:
                    images = model.generate_images(prompt=prompt, number_of_images=1)
            except Exception:
                images = model.generate_images(prompt=prompt, number_of_images=1)
        if not images:
            raise RuntimeError("Vertex Imagen returned no images")
        image = images[0]

        # Best-effort extraction of bytes (SDK versions differ)
        if hasattr(image, "image_bytes"):
            raw = image.image_bytes  # type: ignore[attr-defined]
            if force_aspect_crop:
                raw = _coerce_image_aspect(raw, desired_ratio=desired_ratio)
            return raw, filename
        if hasattr(image, "_image_bytes"):
            raw = image._image_bytes  # type: ignore[attr-defined]
            if force_aspect_crop:
                raw = _coerce_image_aspect(raw, desired_ratio=desired_ratio)
            return raw, filename

        # Fallback: save to bytes via temp file
        buf = io.BytesIO()
        image.save(buf)  # type: ignore[attr-defined]
        raw = buf.getvalue()
        if force_aspect_crop:
            raw = _coerce_image_aspect(raw, desired_ratio=desired_ratio)
        return raw, filename
    except Exception as exc:
        raise RuntimeError(
            f"Image generation error: {exc}."
        ) from exc
