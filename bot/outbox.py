import random
import threading
from typing import Callable


class Outbox:
    """Что отправил сам агент: эхо этих сообщений из long poll — не просьба владельца."""

    def __init__(self, keep: int = 2000):
        self._lock = threading.Lock()
        self._keep = keep
        self._marks: dict[tuple[str, int], None] = {}

    def send(self, deliver: Callable[[int], object]):
        # эхо может прийти раньше ответа VK на отправку: random_id записан до неё, а owns ждёт тот же замок
        # и узнаёт сообщение по id, даже если long poll random_id не вернул
        with self._lock:
            random_id = random.getrandbits(31) or 1
            self._remember("random", random_id)
            result = deliver(random_id)
            # с peer_ids VK отвечает списком: по одной записи на адресата
            sent = result if isinstance(result, list) else [{"message_id": result}]
            for item in sent:
                message_id = item.get("message_id") if isinstance(item, dict) else None
                if type(message_id) is int:
                    self._remember("message", message_id)
            return result

    def owns(self, message_id, random_id) -> bool:
        with self._lock:
            return any(type(value) is int and value and (kind, value) in self._marks
                       for kind, value in (("message", message_id), ("random", random_id)))

    def _remember(self, kind: str, value: int) -> None:
        self._marks[(kind, value)] = None
        while len(self._marks) > self._keep:
            del self._marks[next(iter(self._marks))]
