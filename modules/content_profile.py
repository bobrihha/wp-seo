from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Dict, List, Optional


LANGUAGES: Dict[str, str] = {
    "ru": "русский",
    "en": "английский",
}

STYLE_PRESETS: Dict[str, str] = {
    "entertainment": "развлекательный, лёгкий, вовлекающий",
    "author": "авторский, с личными наблюдениями (без выдуманных фактов)",
    "professional": "профессиональный, экспертный, чёткий и практичный",
    "thematic": "тематический, сфокусированный на узкой нише",
    "random": "случайный стиль (выбери сам уместный под тему)",
}

FORMAT_PRESETS: Dict[str, str] = {
    "article": "полноценная статья (структурно, с выводами)",
    "post": "пост (короче, динамичнее, меньше воды)",
    "pr": "PR-материал (презентация ценности, без агрессивных обещаний)",
    "press_release": "пресс-релиз (нейтрально, факты, анонсы, цитаты по желанию)",
    "release_notes": "релиз/обновление (что нового, кому полезно, как использовать)",
    "random": "случайный формат (выбери сам уместный под тему)",
}

MOOD_PRESETS: Dict[str, str] = {
    "neutral": "нейтральное, спокойное",
    "serious": "серьёзное, без шуток и сленга",
    "humor": "с лёгким уместным юмором (без кринжа и токсичности)",
    "playful": "игровое, дружелюбное, но без панибратства",
    "random": "случайное настроение (выбери сам уместное под тему)",
}


def _stable_pick(options: List[str], *, seed: str) -> str:
    if not options:
        raise ValueError("options is empty")
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    idx = int(digest[:8], 16) % len(options)
    return options[idx]


def _normalize_choice(value: Optional[str], *, allowed: List[str], default: str) -> str:
    v = (value or "").strip()
    if not v:
        return default
    return v if v in allowed else default


@dataclass(frozen=True)
class ContentProfile:
    language: str
    style: str
    content_format: str
    mood: str
    target_length_chars: Optional[int]
    headings_h2_count: Optional[int]
    headings_h3_count: Optional[int]

    def prompt_block(self) -> str:
        language_name = LANGUAGES.get(self.language, self.language)
        style_desc = STYLE_PRESETS.get(self.style, self.style)
        format_desc = FORMAT_PRESETS.get(self.content_format, self.content_format)
        mood_desc = MOOD_PRESETS.get(self.mood, self.mood)

        lines: List[str] = [
            "### НАСТРОЙКИ СТИЛЯ И ФОРМАТА:",
            f"- Язык: {language_name}",
            f"- Стиль: {style_desc}",
            f"- Формат: {format_desc}",
            f"- Настроение автора: {mood_desc}",
        ]

        if self.target_length_chars and self.target_length_chars > 0:
            lines.append(f"- Примерная длина: ~{int(self.target_length_chars)} знаков (с пробелами), допускается ±20%")
        if (self.headings_h2_count and self.headings_h2_count > 0) or (
            self.headings_h3_count and self.headings_h3_count > 0
        ):
            h2 = int(self.headings_h2_count or 0)
            h3 = int(self.headings_h3_count or 0)
            lines.append(f"- Заголовки: примерно <h2> × {h2} и <h3> × {h3} (допускается ±1)")

        lines.append("Соблюдай эти настройки, но не в ущерб фактической точности и читабельности.")
        return "\n".join(lines).strip()


def resolve_profile(settings: Dict[str, object], *, seed: str) -> ContentProfile:
    language = _normalize_choice(
        str(settings.get("site_language", "ru")) if settings.get("site_language") is not None else "ru",
        allowed=list(LANGUAGES.keys()),
        default="ru",
    )

    style = _normalize_choice(
        str(settings.get("content_style", "professional")),
        allowed=list(STYLE_PRESETS.keys()),
        default="professional",
    )
    content_format = _normalize_choice(
        str(settings.get("content_format", "article")),
        allowed=list(FORMAT_PRESETS.keys()),
        default="article",
    )
    mood = _normalize_choice(
        str(settings.get("author_mood", "neutral")),
        allowed=list(MOOD_PRESETS.keys()),
        default="neutral",
    )

    style_choices = [k for k in STYLE_PRESETS.keys() if k != "random"]
    format_choices = [k for k in FORMAT_PRESETS.keys() if k != "random"]
    mood_choices = [k for k in MOOD_PRESETS.keys() if k != "random"]

    if style == "random":
        style = _stable_pick(style_choices, seed=f"{seed}|style")
    if content_format == "random":
        content_format = _stable_pick(format_choices, seed=f"{seed}|format")
    if mood == "random":
        mood = _stable_pick(mood_choices, seed=f"{seed}|mood")

    def _to_opt_int(key: str) -> Optional[int]:
        raw = settings.get(key)
        if raw is None:
            return None
        try:
            value = int(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    return ContentProfile(
        language=language,
        style=style,
        content_format=content_format,
        mood=mood,
        target_length_chars=_to_opt_int("target_length_chars"),
        headings_h2_count=_to_opt_int("headings_h2_count"),
        headings_h3_count=_to_opt_int("headings_h3_count"),
    )
