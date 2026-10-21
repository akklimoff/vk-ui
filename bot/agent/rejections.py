import logging
import math
import threading
import time
from dataclasses import asdict, dataclass

from bot.agent.gate import REASONS
from bot.status import read_json, write_json_atomic

log = logging.getLogger("vk-bot")

# просьба прошла фильтр, но до исполнителя не дошла
RATE_LIMITED = "rate_limited"
QUEUE_FULL = "queue_full"
KNOWN_REASONS = (*REASONS, RATE_LIMITED, QUEUE_FULL)


@dataclass(frozen=True)
class Rejection:
    ts: float
    peer_id: int
    from_id: int
    reason: str
    count: int = 1


def read_rejections(path: str) -> list[Rejection]:
    data = read_json(path, {})
    rows = data.get("rejections") if isinstance(data, dict) else None
    found = []
    for raw in rows if isinstance(rows, list) else []:
        try:
            row = Rejection(float(raw["ts"]), int(raw["peer_id"]), int(raw["from_id"]), str(raw["reason"]),
                            int(raw.get("count", 1)))
        except (AttributeError, KeyError, OverflowError, TypeError, ValueError):
            continue
        if row.reason in KNOWN_REASONS and math.isfinite(row.ts):
            found.append(row)
    return sorted(found, key=lambda row: row.ts, reverse=True)


class RejectionLog:
    """Последние сообщения с тегом, на которые агент промолчал: кто, где и почему. Текста сообщения здесь нет:
    содержимое отброшенного события не должно попасть никуда."""

    def __init__(self, path: str, keep: int = 50, now=time.time, flush_interval: float = 5.0):
        self._path = path
        self._keep = keep
        self._now = now
        self._interval = flush_interval
        self._rows = {(row.peer_id, row.from_id, row.reason): row for row in read_rejections(path)}
        self._dirty = False
        self._last_flush: float | None = None
        # note зовут и главный цикл, и поток исполнителя просьб
        self._lock = threading.Lock()

    def note(self, peer_id: int, from_id: int | None, reason: str) -> None:
        key = (peer_id, from_id or 0, reason)
        with self._lock:
            seen = self._rows.pop(key, None)
            self._rows[key] = Rejection(self._now(), key[0], key[1], reason, seen.count + 1 if seen else 1)
            while len(self._rows) > self._keep:
                del self._rows[min(self._rows, key=lambda k: self._rows[k].ts)]
            self._dirty = True

    def flush(self, force: bool = False) -> None:
        with self._lock:
            if not self._dirty:
                return
            now = self._now()
            if not force and self._last_flush is not None and now - self._last_flush < self._interval:
                return
            self._last_flush = now
            self._dirty = False
            rows = [asdict(row) for row in self._rows.values()]
        try:
            write_json_atomic(self._path, {"rejections": rows})
        except OSError:
            log.warning("Не удалось записать отказы в %s", self._path, exc_info=True)
            with self._lock:
                self._dirty = True
