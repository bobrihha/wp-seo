from __future__ import annotations

import json
import re
from typing import Optional, Dict, Any

import google.generativeai as genai
import openai

# Обновленный промпт для SEO-структуры
SYSTEM_PROMPT = (
    "Ты профессиональный SEO-редактор и разработчик. Твоя задача — писать статьи на РУССКОМ языке. "
    "Ты должен вернуть ответ СТРОГО в формате JSON без лишних слов."
    "\n\n"
    "Структура JSON должна быть такой:\n"
    "{\n"
    '  "seo_title": "Кликбейтный заголовок для поисковиков (до 60 символов)",\n'
    '  "seo_description": "Meta description для сниппета (до 160 символов)",\n'
    '  "focus_keyword": "Главное ключевое слово (1-2 слова)",\n'
    '  "html_content": "Полный текст статьи. ИСПОЛЬЗУЙ HTML ТЕГИ: <h2>, <h3>, <p>, <ul>, <li>, <strong>. Не используй markdown (#), только HTML."\n'
    "}"
)


def generate_article(
    prompt: str,
    provider: str,
    *,
    api_key: str,
    model_name: str,
    base_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Возвращает словарь:
    {
        "seo_title": str,
        "seo_description": str,
        "focus_keyword": str,
        "html_content": str
    }
    """
    if not prompt.strip():
        raise ValueError("prompt is empty")
    if provider not in {"openai", "gemini"}:
        raise ValueError('provider must be "openai" or "gemini"')
    if not api_key:
        raise ValueError("api_key is required")
    if not model_name:
        raise ValueError("model_name is required")

    response_text = ""

    # --- 1. Логика OpenAI (Perplexity/Kie) ---
    if provider == "openai":
        try:
            client = openai.OpenAI(api_key=api_key, base_url=base_url)
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                # Важно: просим JSON режим, чтобы не сломать парсинг
                response_format={"type": "json_object"},
            )
            response_text = (response.choices[0].message.content or "").strip()

        except Exception as exc:
            raise RuntimeError(f"OpenAI provider error: {exc}") from exc

    # --- 2. Логика Gemini ---
    else:
        try:
            genai.configure(api_key=api_key)
            # Добавляем инструкцию про JSON в сам промпт для надежности
            full_prompt = f"{SYSTEM_PROMPT}\n\nЗАДАЧА:\n{prompt}\n\nВерни только валидный JSON."

            try:
                model = genai.GenerativeModel(model_name=model_name)
                # Для новых моделей Gemini можно добавить generation_config={"response_mime_type": "application/json"}
                # Но пока сделаем универсально через промпт
                response = model.generate_content(full_prompt)
            except TypeError:
                model = genai.GenerativeModel(model_name=model_name)
                response = model.generate_content(full_prompt)

            text = getattr(response, "text", None)
            if not text or not str(text).strip():
                raise RuntimeError("Empty response from Gemini provider")
            response_text = str(text).strip()

            # Gemini иногда любит добавить ```json в начале, чистим это
            response_text = re.sub(r"^```json", "", response_text, flags=re.MULTILINE)
            response_text = re.sub(r"^```", "", response_text, flags=re.MULTILINE)
            response_text = re.sub(r"```$", "", response_text, flags=re.MULTILINE).strip()

        except Exception as exc:
            raise RuntimeError(f"Gemini provider error: {exc}") from exc

    # --- 3. Парсинг JSON ---
    try:
        data = json.loads(response_text)

        # Проверка и лечение, если ключей не хватает
        return {
            "seo_title": data.get("seo_title", "Новая статья"),
            "seo_description": data.get("seo_description", ""),
            "focus_keyword": data.get("focus_keyword", ""),
            "html_content": data.get("html_content", "") or data.get("content", ""),  # фоллбэк
        }
    except json.JSONDecodeError:
        # Если нейросеть сошла с ума и вернула не JSON, возвращаем текст как контент
        print(f"Warning: Failed to parse JSON. Raw response: {response_text[:100]}...")
        return {
            "seo_title": "Auto Generated Title",
            "seo_description": "",
            "focus_keyword": "",
            "html_content": response_text,  # Возвращаем сырой текст, чтобы не потерять статью
        }

