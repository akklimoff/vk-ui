import logging
import threading
import time

from web.pace import background

log = logging.getLogger("vk-ui")

RETRY_SECONDS = 5.0
MAX_RETRY_SECONDS = 120.0
# VK держит запрос long poll до 25 секунд; дольше без ответа — связи нет
STALE_SECONDS = 90.0


class Inbox:
    """Версия переписки: её двигает long poll VK самой панели, по ней мессенджер перечитывает чаты.
    Для каждого чата помнится версия его последнего изменения — перечитывается только то, что менялось.
    Поток long poll заводится при первом подписчике и живёт до конца процесса."""

    def __init__(self, listen, retry: float = RETRY_SECONDS, max_retry: float = MAX_RETRY_SECONDS,
                 sleep=time.sleep, now=time.monotonic):
        self._listen = listen
        self._retry = retry
        self._max_retry = max_retry
        self._sleep = sleep
        self._now = now
        self._version = 0
        self._peers: dict[int, int] = {}
        self._unknown = 0
        self._changed_at: dict[int, float] = {}
        self._unknown_at = float("-inf")
        self._failures = 0
        self._alive_at = 0.0
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def version(self) -> int:
        return self._version

    def peer_version(self, peer: int) -> int:
        """Версия последнего изменения чата; событие без чата меняет все."""
        return max(self._peers.get(peer, 0), self._unknown)

    def changed_at(self, peer: int) -> float:
        return max(self._changed_at.get(peer, float("-inf")), self._unknown_at)

    def changes_since(self, version: int) -> tuple[int, frozenset[int] | None]:
        """Текущая версия и чаты, изменившиеся после version; None — было событие без чата."""
        with self._lock:
            if self._unknown > version:
                return self._version, None
            return self._version, frozenset(p for p, v in self._peers.items() if v > version)

    def changed(self, peers=None) -> None:
        with self._lock:
            self._version += 1
            now = self._now()
            if peers is None:
                self._unknown = self._version
                self._unknown_at = now
            else:
                for peer in peers:
                    self._peers[peer] = self._version
                    self._changed_at[peer] = now

    def polled(self) -> None:
        self._alive_at = self._now()
        self._failures = 0

    def healthy(self) -> bool:
        return self._thread is not None and self._now() - self._alive_at < STALE_SECONDS

    def start(self) -> None:
        with self._lock:
            if self._thread is not None:
                return
            self._alive_at = self._now()
            self._thread = threading.Thread(target=self._run, name="vk-longpoll", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        with background():
            while True:
                try:
                    for _ in self._listen(self.changed, self.polled):
                        pass
                except Exception as e:
                    self._failures += 1
                    log.warning("Long poll VK прервался: %s %s", type(e).__name__, getattr(e, "code", ""))
                # сбои подряд — пауза растёт: частые переподключения к VK, который отказывает, лишь множат отказы
                self._sleep(min(self._retry * 2 ** max(0, self._failures - 1), self._max_retry))
