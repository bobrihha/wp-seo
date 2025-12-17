from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


DB_PATH = Path(__file__).resolve().parents[1] / "content_hub.sqlite3"


@dataclass(frozen=True)
class ProcessedLink:
    url: str
    source: str
    status: str
    created_at: str
    title: Optional[str] = None


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_links (
              url TEXT PRIMARY KEY,
              source TEXT NOT NULL,
              title TEXT,
              status TEXT NOT NULL,
              created_at TEXT NOT NULL
            )
            """
        )


def is_url_processed(url: str) -> bool:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM processed_links WHERE url = ? LIMIT 1",
            (url,),
        ).fetchone()
    return row is not None


def mark_url_processed(url: str, *, source: str, title: Optional[str] = None, status: str = "seen") -> None:
    init_db()
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO processed_links (url, source, title, status, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
              source=excluded.source,
              title=COALESCE(excluded.title, processed_links.title),
              status=excluded.status
            """,
            (url, source, title, status, now),
        )

