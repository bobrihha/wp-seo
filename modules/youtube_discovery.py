from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional
from urllib.parse import urlparse

import requests


YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"


@dataclass(frozen=True)
class YouTubeVideo:
    video_id: str
    url: str
    title: Optional[str]
    published_at: Optional[str]
    channel: str


def _extract_channel_identifier(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return ""

    if value.startswith("@"):
        return value

    if value.startswith("http://") or value.startswith("https://"):
        parsed = urlparse(value)
        parts = [p for p in (parsed.path or "").split("/") if p]
        # Examples:
        # /@handle
        # /channel/UCxxxx
        if parts and parts[0].startswith("@"):
            return parts[0]
        if len(parts) >= 2 and parts[0] == "channel":
            return parts[1]
        if parts:
            # /c/... or /user/... -> fallback to using the last segment as query
            return parts[-1]

    return value


def _get_json(url: str, params: Dict[str, str], *, timeout: int = 30) -> Dict:
    resp = requests.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(str(data["error"]))
    return data if isinstance(data, dict) else {}


def resolve_channel_uploads_playlist_id(channel: str, *, api_key: str) -> str:
    """
    Returns uploads playlist id for a channel identifier (handle '@x' or channel id 'UC...').
    Uses channels.list(forHandle=...) when possible.
    """
    if not api_key:
        raise ValueError("youtube_api_key is required")

    ident = _extract_channel_identifier(channel)
    if not ident:
        raise ValueError("channel is empty")

    channel_id: Optional[str] = None

    # 1) Handle -> channels.list(forHandle=...)
    if ident.startswith("@"):
        handle = ident[1:]
        data = _get_json(
            f"{YOUTUBE_API_BASE}/channels",
            params={
                "part": "contentDetails",
                "forHandle": handle,
                "key": api_key,
                "maxResults": "1",
            },
        )
        items = data.get("items") or []
        if items:
            uploads = (
                items[0]
                .get("contentDetails", {})
                .get("relatedPlaylists", {})
                .get("uploads")
            )
            if uploads:
                return str(uploads)

        # Fallback: search for channel by query
        search = _get_json(
            f"{YOUTUBE_API_BASE}/search",
            params={
                "part": "snippet",
                "q": handle,
                "type": "channel",
                "maxResults": "1",
                "key": api_key,
            },
        )
        s_items = search.get("items") or []
        if s_items:
            channel_id = s_items[0].get("id", {}).get("channelId")

    # 2) Already a channel id
    if not channel_id and ident.startswith("UC"):
        channel_id = ident

    if not channel_id:
        # Best-effort: treat ident as query
        search = _get_json(
            f"{YOUTUBE_API_BASE}/search",
            params={
                "part": "snippet",
                "q": ident,
                "type": "channel",
                "maxResults": "1",
                "key": api_key,
            },
        )
        s_items = search.get("items") or []
        if s_items:
            channel_id = s_items[0].get("id", {}).get("channelId")

    if not channel_id:
        raise RuntimeError(f"Could not resolve channel id for: {channel}")

    data = _get_json(
        f"{YOUTUBE_API_BASE}/channels",
        params={
            "part": "contentDetails",
            "id": channel_id,
            "key": api_key,
            "maxResults": "1",
        },
    )
    items = data.get("items") or []
    if not items:
        raise RuntimeError(f"Channel not found: {channel}")

    uploads = items[0].get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
    if not uploads:
        raise RuntimeError(f"Uploads playlist not found for channel: {channel}")
    return str(uploads)


def fetch_latest_channel_videos(
    channel: str,
    *,
    api_key: str,
    limit: int = 5,
) -> List[YouTubeVideo]:
    uploads_playlist_id = resolve_channel_uploads_playlist_id(channel, api_key=api_key)
    limit = max(0, int(limit))
    data = _get_json(
        f"{YOUTUBE_API_BASE}/playlistItems",
        params={
            "part": "contentDetails,snippet",
            "playlistId": uploads_playlist_id,
            "maxResults": str(limit if limit > 0 else 1),
            "key": api_key,
        },
    )
    items = data.get("items") or []
    videos: List[YouTubeVideo] = []
    ident = _extract_channel_identifier(channel)
    for item in items:
        content = item.get("contentDetails") or {}
        video_id = content.get("videoId")
        if not video_id:
            continue
        snippet = item.get("snippet") or {}
        published_at = content.get("videoPublishedAt") or snippet.get("publishedAt")
        title = snippet.get("title")
        videos.append(
            YouTubeVideo(
                video_id=str(video_id),
                url=f"https://www.youtube.com/watch?v={video_id}",
                title=str(title) if title else None,
                published_at=str(published_at) if published_at else None,
                channel=ident or channel,
            )
        )
    return videos

