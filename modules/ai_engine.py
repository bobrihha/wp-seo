from __future__ import annotations

import json
import re
from typing import Optional, Dict, Any, Tuple

import google.generativeai as genai
import openai

from modules.content_profile import resolve_profile


def inject_ad_block(html: str, ad_code: str, paragraph_index: int = 3) -> str:
    """
    Вставляет ad_code после paragraph_index-го параграфа (<p>...</p>) в html.
    Если параграфов меньше, вставляет в конец.
    """
    if not html or not ad_code:
        return html
    
    # Поиск всех закрывающих тегов </p>
    # Используем re.IGNORECASE на всякий случай
    matches = list(re.finditer(r"</p>", html, flags=re.IGNORECASE))
    
    if len(matches) < paragraph_index:
        # Если параграфов мало, просто добавим в конец
        return html + "\n" + ad_code
        
    # Находим позицию вставки: сразу после закрывающего тега N-го параграфа
    # paragraph_index - 1, т.к. список matches начинается с 0 (1-й параграф = индекс 0)
    # Но пользователь вводит 1-based индекс? Обычно да. Пусть 3 означает "после 3-го".
    idx = paragraph_index - 1
    if idx < 0: 
         idx = 0
         
    pos = matches[idx].end()
    
    new_html = html[:pos] + "\n" + ad_code + "\n" + html[pos:]
    return new_html


# --- ПРОМПТ С ДИЗАЙН-СИСТЕМОЙ ---
SYSTEM_PROMPT = (
    "Ты профессиональный SEO-редактор и веб-разработчик. Твоя задача — писать статьи на РУССКОМ языке. "
    "Ты должен вернуть ответ СТРОГО в формате JSON."
    "\n\n"
    "### ПРАВИЛА ОФОРМЛЕНИЯ (DESIGN SYSTEM):\n"
    "Твой HTML должен быть красивым и структурированным. Используй следующие классы:\n"
    "1. ВАЖНОЕ: Оборачивай ключевые мысли или предупреждения в <div class='ai-alert'>...</div>\n"
    "2. ВЫВОДЫ: Блок с выводами в конце оборачивай в <div class='ai-summary'>...</div>\n"
    "3. СПИСКИ: Если идет перечисление плюсов/минусов или фактов, используй <ul class='ai-list'>...</ul>\n"
    "4. ТАБЛИЦЫ: Если данные можно представить таблицей, создай её с классом <table class='ai-table'>\n"
    "5. ЗАГОЛОВКИ: Используй <h2> и <h3>. Никогда не используй <h1> (он уже есть на странице).\n"
    "\n\n"
    "### СТРУКТУРА JSON ОТВЕТА:\n"
    "{\n"
    '  "seo_title": "Кликбейтный заголовок для поисковиков (до 60 символов)",\n'
    '  "seo_description": "Meta description для сниппета (до 160 символов)",\n'
    '  "focus_keyword": "Главное ключевое слово (1-2 слова)",\n'
    '  "html_content": "Полный HTML код статьи с применением классов выше."\n'
    "}"
)


def generate_article(
    prompt: str,
    provider: str,
    *,
    api_key: str,
    model_name: str,
    base_url: Optional[str] = None,
    system_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Возвращает словарь: {seo_title, seo_description, focus_keyword, html_content}
    """
    if not prompt.strip():
        raise ValueError("prompt is empty")
    if provider not in {"openai", "gemini"}:
        raise ValueError('provider must be "openai" or "gemini"')
    if not api_key:
        raise ValueError("api_key is required")

    effective_system_prompt = (system_prompt or "").strip() or SYSTEM_PROMPT

    response_text = ""

    # --- 1. Логика OpenAI (Perplexity/Kie) ---
    if provider == "openai":
        try:
            client = openai.OpenAI(api_key=api_key, base_url=base_url)
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": effective_system_prompt},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
            )
            response_text = (response.choices[0].message.content or "").strip()

        except Exception as exc:
            raise RuntimeError(f"OpenAI error: {exc}") from exc

    # --- 2. Логика Gemini ---
    else:
        try:
            genai.configure(api_key=api_key)
            full_prompt = f"{effective_system_prompt}\n\nЗАДАЧА:\n{prompt}\n\nВерни только валидный JSON."
            
            try:
                model = genai.GenerativeModel(model_name=model_name)
                response = model.generate_content(full_prompt)
            except TypeError:
                # Фоллбэк для старых версий либы
                model = genai.GenerativeModel(model_name=model_name)
                response = model.generate_content(full_prompt)

            text = getattr(response, "text", None)
            if not text:
                raise RuntimeError("Empty response from Gemini")
            response_text = str(text).strip()

            # Чистка markdown оберток ```json
            response_text = re.sub(r"^```json", "", response_text, flags=re.MULTILINE)
            response_text = re.sub(r"^```", "", response_text, flags=re.MULTILINE)
            response_text = re.sub(r"```$", "", response_text, flags=re.MULTILINE).strip()

        except Exception as exc:
            raise RuntimeError(f"Gemini error: {exc}") from exc

    # --- 3. Парсинг JSON ---
    try:
        data = json.loads(response_text)
        return {
            "seo_title": data.get("seo_title", "Auto Title"),
            "seo_description": data.get("seo_description", ""),
            "focus_keyword": data.get("focus_keyword", ""),
            "html_content": data.get("html_content", "") or data.get("content", ""),
        }
    except json.JSONDecodeError:
        # Если JSON сломался, возвращаем текст как есть
        return {
            "seo_title": "Error Parsing JSON",
            "seo_description": "",
            "focus_keyword": "",
            "html_content": response_text,
        }


def build_article_system_prompt(settings: Dict[str, object], *, seed: str) -> str:
    """
    Собирает итоговый system prompt из базового (settings.article_system_prompt или SYSTEM_PROMPT)
    плюс блок настроек стиля/формата/языка/объёма.
    """
    base = (str(settings.get("article_system_prompt", "")) or "").strip() or SYSTEM_PROMPT
    profile = resolve_profile(settings, seed=seed)
    return f"{base}\n\n{profile.prompt_block()}\n"
