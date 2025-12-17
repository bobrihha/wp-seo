from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    CouldNotRetrieveTranscript,
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)

from typing import Any, Dict

from modules.ai_engine import generate_article


def extract_video_id(url: str) -> str:
    if not url or not url.strip():
        raise ValueError("YouTube URL is empty")

    parsed = urlparse(url.strip())

    host = (parsed.netloc or "").lower()
    path = parsed.path or ""

    if host in {"youtu.be", "www.youtu.be"}:
        video_id = path.lstrip("/").split("/")[0]
        if video_id:
            return video_id

    if host.endswith("youtube.com") or host.endswith("youtube-nocookie.com"):
        query = parse_qs(parsed.query or "")
        if "v" in query and query["v"]:
            return query["v"][0]

        parts = [p for p in path.split("/") if p]
        for marker in ("shorts", "embed", "live"):
            if marker in parts:
                idx = parts.index(marker)
                if idx + 1 < len(parts) and parts[idx + 1]:
                    return parts[idx + 1]

    raise ValueError(f"Could not extract video id from URL: {url}")


def get_transcript(video_id: str) -> str:
    if not video_id or not video_id.strip():
        raise ValueError("video_id is empty")

    preferred_languages = ["ru", "uk", "en"]

    try:
        if hasattr(YouTubeTranscriptApi, "get_transcript"):
            segments = YouTubeTranscriptApi.get_transcript(video_id, languages=preferred_languages)
        else:
            api = YouTubeTranscriptApi()
            segments = api.fetch(video_id, languages=preferred_languages).to_raw_data()
    except (TranscriptsDisabled, VideoUnavailable, NoTranscriptFound, CouldNotRetrieveTranscript):
        transcript_list = (
            YouTubeTranscriptApi.list_transcripts(video_id)
            if hasattr(YouTubeTranscriptApi, "list_transcripts")
            else YouTubeTranscriptApi().list(video_id)
        )

        transcript = None
        for lang in preferred_languages:
            try:
                transcript = transcript_list.find_transcript([lang])
                break
            except NoTranscriptFound:
                continue

        if transcript is None:
            try:
                transcript = transcript_list.find_manually_created_transcript(preferred_languages)
            except NoTranscriptFound:
                transcript = transcript_list.find_generated_transcript(preferred_languages)

        segments = transcript.fetch().to_raw_data()

    text = "\n".join((seg.get("text") or "").strip() for seg in segments).strip()
    if not text:
        raise RuntimeError("Transcript is empty")
    return text


def process_youtube_video(url: str, settings: dict) -> Dict[str, Any]:
    video_id = extract_video_id(url)
    transcript_text = get_transcript(video_id)

    provider = settings.get("ai_provider") or settings.get("provider") or "openai"

    if provider == "openai":
        api_key = settings.get("openai_api_key", "")
        base_url = settings.get("base_url")
        model_name = settings.get("model_name", "gpt-4o")
        return generate_article(
            prompt=(
                "Сгенерируй статью на русском языке по этому транскрипту YouTube-видео. "
                "Сохрани факты, убери мусорные повторы, оформи читабельно.\n\n"
                f"URL: {url}\n\n"
                f"Транскрипт:\n{transcript_text}"
            ),
            provider="openai",
            api_key=api_key,
            base_url=base_url,
            model_name=model_name,
            system_prompt=settings.get("article_system_prompt"),
        )

    if provider == "gemini":
        api_key = settings.get("gemini_api_key", "")
        model_name = settings.get("gemini_model_name") or settings.get("model_name", "")
        return generate_article(
            prompt=(
                "Сгенерируй статью на русском языке по этому транскрипту YouTube-видео. "
                "Сохрани факты, убери мусорные повторы, оформи читабельно.\n\n"
                f"URL: {url}\n\n"
                f"Транскрипт:\n{transcript_text}"
            ),
            provider="gemini",
            api_key=api_key,
            model_name=model_name,
            system_prompt=settings.get("article_system_prompt"),
        )

    raise ValueError(f"Unsupported provider: {provider}")
