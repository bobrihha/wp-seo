from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone
from typing import List, Optional

from modules.autopilot import run_autopilot_once
from utils.config_manager import load_settings


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AI Content Hub Autopilot")
    p.add_argument("--once", action="store_true", help="Run one cycle and exit (default).")
    p.add_argument("--daemon", action="store_true", help="Run continuously according to poll intervals.")
    p.add_argument(
        "--sources",
        nargs="*",
        choices=["rss", "youtube", "telegram"],
        help="Override enabled sources for this run.",
    )
    p.add_argument("--sleep-seconds", type=int, default=30, help="Daemon loop sleep step (seconds).")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    settings = load_settings()

    if args.daemon:
        last_run = {"rss": 0.0, "youtube": 0.0, "telegram": 0.0}
        while True:
            now = time.time()
            if not bool(settings.get("autopilot_enabled", False)):
                time.sleep(max(1, int(args.sleep_seconds)))
                settings = load_settings()
                continue
            due: List[str] = []
            for source in ("rss", "youtube", "telegram"):
                key = f"autopilot_{source}_poll_minutes"
                minutes = int(settings.get(key, 10) or 10)
                interval = max(60, minutes * 60)
                if now - last_run[source] >= interval:
                    due.append(source)

            if due:
                try:
                    result = run_autopilot_once(settings, sources=due)
                    ts = datetime.now(timezone.utc).isoformat()
                    print(
                        f"[{ts}] processed={result.processed} published={result.published} draft={result.drafted} errors={result.errors}"
                    )
                    for line in result.details[-30:]:
                        print(" -", line)
                    for s in due:
                        last_run[s] = now
                except Exception as exc:
                    ts = datetime.now(timezone.utc).isoformat()
                    print(f"[{ts}] autopilot error: {exc}")

            time.sleep(max(1, int(args.sleep_seconds)))
            settings = load_settings()

    # default: once
    result = run_autopilot_once(settings, sources=args.sources)
    for line in result.details:
        print(line)
    return 0 if result.errors == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
