from __future__ import annotations

from typing import Optional

import google.generativeai as genai
import openai


SYSTEM_PROMPT = (
    "Ты профессиональный редактор. Твоя задача — писать статьи на РУССКОМ языке. "
    "Используй Markdown. Структура: H1, введение, H2, списки, заключение."
)


def generate_article(
    prompt: str,
    provider: str,
    *,
    api_key: str,
    model_name: str,
    base_url: Optional[str] = None,
) -> str:
    if not prompt.strip():
        raise ValueError("prompt is empty")
    if provider not in {"openai", "gemini"}:
        raise ValueError('provider must be "openai" or "gemini"')
    if not api_key:
        raise ValueError("api_key is required")
    if not model_name:
        raise ValueError("model_name is required")

    if provider == "openai":
        try:
            client = openai.OpenAI(api_key=api_key, base_url=base_url)
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
            content = (response.choices[0].message.content or "").strip()
            if not content:
                raise RuntimeError("Empty response from OpenAI-compatible provider")
            return content
        except Exception as exc:
            raise RuntimeError(f"OpenAI provider error: {exc}") from exc

    try:
        genai.configure(api_key=api_key)
        try:
            model = genai.GenerativeModel(model_name=model_name, system_instruction=SYSTEM_PROMPT)
            response = model.generate_content(prompt)
        except TypeError:
            model = genai.GenerativeModel(model_name=model_name)
            response = model.generate_content(f"{SYSTEM_PROMPT}\n\n{prompt}")

        text = getattr(response, "text", None)
        if not text or not str(text).strip():
            raise RuntimeError("Empty response from Gemini provider")
        return str(text).strip()
    except Exception as exc:
        raise RuntimeError(f"Gemini provider error: {exc}") from exc

