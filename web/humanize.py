UNITS = ((86400, "д"), (3600, "ч"), (60, "мин"), (1, "с"))


def ago(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    if seconds < 5:
        return "только что"
    for size, unit in UNITS:
        if seconds >= size:
            return f"{int(seconds // size)} {unit} назад"
    return "только что"


def duration(seconds: float | None) -> str:
    """Секунды при минутах не показываем: аптайм читают, а не засекают."""
    if seconds is None:
        return "—"
    rest = int(seconds)
    parts = []
    for size, unit in UNITS:
        if rest >= size and not (unit == "с" and parts):
            parts.append(f"{rest // size} {unit}")
            rest %= size
        if len(parts) == 2:
            break
    return " ".join(parts) if parts else "0 с"
