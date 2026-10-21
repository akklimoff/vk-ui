import logging
import threading
import time

log = logging.getLogger("vk-ui")

ARCHIVE_TTL = 10.0


class Archive:
    """id архивных бесед. Флага «в архиве» у беседы VK не отдаёт, их знает только getConversations с filter=archive;
    список держится недолго, иначе каждый тик поллинга открытого чата стоил бы лишнего запроса к VK.
    Если VK не отдал архив, остаётся последний известный: отказ архива не должен ронять весь мессенджер."""

    def __init__(self, fetch, ttl: float = ARCHIVE_TTL, now=time.monotonic):
        self._fetch = fetch
        self._ttl = ttl
        self._now = now
        self._peers: frozenset[int] = frozenset()
        self._at: float | None = None
        self._lock = threading.Lock()

    def peers(self, fresh: bool = False) -> frozenset[int]:
        with self._lock:
            if fresh or self._at is None or self._now() - self._at >= self._ttl:
                try:
                    self._peers = frozenset(self._fetch())
                except Exception as e:
                    log.warning("Архив чатов VK не получен: %s", e)
                self._at = self._now()
            return self._peers
