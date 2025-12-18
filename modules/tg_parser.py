from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from telethon import TelegramClient

from utils.database import is_url_processed, mark_url_processed


@dataclass(frozen=True)
class TgPost:
    channel: str
    message_id: int
    url: str
    text: str
    date: Optional[str]


async def _fetch_latest_posts_async(
    channel_username: str,
    *,
    api_id: int,
    api_hash: str,
    limit: int = 3,
    session_path: str = "secrets/telethon.session",
) -> List[TgPost]:
    if not channel_username or not channel_username.strip():
        raise ValueError("channel_username is empty")
    if not api_id or not api_hash:
        raise ValueError("telegram_api_id and telegram_api_hash are required")

    channel_username = channel_username.lstrip("@").strip()
    limit = max(0, int(limit))

    posts: List[TgPost] = []

    path = Path(session_path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[1] / path
    path.parent.mkdir(parents=True, exist_ok=True)

    client = TelegramClient(str(path), api_id, api_hash)
    await client.connect()
    try:
        messages = await client.get_messages(channel_username, limit=limit)
        for msg in messages:
            if not msg or not getattr(msg, "id", None):
                continue

            url = f"https://t.me/{channel_username}/{msg.id}"
            if is_url_processed(url):
                continue

            text = (getattr(msg, "message", "") or "").strip()
            if not text:
                continue

            date = getattr(msg, "date", None)
            posts.append(
                TgPost(
                    channel=channel_username,
                    message_id=int(msg.id),
                    url=url,
                    text=text,
                    date=date.isoformat() if date else None,
                )
            )

            mark_url_processed(url, source="telegram", title=None, status="seen")
    finally:
        await client.disconnect()

    return posts


def fetch_latest_channel_posts(channel_username: str, settings: dict, *, limit: int = 3) -> List[TgPost]:
    api_id_raw = settings.get("telegram_api_id", "")
    api_hash = settings.get("telegram_api_hash", "")
    session_path = settings.get("telegram_session_path", "secrets/telethon.session")

    try:
        api_id = int(api_id_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("telegram_api_id must be an integer") from exc

    coro = _fetch_latest_posts_async(
        channel_username,
        api_id=api_id,
        api_hash=api_hash,
        limit=limit,
        session_path=session_path,
    )
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    else:
        raise RuntimeError(
            "fetch_latest_channel_posts() cannot be called from a running event loop; "
            "use _fetch_latest_posts_async() and await it."
        )
