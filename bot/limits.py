import re
import time
from collections import deque


def mention_of(user_id: int) -> str:
    # упоминание приходит в тексте как [id123|@name]
    return f"[id{user_id}|"


LIVE_SIGNS = str.maketrans({"@": "＠", "*": "＊"})


def plain_label(label: str) -> str:
    # имя вида @ник или *ник VK сам превращает обратно в упоминание
    return label[:1].translate(LIVE_SIGNS) + label[1:]


def strip_self_mention(text: str, me_id: int) -> str:
    """Текст без живого тега владельца: отправленное с таким тегом вернулось бы из long poll его же просьбой."""
    text = text or ""
    tag = re.compile(rf"\[id{me_id}\|([^\]]*)\]")
    prefix = mention_of(me_id)
    # вложенный тег после одного прохода снова собирается в целый, а незакрытый фильтр входа всё равно узнаёт
    while tag.search(text):
        text = tag.sub(lambda found: plain_label(found.group(1)), text)
    while prefix in text:
        text = text.replace(prefix, "")
    return re.sub(rf"[@*](?=id{me_id}(?!\d))", lambda found: found.group().translate(LIVE_SIGNS), text)


class RateLimiter:
    def __init__(
        self,
        user_cooldown_seconds: float,
        chat_limit_per_hour: int,
        global_limit_per_minute: int,
        clock=time.monotonic,
    ):
        self._cooldown = user_cooldown_seconds
        self._chat_limit = chat_limit_per_hour
        self._global_limit = global_limit_per_minute
        self._clock = clock
        self._last_by_user: dict[int, float] = {}
        self._by_chat: dict[int, deque[float]] = {}
        self._recent: deque[float] = deque()

    def allow(self, user_id: int, peer_id: int) -> bool:
        now = self._clock()

        last = self._last_by_user.get(user_id)
        if last is not None and now - last < self._cooldown:
            return False

        chat = self._by_chat.setdefault(peer_id, deque())
        while chat and now - chat[0] >= 3600:
            chat.popleft()
        if len(chat) >= self._chat_limit:
            return False

        while self._recent and now - self._recent[0] >= 60:
            self._recent.popleft()
        if len(self._recent) >= self._global_limit:
            return False

        self._last_by_user[user_id] = now
        chat.append(now)
        self._recent.append(now)
        return True
