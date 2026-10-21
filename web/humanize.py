from datetime import datetime

MONTHS_SHORT = ("янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")


def clock(ts: float, tz) -> str:
    return datetime.fromtimestamp(ts, tz).strftime("%H:%M")


def mmss(seconds: int) -> str:
    return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"


def plural(n: int, one: str, few: str, many: str) -> str:
    tail = n % 100
    if 11 <= tail <= 14:
        form = many
    else:
        form = {1: one, 2: few, 3: few, 4: few}.get(n % 10, many)
    return f"{n} {form}"


def short_since(ts: float, now: float, tz) -> str:
    ago = max(0.0, now - ts)
    if ago < 3600:
        return f"{max(1, int(ago // 60))}м"
    if ago < 86400:
        return f"{int(ago // 3600)}ч"
    if ago < 7 * 86400:
        return f"{int(ago // 86400)}д"
    at = datetime.fromtimestamp(ts, tz)
    return f"{at.day} {MONTHS_SHORT[at.month - 1]}"
