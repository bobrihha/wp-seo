from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from modules.ai_engine import build_article_system_prompt, generate_article, inject_ad_block
from modules.rss_parser import fetch_latest_rss_items
from modules.tg_parser import fetch_latest_channel_posts
from modules.wp_publisher import publish_to_wordpress
from modules.youtube_discovery import fetch_latest_channel_videos
from modules.youtube_parser import process_youtube_video
from utils.autopilot_lock import autopilot_lock
from utils.database import count_processed_today, is_url_processed, mark_url_processed


@dataclass(frozen=True)
class AutopilotResult:
    processed: int
    published: int
    drafted: int
    skipped: int
    errors: int
    details: List[str]


def _mode_to_wp_status(mode: str) -> Optional[str]:
    m = (mode or "").strip().lower()
    if m == "publish":
        return "publish"
    if m == "draft":
        return "draft"
    return None


def _get_int(settings: Dict[str, Any], key: str, default: int) -> int:
    raw = settings.get(key, default)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return int(default)


def run_autopilot_once(settings: Dict[str, Any], *, sources: Optional[List[str]] = None) -> AutopilotResult:
    """
    One-shot autopilot run: fetch fresh items, generate articles, and publish/draft according to per-source mode.
    This is safe to call from CLI or Streamlit (button).
    """
    enabled_global = bool(settings.get("autopilot_enabled", False))
    if not enabled_global and sources is None:
        return AutopilotResult(0, 0, 0, 0, 0, ["Autopilot is disabled (autopilot_enabled=false)."])

    rss_enabled = bool(settings.get("autopilot_rss_enabled", True))
    yt_enabled = bool(settings.get("autopilot_youtube_enabled", False))
    tg_enabled = bool(settings.get("autopilot_telegram_enabled", False))

    rss_mode = str(settings.get("autopilot_rss_mode", "draft"))
    yt_mode = str(settings.get("autopilot_youtube_mode", "draft"))
    tg_mode = str(settings.get("autopilot_telegram_mode", "draft"))

    max_per_run = max(0, _get_int(settings, "autopilot_max_per_run", 3))
    daily_limit_total = max(0, _get_int(settings, "autopilot_daily_limit_total", 10))

    # Determine which sources to run
    selected = set(sources or [])
    if not selected:
        if rss_enabled:
            selected.add("rss")
        if yt_enabled:
            selected.add("youtube")
        if tg_enabled:
            selected.add("telegram")

    wp_status_for_source: Dict[str, Optional[str]] = {
        "rss": _mode_to_wp_status(rss_mode),
        "youtube": _mode_to_wp_status(yt_mode),
        "telegram": _mode_to_wp_status(tg_mode),
    }

    # If a source is selected but mode is off -> skip it.
    selected = {s for s in selected if wp_status_for_source.get(s) is not None}
    if not selected:
        return AutopilotResult(0, 0, 0, 0, 0, ["No sources selected or all sources are set to off."])

    already_today = count_processed_today(statuses={"published", "draft"})
    if daily_limit_total and already_today >= daily_limit_total:
        return AutopilotResult(
            0,
            0,
            0,
            0,
            0,
            [f"Daily limit reached: {already_today}/{daily_limit_total} (published+draft)."],
        )

    details: List[str] = []
    processed = published = drafted = skipped = errors = 0

    with autopilot_lock():
        # Build a simple queue in priority order
        queue: List[Tuple[str, str, Dict[str, Any]]] = []

        if "rss" in selected:
            rss_limit_per_feed = max(0, _get_int(settings, "autopilot_rss_limit_per_feed", 3))
            items = fetch_latest_rss_items(settings.get("rss_sources", []), limit_per_feed=rss_limit_per_feed)
            for item in items:
                if is_url_processed(item.link):
                    continue
                queue.append(("rss", item.link, {"title": item.title, "summary": item.summary, "source": item.source}))

        if "youtube" in selected:
            api_key = (settings.get("youtube_api_key") or "").strip()
            if not api_key:
                details.append("YouTube enabled but youtube_api_key is empty; skipping YouTube.")
            else:
                yt_limit_per_channel = max(0, _get_int(settings, "autopilot_youtube_limit_per_channel", 3))
                for ch in settings.get("youtube_channels", []) or []:
                    ch = (ch or "").strip()
                    if not ch:
                        continue
                    try:
                        videos = fetch_latest_channel_videos(ch, api_key=api_key, limit=yt_limit_per_channel)
                    except Exception as exc:
                        errors += 1
                        details.append(f"YouTube channel {ch}: discovery error: {exc}")
                        continue
                    for v in videos:
                        if is_url_processed(v.url):
                            continue
                        queue.append(("youtube", v.url, {"channel": v.channel, "published_at": v.published_at, "title": v.title}))

        if "telegram" in selected:
            tg_limit = max(0, _get_int(settings, "autopilot_telegram_limit_per_channel", 3))
            for ch in settings.get("telegram_channels", []) or []:
                ch = (ch or "").strip()
                if not ch:
                    continue
                try:
                    posts = fetch_latest_channel_posts(ch, settings, limit=tg_limit)
                except Exception as exc:
                    errors += 1
                    details.append(f"Telegram {ch}: fetch error: {exc}")
                    continue
                for p in posts:
                    if is_url_processed(p.url):
                        continue
                    queue.append(("telegram", p.url, {"text": p.text}))

        if not queue:
            return AutopilotResult(0, 0, 0, 0, 0, ["No new items found."])

        # Cap work per run
        if max_per_run:
            queue = queue[:max_per_run]

        for source_type, source_url, payload in queue:
            if daily_limit_total:
                already_today = count_processed_today(statuses={"published", "draft"})
                if already_today >= daily_limit_total:
                    details.append(f"Daily limit reached during run: {already_today}/{daily_limit_total}.")
                    break

            wp_status = wp_status_for_source.get(source_type) or "draft"
            settings_for_publish = dict(settings)
            settings_for_publish["wp_post_status"] = wp_status

            try:
                if source_type == "youtube":
                    article_data = process_youtube_video(source_url, settings_for_publish)
                elif source_type == "rss":
                    prompt = (
                        "Сгенерируй статью по новости из RSS. Сохрани факты, перефразируй, сделай материал оригинальным.\n\n"
                        f"Источник (лента): {payload.get('source')}\n"
                        f"Ссылка: {source_url}\n\n"
                        f"Заголовок: {payload.get('title')}\n\n"
                        f"Краткое описание/анонс:\n{payload.get('summary') or ''}"
                    )
                    article_data = generate_article(
                        prompt=prompt,
                        provider="openai",
                        api_key=settings.get("openai_api_key", ""),
                        base_url=settings.get("base_url"),
                        model_name=settings.get("model_name", "gpt-4o"),
                        system_prompt=build_article_system_prompt(settings, seed=source_url),
                    )
                else:
                    prompt = (
                        "Сгенерируй статью по посту из Telegram-канала. "
                        "Сохрани смысл, оформи как полноценную статью.\n\n"
                        f"Ссылка: {source_url}\n\n"
                        f"Текст поста:\n{payload.get('text') or ''}"
                    )
                    article_data = generate_article(
                        prompt=prompt,
                        provider="openai",
                        api_key=settings.get("openai_api_key", ""),
                        base_url=settings.get("base_url"),
                        model_name=settings.get("model_name", "gpt-4o"),
                        system_prompt=build_article_system_prompt(settings, seed=source_url),
                    )

                # Ads injection
                ad_c = settings.get("ad_code", "")
                if ad_c and article_data.get("html_content"):
                    article_data["html_content"] = inject_ad_block(
                        article_data["html_content"], ad_c, int(settings.get("ad_paragraph", 3) or 3)
                    )

                # Publish/Draft
                link = publish_to_wordpress(settings_for_publish, article_data)

                processed += 1
                if wp_status == "publish":
                    published += 1
                    mark_url_processed(source_url, source=source_type, title=article_data.get("seo_title"), status="published")
                else:
                    drafted += 1
                    mark_url_processed(source_url, source=source_type, title=article_data.get("seo_title"), status="draft")

                details.append(f"{source_type}: {source_url} -> {wp_status} ({link})")
            except Exception as exc:
                errors += 1
                skipped += 1
                details.append(f"{source_type}: {source_url} error: {exc}")

    return AutopilotResult(processed, published, drafted, skipped, errors, details)

