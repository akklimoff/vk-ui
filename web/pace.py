import threading
import time
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar

# лимит VK для токена пользователя — 3 запроса в секунду; окно чуть шире секунды гасит дрожание сети на границе
RATE = 3
WINDOW = 1.1

_background: ContextVar[bool] = ContextVar("vk_background", default=False)


@contextmanager
def background():
    """Запросы к VK внутри — фоновые: обновление списка, поллинг, прогрев. Они уступают место щелчкам пользователя."""
    token = _background.set(True)
    try:
        yield
    finally:
        _background.reset(token)


class Pace:
    """Не больше `rate` стартов запросов к VK за `window` секунд, но сами запросы идут параллельно: долгий
    getConversations не держит открытие чата, как держал общий замок vk_api на всё время HTTP-запроса.

    Фоновым достаётся на одно место в окне меньше, и пока ждёт хоть один запрос пользователя, фон не стартует:
    щелчок не стоит в очереди за обновлениями списка."""

    def __init__(self, rate: int = RATE, window: float = WINDOW, now=time.monotonic):
        self._rate = rate
        self._window = window
        self._now = now
        self._starts: deque[float] = deque()
        self._urgent = 0
        self._cond = threading.Condition()

    def acquire(self) -> None:
        bg = _background.get()
        limit = max(1, self._rate - 1) if bg else self._rate
        with self._cond:
            if not bg:
                self._urgent += 1
            try:
                while True:
                    now = self._now()
                    while self._starts and now - self._starts[0] >= self._window:
                        self._starts.popleft()
                    if len(self._starts) < limit and not (bg and self._urgent):
                        self._starts.append(now)
                        return
                    wait = self._window - (now - self._starts[0]) if len(self._starts) >= limit else self._window
                    self._cond.wait(max(wait, 0.01))
            finally:
                if not bg:
                    self._urgent -= 1
                    self._cond.notify_all()
