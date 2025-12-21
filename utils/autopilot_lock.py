from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def autopilot_lock(*, name: str = "autopilot") -> Iterator[None]:
    """
    Cross-process lock to prevent concurrent autopilot runs (cron + UI button).
    Uses a best-effort exclusive file lock on Unix.
    """
    lock_dir = Path(__file__).resolve().parents[1] / "secrets"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / f"{name}.lock"

    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            import fcntl  # type: ignore

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception as exc:
            raise RuntimeError("Autopilot is already running (lock is held).") from exc
        yield
    finally:
        try:
            os.close(fd)
        except Exception:
            pass

