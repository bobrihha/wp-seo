from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import feedparser

from utils.database import is_url_processed


@dataclass(frozen=True)
class RssItem:
    title: str
    link: str
    published: Optional[str]
    summary: Optional[str]
    source: str


def fetch_latest_rss_items(
    rss_urls: List[str],
    *,
    limit_per_feed: int = 5,
) -> List[RssItem]:
    items: List[RssItem] = []

    for feed_url in rss_urls or []:
        feed_url = (feed_url or "").strip()
        if not feed_url:
            continue

        parsed = feedparser.parse(feed_url)
        for entry in (parsed.entries or [])[: max(0, int(limit_per_feed))]:
            link = (getattr(entry, "link", "") or "").strip()
            if not link:
                continue

            if is_url_processed(link):
                continue

            title = (getattr(entry, "title", "") or "").strip()
            published = (getattr(entry, "published", None) or getattr(entry, "updated", None) or None)
            summary = (getattr(entry, "summary", None) or getattr(entry, "description", None) or None)

            items.append(
                RssItem(
                    title=title,
                    link=link,
                    published=published,
                    summary=summary,
                    source=feed_url,
                )
            )

    return items
