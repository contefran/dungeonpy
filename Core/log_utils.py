"""log_utils.py — Timestamped console logger for DungeonPy."""

from datetime import datetime


def log_msg(message: str) -> None:
    """Print *message* prefixed with a ``[H:MM:SS.ms AM/PM]`` timestamp."""
    now = datetime.now()
    hour = now.strftime("%I").lstrip("0") or "0"
    print(f"[{hour}:{now.strftime('%M:%S')}.{now.microsecond // 1000} {now.strftime('%p')}] {message}")
