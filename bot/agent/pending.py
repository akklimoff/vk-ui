import logging
import time
from dataclasses import dataclass

from bot.agent.journal import journal_value
from bot.status import write_json_atomic

log = logging.getLogger("vk-bot")

YES, NO = "yes", "no"
YES_WORDS = frozenset({"да", "подтверждаю"})
NO_WORDS = frozenset({"нет", "отмена"})
AROUND = " \t\n.,!?…"


@dataclass(frozen=True)
class Pending:
    method: str
    params: dict
    title: str


def verdict_of(text: str | None) -> str | None:
    word = (text or "").strip(AROUND).lower()
    if word in YES_WORDS:
        return YES
    if word in NO_WORDS:
        return NO
    return None


class PendingStore:
    """Не больше одного ожидающего «да» действия на пару (беседа, человек); «да» спрашивается только в «Избранном».
    Живёт в памяти: перезапуск отменяет всё.
    Файл-зеркало нужен только админке и повторяет то, что человеку уже показано в вопросе «да»."""

    def __init__(self, ttl: float, clock=time.monotonic, mirror: str | None = None, wall=time.time, secrets=()):
        self._ttl = ttl
        self._clock = clock
        self._mirror = mirror
        self._wall = wall
        self._secrets = secrets
        self._waiting: dict[tuple[int, int], tuple[Pending, float, float]] = {}
        self._reflect()

    def put(self, peer_id: int, user_id: int, pending: Pending) -> None:
        self._waiting[(peer_id, user_id)] = (pending, self._clock() + self._ttl, self._wall())
        self._reflect()

    def take(self, peer_id: int, user_id: int) -> Pending | None:
        found = self._waiting.pop((peer_id, user_id), None)
        if found is None:
            return None
        self._reflect()
        pending, expires_at, _ = found
        return pending if self._clock() < expires_at else None

    def _reflect(self) -> None:
        now = self._clock()
        self._waiting = {key: entry for key, entry in self._waiting.items() if now < entry[1]}
        if self._mirror is None:
            return
        rows = [{"peer_id": peer_id, "user_id": user_id, "method": pending.method, "title": pending.title,
                 "params": {name: journal_value(value, self._secrets) for name, value in pending.params.items()},
                 "asked_at": asked_at, "expires_at": asked_at + self._ttl}
                for (peer_id, user_id), (pending, _, asked_at) in self._waiting.items()]
        try:
            write_json_atomic(self._mirror, {"pending": rows})
        except OSError:
            log.warning("Не удалось записать зеркало ожидающих «да» в %s", self._mirror, exc_info=True)
