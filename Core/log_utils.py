from datetime import datetime


def log(message: str) -> None:
    now = datetime.now()
    hour = now.strftime("%I").lstrip("0") or "0"
    print(f"[{hour}:{now.strftime('%M:%S')}.{now.microsecond // 1000} {now.strftime('%p')}] {message}")
