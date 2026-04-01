from datetime import datetime


def log(message: str) -> None:
    now = datetime.now()
    print(f"[{now.strftime('%-I:%M:%S')}.{now.microsecond // 1000} {now.strftime('%p')}] {message}")
