import streamlit as st

from utils.config_manager import load_settings
from utils.config_manager import save_settings
from utils.database import mark_url_processed

from modules.wp_publisher import publish_to_wordpress
from modules.ai_engine import generate_article
from modules.rss_parser import fetch_latest_rss_items
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

    def _upsert_generated_article(*, source_url: str, source_type: str, article_data: dict) -> None:
        generated = st.session_state.get("generated_articles", [])
        for item in generated:
            if item.get("source_url") == source_url and item.get("source_type") == source_type:
                item["article_data"] = article_data
                return
        generated.append(
            {
                "source_url": source_url,
                "source_type": source_type,
                "article_data": article_data,
                "published_link": None,
            }
        )

    def display_and_publish(article_data: dict, *, source_url: str, source_type: str) -> None:
        seo_title = (article_data.get("seo_title") or "").strip()
        seo_description = (article_data.get("seo_description") or "").strip()
        focus_keyword = (article_data.get("focus_keyword") or "").strip()
        html_content = article_data.get("html_content") or ""

        with st.expander(seo_title or "Без заголовка", expanded=True):
            c1, c2, c3 = st.columns(3)
            c1.write(f"Focus keyword: {focus_keyword}")
            c2.write(f"SEO title: {seo_title}")
            c3.write(f"SEO description: {seo_description}")
            st.markdown(html_content, unsafe_allow_html=True)

            if st.button(
                "Опубликовать в WordPress (черновик)",
                key=f"publish::{source_type}::{source_url}",
            ):
                try:
                    link = publish_to_wordpress(settings, article_data)
                    st.success(f"Опубликовано: {link}")
                    for item in st.session_state.get("generated_articles", []):
                        if item.get("source_url") == source_url and item.get("source_type") == source_type:
                            item["published_link"] = link
                            break
                    mark_url_processed(source_url, source=source_type, title=seo_title or None, status="published")
                except Exception as exc:
                    st.error(f"Ошибка публикации: {exc}")

            for item in st.session_state.get("generated_articles", []):
                if item.get("source_url") == source_url and item.get("source_type") == source_type:
                    if item.get("published_link"):
                        st.caption(f"WP draft link: {item['published_link']}")
                    break

    with st.sidebar:
        tab_settings, tab_sources, tab_generator = st.tabs(
            ["Настройки", "Управление источниками", "Генератор"]
        )

        with tab_settings:
            st.subheader("WordPress")
            wp_url = st.text_input("Сайт (URL)", value=settings.get("wp_url", ""))
            wp_user = st.text_input("Логин WP", value=settings.get("wp_user", ""))
            wp_password = st.text_input(
                "Пароль приложения WP",
                type="password",
                value=settings.get("wp_password", ""),
                help="WP → Пользователи → Профиль → Пароли приложений",
            )
            st.divider()

            st.subheader("AI (OpenAI-compatible)")
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

            st.subheader("Изображения (обложка)")
            image_enabled = st.checkbox(
                "Генерировать и загружать обложку",
                value=bool(settings.get("image_enabled", True)),
            )
            image_api_key = st.text_input(
                "Image API Key (если пусто — используем основной API Key выше)",
                value=settings.get("image_api_key", ""),
                type="password",
            )
            image_base_url = st.text_input(
                "Image Base URL",
                value=settings.get("image_base_url", settings.get("base_url", "https://api.openai.com/v1")),
            )
            image_model_name = st.text_input(
                "Image Model",
                value=settings.get("image_model_name", "gpt-image-1"),
            )
            image_size = st.selectbox(
                "Image size",
                options=["1024x1024", "1024x1792", "1792x1024"],
                index=["1024x1024", "1024x1792", "1792x1024"].index(
                    settings.get("image_size", "1024x1024")
                    if settings.get("image_size", "1024x1024") in {"1024x1024", "1024x1792", "1792x1024"}
                    else "1024x1024"
                ),
            )

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

            if st.button("Сохранить", use_container_width=True):
                settings["wp_url"] = wp_url.strip()
                settings["wp_user"] = wp_user.strip()
                settings["wp_password"] = wp_password.strip()
                settings["openai_api_key"] = openai_api_key.strip()
                settings["base_url"] = base_url.strip() or "https://api.openai.com/v1"
                settings["model_name"] = model_name.strip() or "gpt-4o"
                settings["image_enabled"] = bool(image_enabled)
                settings["image_provider"] = "openai"
                settings["image_api_key"] = image_api_key.strip()
                settings["image_base_url"] = image_base_url.strip() or settings["base_url"]
                settings["image_model_name"] = image_model_name.strip() or "gpt-image-1"
                settings["image_size"] = image_size
                settings["telegram_api_id"] = telegram_api_id.strip()
                settings["telegram_api_hash"] = telegram_api_hash.strip()
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
            st.caption("Генерация всегда идет на русском языке (JSON: SEO + HTML контент).")

    if mode == "YouTube":
        st.header("YouTube → Статья")
        url = st.text_input("Ссылка на YouTube-видео", placeholder="https://www.youtube.com/watch?v=...")
        if st.button("Start", type="primary"):
            try:
                article_data = process_youtube_video(url, settings)
                mark_url_processed(url, source="youtube", title=article_data.get("seo_title"), status="generated")
                _upsert_generated_article(source_url=url, source_type="youtube", article_data=article_data)
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
                        )
                        mark_url_processed(
                            item.link,
                            source="rss",
                            title=article_data.get("seo_title") or item.title,
                            status="generated",
                        )
                        _upsert_generated_article(source_url=item.link, source_type="rss", article_data=article_data)
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
                            "Сгенерируй статью на русском языке по посту из Telegram-канала. "
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
                        )
                        mark_url_processed(
                            post.url,
                            source="telegram",
                            title=article_data.get("seo_title"),
                            status="generated",
                        )
                        _upsert_generated_article(source_url=post.url, source_type="telegram", article_data=article_data)
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
