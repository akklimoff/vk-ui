import logging
import threading
import time

log = logging.getLogger("vk-ui")

RETRY_SECONDS = 5.0
# VK держит запрос long poll до 25 секунд; дольше без ответа — связи нет
STALE_SECONDS = 90.0


class Inbox:
    """Номер версии переписки: его двигает long poll VK самой панели, по нему мессенджер перечитывает чат.
    Поток long poll заводится при первом подписчике и живёт до конца процесса."""

    def __init__(self, listen, retry: float = RETRY_SECONDS, sleep=time.sleep, now=time.monotonic):
        self._listen = listen
        self._retry = retry
        self._sleep = sleep
        self._now = now
        self._version = 0
        self._alive_at = 0.0
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def version(self) -> int:
        return self._version

    def changed(self) -> None:
        with self._lock:
            self._version += 1

    def polled(self) -> None:
        self._alive_at = self._now()

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
        while True:
            try:
                for _ in self._listen(self.changed, self.polled):
                    pass
            except Exception as e:
                log.warning("Long poll VK прервался: %s", type(e).__name__)
            self._sleep(self._retry)
