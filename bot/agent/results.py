DROPPED_KEYS = frozenset({"random_id", "important", "is_hidden", "version", "track_code", "web_view_token",
                          "orig_photo", "has_tags", "waveform", "images", "images_with_background", "image",
                          "first_frame", "preview", "square_crop",
                          # VK кладёт их в каждый профиль без спроса, и на них уходит больше половины списка
                          # участников; аватарку модель просит явно — photo_max_orig
                          "photo_50", "photo_100", "online_info", "can_access_closed"})
EMPTY = (None, "", [], {})
PREFERRED_WIDTH = 1280


def best_size(sizes) -> str:
    """Адрес самой крупной копии фото не шире PREFERRED_WIDTH; если таких нет — самой узкой."""
    known = [size for size in sizes if isinstance(size, dict) and isinstance(size.get("url"), str)]
    if not known:
        return ""
    fitting = [size for size in known if (size.get("width") or 0) <= PREFERRED_WIDTH]
    chosen = (max(fitting, key=lambda size: size.get("width") or 0) if fitting
              else min(known, key=lambda size: size.get("width") or 0))
    return chosen["url"]


def slim(value):
    """Ответ VK без служебного: модель видит результат обрезанным по длине, и шум вытеснял бы из него сообщения."""
    if isinstance(value, (list, tuple)):
        return [item for item in map(slim, value) if item not in EMPTY]
    if not isinstance(value, dict):
        return value
    result = {}
    for name, item in value.items():
        if name in DROPPED_KEYS:
            continue
        if name == "sizes" and isinstance(item, list):
            result["url"] = best_size(item)
            continue
        item = slim(item)
        if item not in EMPTY:
            result[name] = item
    return result
