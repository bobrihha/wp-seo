import streamlit as st

from typing import Optional

from utils.config_manager import load_settings
from utils.config_manager import save_settings
from utils.database import mark_url_processed

from modules.wp_publisher import publish_to_wordpress
from modules.ai_engine import build_article_system_prompt, generate_article, SYSTEM_PROMPT, inject_ad_block
from modules.image_generator import DEFAULT_IMAGE_PROMPT_TEMPLATE, build_image_prompt, generate_cover_image
from modules.rss_parser import fetch_latest_rss_items
from modules.tg_auth import run_async as run_async_tg
from modules.tg_auth import is_authorized as tg_is_authorized
from modules.tg_auth import send_login_code as tg_send_login_code
from modules.tg_auth import sign_in_with_code as tg_sign_in_with_code
from modules.tg_auth import sign_in_with_password as tg_sign_in_with_password
from modules.tg_parser import fetch_latest_channel_posts
from modules.youtube_parser import process_youtube_video


def main() -> None:
    st.set_page_config(page_title="AI Content Hub", layout="wide")
    st.title("AI Content Hub")

    settings = load_settings()

    if "rss_items" not in st.session_state:
        st.session_state["rss_items"] = []
    if "tg_posts" not in st.session_state:
        st.session_state["tg_posts"] = []
    if "generated_articles" not in st.session_state:
        st.session_state["generated_articles"] = []

    def _upsert_generated_article(
        *, source_url: str, source_type: str, article_data: dict, cover_preview_bytes: Optional[bytes] = None
    ) -> None:
        generated = st.session_state.get("generated_articles", [])
        for item in generated:
            if item.get("source_url") == source_url and item.get("source_type") == source_type:
                item["article_data"] = article_data
                if cover_preview_bytes is not None:
                    item["cover_preview_bytes"] = cover_preview_bytes
                return
        generated.append(
            {
                "source_url": source_url,
                "source_type": source_type,
                "article_data": article_data,
                "published_link": None,
                "cover_preview_bytes": cover_preview_bytes,
            }
        )

    def _resolve_image_provider_settings() -> dict:
        provider = (settings.get("image_provider") or "openai").strip()
        base_url = (settings.get("image_base_url") or settings.get("base_url") or "").strip() or None
        model_name = (settings.get("image_model_name") or "").strip()
        size = (settings.get("image_size") or "1024x1024").strip()

        api_key = ""
        if provider == "openai":
            api_key = (
                (settings.get("openai_image_api_key") or "").strip()
                or (settings.get("image_api_key") or "").strip()
                or (settings.get("openai_api_key") or "").strip()
            )
        elif provider == "flux":
            api_key = (settings.get("flux_image_api_key") or "").strip()

        gcp_project_id = (settings.get("gcp_project_id") or "").strip() or None
        gcp_location = (settings.get("gcp_location") or "us-central1").strip() or "us-central1"
        gcp_credentials_path = (settings.get("gcp_credentials_path") or "").strip() or None

        return {
            "provider": provider,
            "api_key": api_key,
            "base_url": base_url,
            "model_name": model_name,
            "size": size,
            "gcp_project_id": gcp_project_id,
            "gcp_location": gcp_location,
            "gcp_credentials_path": gcp_credentials_path,
        }

    def _maybe_generate_cover_preview(article_data: dict, *, seed: str) -> Optional[bytes]:
        if not bool(settings.get("image_enabled", True)):
            return None
        if not bool(settings.get("image_show_preview", False)):
            return None
        try:
            img_settings = _resolve_image_provider_settings()
            template = settings.get("image_prompt_template") if settings.get("image_prompt_use_custom") else None
            prompt = build_image_prompt(article_data, template=template)
            image_bytes, _filename = generate_cover_image(
                provider=img_settings["provider"],
                api_key=img_settings["api_key"],
                base_url=img_settings["base_url"],
                model_name=img_settings["model_name"],
                size=img_settings["size"],
                force_aspect_crop=bool(settings.get("image_force_aspect_crop", False)),
                prompt=prompt,
                gcp_project_id=img_settings["gcp_project_id"],
                gcp_location=img_settings["gcp_location"],
                gcp_credentials_path=img_settings["gcp_credentials_path"],
            )
            return image_bytes
        except Exception:
            return None

    def display_and_publish(article_data: dict, *, source_url: str, source_type: str) -> None:
        seo_title = (article_data.get("seo_title") or "").strip()
        seo_description = (article_data.get("seo_description") or "").strip()
        focus_keyword = (article_data.get("focus_keyword") or "").strip()
        html_content = article_data.get("html_content") or ""
        wp_post_status = (settings.get("wp_post_status") or "draft").strip().lower()
        publish_label = "Опубликовать в WordPress (сразу)" if wp_post_status == "publish" else "Отправить в WordPress (черновик)"

        with st.expander(seo_title or "Без заголовка", expanded=True):
            for item in st.session_state.get("generated_articles", []):
                if item.get("source_url") == source_url and item.get("source_type") == source_type:
                    preview_bytes = item.get("cover_preview_bytes")
                    if preview_bytes:
                        st.image(preview_bytes, caption="Превью обложки", use_container_width=True)
                    break

            c1, c2, c3 = st.columns(3)
            c1.write(f"Focus keyword: {focus_keyword}")
            c2.write(f"SEO title: {seo_title}")
            c3.write(f"SEO description: {seo_description}")
            st.markdown(html_content, unsafe_allow_html=True)

            if st.button(
                publish_label,
                key=f"publish::{source_type}::{source_url}",
            ):
                try:
                    link = publish_to_wordpress(settings, article_data)
                    st.success(f"Опубликовано: {link}")
                    for item in st.session_state.get("generated_articles", []):
                        if item.get("source_url") == source_url and item.get("source_type") == source_type:
                            item["published_link"] = link
                            break
                    mark_url_processed(
                        source_url,
                        source=source_type,
                        title=seo_title or None,
                        status="published" if wp_post_status == "publish" else "draft",
                    )
                except Exception as exc:
                    st.error(f"Ошибка публикации: {exc}")

            for item in st.session_state.get("generated_articles", []):
                if item.get("source_url") == source_url and item.get("source_type") == source_type:
                    if item.get("published_link"):
                        st.caption(f"WP link: {item['published_link']}")
                    break

    with st.sidebar:
        tab_settings, tab_sources, tab_generator = st.tabs(
            ["Настройки", "Управление источниками", "Генератор"]
        )

        with tab_settings:
            tab_keys, tab_images, tab_other = st.tabs(["Ключи", "Изображения", "Настройки"])

            with tab_keys:
                st.subheader("WordPress")
                wp_url = st.text_input("Сайт (URL)", value=settings.get("wp_url", ""))
                wp_user = st.text_input("Логин WP", value=settings.get("wp_user", ""))
                wp_password = st.text_input(
                    "Пароль приложения WP",
                    type="password",
                    value=settings.get("wp_password", ""),
                    help="WP → Пользователи → Профиль → Пароли приложений",
                )
                wp_post_status = st.selectbox(
                    "Статус записи в WordPress",
                    options=["draft", "publish"],
                    index=["draft", "publish"].index(
                        settings.get("wp_post_status", "draft")
                        if settings.get("wp_post_status", "draft") in {"draft", "publish"}
                        else "draft"
                    ),
                    format_func=lambda v: {"draft": "Черновик", "publish": "Опубликовать сразу"}.get(v, v),
                )
                st.divider()

                st.subheader("AI (OpenAI-compatible) — текст")
                openai_api_key = st.text_input(
                    "API Key",
                    value=settings.get("openai_api_key", ""),
                    type="password",
                )
                base_url = st.text_input(
                    "Base URL",
                    value=settings.get("base_url", "https://api.openai.com/v1"),
                )
                model_name = st.text_input(
                    "Model",
                    value=settings.get("model_name", "gpt-4o"),
                )
                st.divider()

                st.subheader("AI (Gemini) — ключи (опционально)")
                gemini_api_key = st.text_input(
                    "Gemini API Key",
                    value=settings.get("gemini_api_key", ""),
                    type="password",
                )
                gemini_model_name = st.text_input(
                    "Gemini model (для текста, если используете)",
                    value=settings.get("gemini_model_name", ""),
                    placeholder="например: gemini-1.5-pro",
                )
                st.divider()

                st.subheader("Ключи генерации изображений")
                st.caption("Можно заполнить все сразу — потом просто переключать модель в вкладке «Изображения».")
                openai_image_api_key = st.text_input(
                    "OpenAI Images API Key (если пусто — используем общий OpenAI API Key)",
                    value=settings.get("openai_image_api_key", settings.get("image_api_key", "")),
                    type="password",
                )
                image_base_url = st.text_input(
                    "OpenAI Images Base URL",
                    value=settings.get("image_base_url", settings.get("base_url", "https://api.openai.com/v1")),
                )
                st.caption("Google Vertex Imagen: положи JSON ключ на диск и укажи путь (файл не должен попадать в git).")
                gcp_project_id = st.text_input("GCP project id", value=settings.get("gcp_project_id", ""))
                gcp_location = st.text_input("GCP location", value=settings.get("gcp_location", "us-central1"))
                gcp_credentials_path = st.text_input(
                    "Path to service account JSON",
                    value=settings.get("gcp_credentials_path", ""),
                    placeholder="/path/to/service-account.json",
                )
                flux_image_api_key = st.text_input(
                    "Flux API Key (на будущее)",
                    value=settings.get("flux_image_api_key", ""),
                    type="password",
                )
                flux_image_base_url = st.text_input(
                    "Flux Base URL (на будущее)",
                    value=settings.get("flux_image_base_url", ""),
                    placeholder="https://...",
                )
                st.divider()

                st.subheader("Telegram (Telethon)")
                telegram_api_id = st.text_input(
                    "Telegram API ID",
                    value=str(settings.get("telegram_api_id", "")),
                    help="Число (api_id) из my.telegram.org",
                )
                telegram_api_hash = st.text_input(
                    "Telegram API Hash",
                    value=settings.get("telegram_api_hash", ""),
                    type="password",
                )
                telegram_session_path = st.text_input(
                    "Telegram session path",
                    value=settings.get("telegram_session_path", "secrets/telethon.session"),
                    help="Файл сессии будет создан автоматически после авторизации.",
                )

            with tab_images:
                st.subheader("Генерация изображений")
                image_enabled = st.checkbox(
                    "Генерировать и загружать обложку",
                    value=bool(settings.get("image_enabled", True)),
                )
                image_provider = st.selectbox(
                    "Модель/провайдер генерации",
                    options=["openai", "vertex_imagen", "flux"],
                    index=["openai", "vertex_imagen", "flux"].index(
                        settings.get("image_provider", "openai")
                        if settings.get("image_provider", "openai") in {"openai", "vertex_imagen", "flux"}
                        else "openai"
                    ),
                    format_func=lambda v: {
                        "openai": "DALL·E / OpenAI Images",
                        "vertex_imagen": "Google Vertex Imagen",
                        "flux": "Flux (в разработке)",
                    }.get(v, v),
                )
                image_model_name = st.text_input(
                    "Image model",
                    value=settings.get("image_model_name", "gpt-image-1"),
                    help="Для OpenAI: gpt-image-1 или dall-e-3; для Vertex: имя модели Imagen.",
                )
                image_size = st.selectbox(
                    "Размер изображений",
                    options=["1024x1024", "1024x1792", "1792x1024"],
                    index=["1024x1024", "1024x1792", "1792x1024"].index(
                        settings.get("image_size", "1024x1024")
                        if settings.get("image_size", "1024x1024") in {"1024x1024", "1024x1792", "1792x1024"}
                        else "1024x1024"
                    ),
                )
                image_show_preview = st.checkbox(
                    "Показывать превью обложки в интерфейсе (перед публикацией)",
                    value=bool(settings.get("image_show_preview", False)),
                )
                image_per_paragraph_enabled = st.checkbox(
                    "Добавлять изображения к параграфам (в WordPress при публикации)",
                    value=bool(settings.get("image_per_paragraph_enabled", False)),
                )
                image_per_paragraph_max = st.number_input(
                    "Максимум изображений для параграфов",
                    min_value=0,
                    value=int(settings.get("image_per_paragraph_max", 3) or 0),
                    step=1,
                    help="Чтобы не перегружать статью и не тратить лишние запросы к генератору.",
                )
                image_force_aspect_crop = st.checkbox(
                    "Если провайдер вернул квадрат — обрезать до выбранного формата (не рекомендуется)",
                    value=bool(settings.get("image_force_aspect_crop", False)),
                    help="Лучше добиться нужного формата на стороне модели. Кроп может обрезать лица/объекты.",
                )
                st.divider()
                st.subheader("Промпт изображений")
                st.session_state.setdefault(
                    "image_prompt_use_custom",
                    bool(settings.get("image_prompt_use_custom", False)),
                )
                st.session_state.setdefault(
                    "image_prompt_template",
                    (settings.get("image_prompt_template") or "").strip(),
                )

                image_prompt_use_custom = st.checkbox(
                    "Использовать свой промпт",
                    key="image_prompt_use_custom",
                )
                if st.button("Вставить дефолт", use_container_width=True, key="image_prompt_insert_default"):
                    st.session_state["image_prompt_use_custom"] = True
                    st.session_state["image_prompt_template"] = DEFAULT_IMAGE_PROMPT_TEMPLATE
                    st.rerun()

                if image_prompt_use_custom:
                    st.text_area(
                        "Промпт для изображений (обложка/параграфы)",
                        key="image_prompt_template",
                        height=160,
                        help="Плейсхолдеры: {title}, {keyword}.",
                    )
                else:
                    st.text_area(
                        "Дефолтный промпт (read-only)",
                        value=DEFAULT_IMAGE_PROMPT_TEMPLATE,
                        height=140,
                        disabled=True,
                    )

            with tab_other:
                st.subheader("Контент (язык/стиль/объём)")
                site_language = st.selectbox(
                    "Язык статьи",
                    options=["ru", "en"],
                    index=["ru", "en"].index(
                        settings.get("site_language", "ru")
                        if settings.get("site_language", "ru") in {"ru", "en"}
                        else "ru"
                    ),
                    format_func=lambda v: {"ru": "Русский", "en": "English"}.get(v, v),
                )
                content_style = st.selectbox(
                    "Стиль",
                    options=["professional", "entertainment", "author", "thematic", "random"],
                    index=["professional", "entertainment", "author", "thematic", "random"].index(
                        settings.get("content_style", "professional")
                        if settings.get("content_style", "professional")
                        in {"professional", "entertainment", "author", "thematic", "random"}
                        else "professional"
                    ),
                    format_func=lambda v: {
                        "professional": "Профессиональная",
                        "entertainment": "Развлекательная",
                        "author": "Авторская",
                        "thematic": "Тематическая",
                        "random": "Случайная",
                    }.get(v, v),
                )
                content_format = st.selectbox(
                    "Формат материала",
                    options=["article", "post", "pr", "press_release", "release_notes", "random"],
                    index=["article", "post", "pr", "press_release", "release_notes", "random"].index(
                        settings.get("content_format", "article")
                        if settings.get("content_format", "article")
                        in {"article", "post", "pr", "press_release", "release_notes", "random"}
                        else "article"
                    ),
                    format_func=lambda v: {
                        "article": "Статья",
                        "post": "Пост",
                        "pr": "Пиар/PR",
                        "press_release": "Пресс-релиз",
                        "release_notes": "Релиз/обновление",
                        "random": "Случайный",
                    }.get(v, v),
                )
                author_mood = st.selectbox(
                    "Настроение автора",
                    options=["neutral", "serious", "humor", "playful", "random"],
                    index=["neutral", "serious", "humor", "playful", "random"].index(
                        settings.get("author_mood", "neutral")
                        if settings.get("author_mood", "neutral")
                        in {"neutral", "serious", "humor", "playful", "random"}
                        else "neutral"
                    ),
                    format_func=lambda v: {
                        "neutral": "Нейтральное",
                        "serious": "Серьёзное",
                        "humor": "С юмором",
                        "playful": "Игровое/лёгкое",
                        "random": "Случайное",
                    }.get(v, v),
                )
                target_length_chars = st.number_input(
                    "Примерная длина (знаков, с пробелами)",
                    min_value=0,
                    value=int(settings.get("target_length_chars", 6000) or 0),
                    step=500,
                )
                headings_h2_count = st.number_input(
                    "Количество заголовков H2 (примерно)",
                    min_value=0,
                    value=int(settings.get("headings_h2_count", 4) or 0),
                    step=1,
                )
                headings_h3_count = st.number_input(
                    "Количество заголовков H3 (примерно)",
                    min_value=0,
                    value=int(settings.get("headings_h3_count", 6) or 0),
                    step=1,
                )
                st.caption(
                    "Если выбран «Случайный» стиль/формат/настроение — вариант выбирается от ссылки, без «прыжков» при повторной генерации."
                )

                st.subheader("YouTube настройки")
                youtube_embed_enabled = st.checkbox(
                    "Встраивать видео (embed) в начало статьи",
                    value=bool(settings.get("youtube_embed_enabled", True)),
                )

                st.subheader("Реклама (Ad Injection)")
                ad_code = st.text_area(
                    "HTML-код рекламы (AdSense / Яндекс)",
                    value=settings.get("ad_code", ""),
                    height=100,
                    help="Оставьте пустым, если реклама не нужна.",
                )
                ad_paragraph = st.number_input(
                    "Вставлять после параграфа №",
                    min_value=1,
                    value=int(settings.get("ad_paragraph", 3)),
                    help="3 означает: реклама будет после 3-го абзаца текста.",
                )

                st.subheader("Промпт статьи")
                article_system_prompt = st.text_area(
                    "System prompt (JSON + HTML + классы)",
                    value=(settings.get("article_system_prompt") or "").strip() or SYSTEM_PROMPT,
                    height=260,
                )

            with st.expander("Telegram авторизация (первый запуск)", expanded=False):
                col_a, col_b = st.columns([1, 1])
                try:
                    authorized = run_async_tg(tg_is_authorized(settings))
                except Exception:
                    authorized = False
                col_a.write(f"Статус: {'авторизован' if authorized else 'не авторизован'}")

                phone = st.text_input(
                    "Телефон (или bot token)",
                    value=st.session_state.get("tg_phone", ""),
                    placeholder="+7XXXXXXXXXX",
                )
                if st.button("Отправить код", key="tg_send_code"):
                    try:
                        settings["telegram_session_path"] = telegram_session_path.strip() or "secrets/telethon.session"
                        save_settings(settings)
                        phone_code_hash = run_async_tg(tg_send_login_code(settings, phone))
                        st.session_state["tg_phone"] = phone.strip()
                        st.session_state["tg_phone_code_hash"] = phone_code_hash
                        st.success("Код отправлен. Введите его ниже.")
                    except Exception as exc:
                        st.error(str(exc))

                code = st.text_input("Код из Telegram", value="", key="tg_code")
                password = st.text_input("Пароль 2FA (если включён)", value="", type="password", key="tg_2fa")

                if st.button("Войти", key="tg_sign_in"):
                    try:
                        settings["telegram_session_path"] = telegram_session_path.strip() or "secrets/telethon.session"
                        save_settings(settings)
                        ok, next_step = run_async_tg(
                            tg_sign_in_with_code(
                                settings,
                                phone=st.session_state.get("tg_phone", phone),
                                code=code,
                                phone_code_hash=st.session_state.get("tg_phone_code_hash", ""),
                            )
                        )
                        if ok:
                            st.success("Telegram авторизация успешна.")
                        elif next_step == "password":
                            if not password:
                                st.warning("Нужен пароль 2FA. Введите пароль и нажмите «Войти» ещё раз.")
                            else:
                                ok2 = run_async_tg(tg_sign_in_with_password(settings, password=password))
                                if ok2:
                                    st.success("Telegram авторизация успешна (2FA).")
                                else:
                                    st.error("Не удалось авторизоваться (2FA).")
                    except Exception as exc:
                        st.error(str(exc))

            if st.button("Сохранить", use_container_width=True):
                settings["wp_url"] = wp_url.strip()
                settings["wp_user"] = wp_user.strip()
                settings["wp_password"] = wp_password.strip()
                settings["wp_post_status"] = wp_post_status
                settings["openai_api_key"] = openai_api_key.strip()
                settings["base_url"] = base_url.strip() or "https://api.openai.com/v1"
                settings["model_name"] = model_name.strip() or "gpt-4o"
                settings["gemini_api_key"] = gemini_api_key.strip()
                settings["gemini_model_name"] = gemini_model_name.strip()
                settings["article_system_prompt"] = article_system_prompt.strip()
                settings["site_language"] = site_language
                settings["content_style"] = content_style
                settings["content_format"] = content_format
                settings["author_mood"] = author_mood
                settings["target_length_chars"] = int(target_length_chars)
                settings["headings_h2_count"] = int(headings_h2_count)
                settings["headings_h3_count"] = int(headings_h3_count)
                settings["image_enabled"] = bool(image_enabled)
                settings["image_provider"] = image_provider
                settings["openai_image_api_key"] = openai_image_api_key.strip()
                settings["image_api_key"] = openai_image_api_key.strip()
                settings["image_base_url"] = image_base_url.strip() or settings["base_url"]
                settings["image_model_name"] = image_model_name.strip() or "gpt-image-1"
                settings["image_size"] = image_size
                settings["image_show_preview"] = bool(image_show_preview)
                settings["image_per_paragraph_enabled"] = bool(image_per_paragraph_enabled)
                settings["image_per_paragraph_max"] = int(image_per_paragraph_max)
                settings["image_force_aspect_crop"] = bool(image_force_aspect_crop)
                settings["image_prompt_use_custom"] = bool(st.session_state.get("image_prompt_use_custom", False))
                settings["image_prompt_template"] = (
                    (st.session_state.get("image_prompt_template", "") or "").strip()
                    if settings["image_prompt_use_custom"]
                    else ""
                )
                settings["gcp_project_id"] = gcp_project_id.strip()
                settings["gcp_location"] = gcp_location.strip() or "us-central1"
                settings["gcp_credentials_path"] = gcp_credentials_path.strip()
                settings["flux_image_api_key"] = flux_image_api_key.strip()
                settings["flux_image_base_url"] = flux_image_base_url.strip()
                settings["telegram_api_id"] = telegram_api_id.strip()
                settings["telegram_api_hash"] = telegram_api_hash.strip()
                settings["telegram_session_path"] = telegram_session_path.strip() or "secrets/telethon.session"
                settings["ad_code"] = ad_code.strip()
                settings["ad_paragraph"] = int(ad_paragraph)
                settings["youtube_embed_enabled"] = bool(youtube_embed_enabled)
                save_settings(settings)
                st.success("Настройки сохранены.")

        with tab_sources:
            st.subheader("RSS-ленты")
            rss_text = st.text_area(
                "Список RSS (по одному URL на строку)",
                value="\n".join(settings.get("rss_sources", [])),
                height=140,
            )

            st.subheader("Telegram-каналы")
            tg_text = st.text_area(
                "Список каналов (по одному username на строку, можно с @)",
                value="\n".join(settings.get("telegram_channels", [])),
                height=140,
            )

            if st.button("Сохранить источники", use_container_width=True):
                rss_sources = [line.strip() for line in rss_text.splitlines() if line.strip()]
                telegram_channels = [line.strip() for line in tg_text.splitlines() if line.strip()]
                settings["rss_sources"] = rss_sources
                settings["telegram_channels"] = telegram_channels
                save_settings(settings)
                st.success("Источники сохранены.")

        with tab_generator:
            mode = st.radio(
                "Режим",
                options=["YouTube", "RSS", "Telegram"],
                horizontal=False,
            )
            st.caption("Генерация: JSON (SEO + HTML). Язык/стиль/объём задаются в «Настройки» → «Контент».")

    if mode == "YouTube":
        st.header("YouTube → Статья")
        url = st.text_input("Ссылка на YouTube-видео", placeholder="https://www.youtube.com/watch?v=...")
        if st.button("Start", type="primary"):
            try:
                article_data = process_youtube_video(url, settings)

                # Вставка рекламы (если настроена)
                ad_c = settings.get("ad_code", "")
                if ad_c and article_data.get("html_content"):
                    article_data["html_content"] = inject_ad_block(
                        article_data["html_content"],
                        ad_c,
                        int(settings.get("ad_paragraph", 3))
                    )

                mark_url_processed(url, source="youtube", title=article_data.get("seo_title"), status="generated")
                cover_preview = _maybe_generate_cover_preview(article_data, seed=url)
                _upsert_generated_article(
                    source_url=url, source_type="youtube", article_data=article_data, cover_preview_bytes=cover_preview
                )
            except Exception as exc:
                st.error(str(exc))

    elif mode == "RSS":
        st.header("RSS → Выбор → Генерация")
        if st.button("Проверить ленты", type="primary"):
            try:
                st.session_state["rss_items"] = fetch_latest_rss_items(settings.get("rss_sources", []))
                if not st.session_state["rss_items"]:
                    st.info("Новых новостей не найдено (или все уже обработаны).")
            except Exception as exc:
                st.error(str(exc))

        rss_items = st.session_state.get("rss_items", [])
        if rss_items:
            st.subheader("Новости")
            selected_links = []
            for i, item in enumerate(rss_items):
                label = f"{item.title or '(без заголовка)'} — {item.link}"
                if st.checkbox(label, key=f"rss_item_{i}"):
                    selected_links.append(item)

            if st.button("Генерировать выбранное"):
                for item in selected_links:
                    try:
                        prompt = (
                            "Напиши статью на русском языке по новости из RSS.\n\n"
                            f"Заголовок: {item.title}\n"
                            f"Источник: {item.source}\n"
                            f"Ссылка: {item.link}\n\n"
                            f"Краткое описание/анонс:\n{item.summary or ''}"
                        )
                        article_data = generate_article(
                            prompt=prompt,
                            provider="openai",
                            api_key=settings.get("openai_api_key", ""),
                            base_url=settings.get("base_url"),
                            model_name=settings.get("model_name", "gpt-4o"),
                            system_prompt=build_article_system_prompt(settings, seed=item.link),
                        )


                        # Вставка рекламы
                        ad_c = settings.get("ad_code", "")
                        if ad_c and article_data.get("html_content"):
                            article_data["html_content"] = inject_ad_block(
                                article_data["html_content"],
                                ad_c,
                                int(settings.get("ad_paragraph", 3))
                            )

                        mark_url_processed(
                            item.link,
                            source="rss",
                            title=article_data.get("seo_title") or item.title,
                            status="generated",
                        )
                        cover_preview = _maybe_generate_cover_preview(article_data, seed=item.link)
                        _upsert_generated_article(
                            source_url=item.link,
                            source_type="rss",
                            article_data=article_data,
                            cover_preview_bytes=cover_preview,
                        )
                    except Exception as exc:
                        st.error(f"{item.link}: {exc}")

    else:
        st.header("Telegram → Выбор → Генерация")
        channels = settings.get("telegram_channels", [])
        if channels:
            channel = st.selectbox("Канал", options=channels)
        else:
            channel = st.text_input("Канал (username)", placeholder="@channel_username")

        if st.button("Получить посты", type="primary"):
            try:
                st.session_state["tg_posts"] = fetch_latest_channel_posts(channel, settings, limit=3)
                if not st.session_state["tg_posts"]:
                    st.info("Новых постов не найдено (или все уже обработаны).")
            except Exception as exc:
                st.error(str(exc))

        tg_posts = st.session_state.get("tg_posts", [])
        if tg_posts:
            st.subheader("Посты")
            selected_posts = []
            for i, post in enumerate(tg_posts):
                preview = post.text.replace("\n", " ")
                if len(preview) > 120:
                    preview = preview[:120] + "…"
                label = f"{post.url} — {preview}"
                if st.checkbox(label, key=f"tg_post_{i}"):
                    selected_posts.append(post)

            if st.button("Генерировать выбранное"):
                for post in selected_posts:
                    try:
                        prompt = (
                            "Сгенерируй статью по посту из Telegram-канала. "
                            "Сохрани смысл, оформи как полноценную статью.\n\n"
                            f"Ссылка: {post.url}\n\n"
                            f"Текст поста:\n{post.text}"
                        )
                        article_data = generate_article(
                            prompt=prompt,
                            provider="openai",
                            api_key=settings.get("openai_api_key", ""),
                            base_url=settings.get("base_url"),
                            model_name=settings.get("model_name", "gpt-4o"),
                            system_prompt=build_article_system_prompt(settings, seed=post.url),
                        )


                        # Вставка рекламы
                        ad_c = settings.get("ad_code", "")
                        if ad_c and article_data.get("html_content"):
                            article_data["html_content"] = inject_ad_block(
                                article_data["html_content"],
                                ad_c,
                                int(settings.get("ad_paragraph", 3))
                            )

                        mark_url_processed(
                            post.url,
                            source="telegram",
                            title=article_data.get("seo_title"),
                            status="generated",
                        )
                        cover_preview = _maybe_generate_cover_preview(article_data, seed=post.url)
                        _upsert_generated_article(
                            source_url=post.url,
                            source_type="telegram",
                            article_data=article_data,
                            cover_preview_bytes=cover_preview,
                        )
                    except Exception as exc:
                        st.error(f"{post.url}: {exc}")

    generated = st.session_state.get("generated_articles", [])
    if generated:
        st.divider()
        st.header("Сгенерированные статьи")
        for item in reversed(generated):
            display_and_publish(
                item.get("article_data", {}) or {},
                source_url=item.get("source_url", ""),
                source_type=item.get("source_type", "unknown"),
            )


if __name__ == "__main__":
    main()
