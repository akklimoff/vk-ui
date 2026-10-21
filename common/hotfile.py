import logging
import os
import threading
import time
from typing import Callable, Generic, TypeVar

log = logging.getLogger("vk-bot")

T = TypeVar("T")
RETRY_SECONDS = 30.0


class PartialRead(Exception):
    """Разбор дал значение, но не всё, что в файле: оно вступает в силу сразу,
    а файл перечитывается снова через RETRY_SECONDS."""

    def __init__(self, value):
        super().__init__("файл прочитан не полностью")
        self.value = value


class WatchedFile(Generic[T]):
    """Значение из файла, перечитываемое по mtime без перезапуска.
    Нет файла — default; файл не разобрался — прежнее значение и новая попытка через RETRY_SECONDS;
    разобрался не полностью (PartialRead) — то, что разобралось, и такая же новая попытка."""

    def __init__(self, path: str, parse: Callable[[str], T], default: T, log_label: str, clock=time.monotonic):
        self._path = path
        self._parse = parse
        self._default = default
        self._label = log_label
        self._value = default
        self._stamp: tuple | None = None
        self._failed_stamp: tuple | None = None
        self._retry_at = 0.0
        self._clock = clock
        self._lock = threading.Lock()

    def current(self) -> T:
        # файл читают и главный цикл, и поток агента: второй ждёт перечитывания, а не берёт прежнее значение
        with self._lock:
            return self._reloaded()

    def _reloaded(self) -> T:
        try:
            found = os.stat(self._path)
            # одного mtime мало: две записи подряд укладываются в один его шаг, и вторая осталась бы непрочитанной
            stamp = (found.st_mtime_ns, found.st_ino, found.st_size)
        except OSError:
            if self._stamp is not None:
                log.info("Файл %s пропал, работаю без него", self._path)
            self._stamp = None
            self._value = self._default
            return self._value

        if stamp != self._stamp and (stamp != self._failed_stamp or self._clock() >= self._retry_at):
            try:
                with open(self._path, encoding="utf-8") as f:
                    self._value = self._parse(f.read())
                self._stamp = stamp
                log.info("%s перечитан из %s", self._label, self._path)
            except PartialRead as partial:
                self._value = partial.value
                self._stamp = None
                self._failed_stamp = stamp
                self._retry_at = self._clock() + RETRY_SECONDS
                log.warning("%s из %s прочитан не полностью, повтор через %d с", self._label, self._path,
                            RETRY_SECONDS)
            except Exception:
                # разбор мог упасть не из-за файла (списки доступа ходят в VK за никами), поэтому mtime не
                # запоминаем как прочитанный; пауза не даёт перечитывать битый файл на каждом событии
                self._failed_stamp = stamp
                self._retry_at = self._clock() + RETRY_SECONDS
                log.exception("Не удалось прочитать %s, работаю по прежнему значению", self._path)
        return self._value
