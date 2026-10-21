import json
import logging
import os
import time
from collections import deque

log = logging.getLogger("vk-bot")

FLUSH_INTERVAL = 5.0
ERROR_WINDOW = 3600.0


def write_json_atomic(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def read_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


class StatusWriter:
    def __init__(self, path: str, me_id: int, me_name: str, now=time.time):
        self._path = path
        self._now = now
        self._errors: deque[float] = deque()
        self._last_flush = 0.0
        self._data = {
            "me_id": me_id, "me_name": me_name, "model": "",
            "started_at": now(), "heartbeat_at": None, "last_poll_at": None,
            "last_event_at": None, "last_reply_at": None, "errors_last_hour": 0,
        }

    def set_model(self, model_id: str) -> None:
        if model_id:
            self._data["model"] = model_id

    def polled(self) -> None:
        """Long poll получил ответ VK, пусть и пустой: зовётся из потока long poll."""
        self._data["last_poll_at"] = self._now()

    def event(self) -> None:
        self._data["last_event_at"] = self._now()

    def replied(self) -> None:
        self._data["last_reply_at"] = self._now()

    def error(self) -> None:
        self._errors.append(self._now())

    def flush(self, force: bool = False) -> None:
        now = self._now()
        if not force and now - self._last_flush < FLUSH_INTERVAL:
            return
        while self._errors and now - self._errors[0] > ERROR_WINDOW:
            self._errors.popleft()
        self._data["errors_last_hour"] = len(self._errors)
        self._data["heartbeat_at"] = now
        self._last_flush = now
        try:
            write_json_atomic(self._path, self._data)
        except OSError:
            # полный диск или чужой владелец тома не причина останавливать главный цикл
            log.warning("Не удалось записать статус в %s", self._path, exc_info=True)


class InboxMark:
    """`state/inbox.json` — время последнего изменения переписки: по нему мессенджер админки тут же перечитывает чат.
    Ни текста, ни чатов, ни авторов в файле нет: только что что-то пришло."""

    def __init__(self, path: str, now=time.time):
        self._path = path
        self._now = now

    def changed(self) -> None:
        try:
            write_json_atomic(self._path, {"at": self._now()})
        except OSError:
            log.warning("Не удалось записать %s", self._path, exc_info=True)
