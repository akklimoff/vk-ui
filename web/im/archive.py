import logging
import threading
import time

log = logging.getLogger("vk-ui")

ARCHIVE_TTL = 60.0
REFUSED_TTL = 3600.0
ACCESS_DENIED = 15


class Archive:
    """id архивных бесед. Флага «в архиве» у беседы VK не отдаёт, их знает только getConversations с filter=archive;
    список держится в памяти, иначе каждое обновление списка стоило бы лишнего запроса к VK.
    Если VK не отдал архив, остаётся последний известный: отказ архива не должен ронять весь мессенджер.
    На отказ в доступе ([15], токен не того приложения) VK отвечает одинаково всегда — его не переспрашивают час."""

    def __init__(self, fetch, ttl: float = ARCHIVE_TTL, refused_ttl: float = REFUSED_TTL, now=time.monotonic):
        self._fetch = fetch
        self._ttl = ttl
        self._refused_ttl = refused_ttl
        self._now = now
        self._peers: frozenset[int] = frozenset()
        self._at: float | None = None
        self._refused_until = 0.0
        self._lock = threading.Lock()
        self._first = threading.Lock()
        self._loading = False

    def peers(self, fresh: bool = False) -> frozenset[int]:
        if self._at is None:
            # пока архив ни разу не получен, ждут все: без него в списке мелькнули бы архивные чаты
            with self._first:
                if self._at is None:
                    self._refresh()
            return self._peers
        with self._lock:
            now = self._now()
            due = (fresh or now - self._at >= self._ttl) and now >= self._refused_until and not self._loading
            self._loading = self._loading or due
        # обновляет один запрос, остальные берут прежний список: открытие чата не ждёт медленный архив
        if due:
            try:
                self._refresh()
            finally:
                self._loading = False
        return self._peers

    def _refresh(self) -> None:
        now = self._now()
        try:
            self._peers = frozenset(self._fetch())
        except Exception as e:
            if getattr(e, "code", None) == ACCESS_DENIED:
                self._refused_until = now + self._refused_ttl
                log.warning("VK не отдаёт архив чатов этому токену, следующая попытка через час: %s", e)
            else:
                log.warning("Архив чатов VK не получен: %s", e)
        self._at = now
