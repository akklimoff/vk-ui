import base64
import re

from bot.agent.results import DROPPED_KEYS, best_size

# картинки скачивает сам бот, и адрес для этого берётся из переписки: только хранилища фото ВКонтакте,
# иначе чужое сообщение заставило бы сервер сходить по любому адресу
# адрес сверяется целиком и буквально: разборщики URL расходятся в том, где кончается хост («\\», «@», «;»),
# и то, что один счёл бы хранилищем VK, другой открыл бы как чужой сервер
PHOTO_URL = re.compile(r"https://(?:[a-z0-9-]+\.)+(?:vkuserphoto\.ru|userapi\.com)/[!-\[\]-~]*")
AVATAR_FIELD = re.compile(r"photo_(\d+|max|max_orig|400_orig)")
SHOWN_AT_ONCE = 4


def is_photo_url(url) -> bool:
    return isinstance(url, str) and PHOTO_URL.fullmatch(url) is not None


def photo_urls(value) -> list[str]:
    """Адреса картинок в ответе VK в порядке обхода: фото — самой удобной копией, аватары — как есть."""
    found: dict[str, None] = {}
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, (list, tuple)):
            stack.extend(reversed(item))
        elif isinstance(item, dict):
            if isinstance(item.get("sizes"), list):
                found.setdefault(best_size(item["sizes"]))
            # мелкие аватары из результата вырезаны: показывать то, чего модель не просила, незачем
            avatars = [url for name, url in item.items()
                       if AVATAR_FIELD.fullmatch(name) and name not in DROPPED_KEYS]
            # один и тот же аватар приходит в нескольких размерах: хватит самого крупного, он идёт последним
            found.setdefault(avatars[-1] if avatars else "")
            stack.extend(reversed([child for name, child in item.items() if name != "sizes"]))
    return [url for url in found if is_photo_url(url)]


def data_url(kind: str, data: bytes) -> str:
    return f"data:{kind};base64,{base64.b64encode(data).decode('ascii')}"
