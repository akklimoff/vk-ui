import os

from bot.agent.journal import ActionLog, ActionRecord
from web.im.views import BotMark
from web.services import model_label


def bot_marks(records: list[ActionRecord]) -> dict[int, BotMark]:
    marks = {}
    for record in records:
        mark = BotMark(record.persona or "по умолчанию", model_label(record.model) if record.model else "")
        for message_id in record.reply_message_ids:
            marks[int(message_id)] = mark
    return marks


class MarksFile:
    """Метки ответов агента из журнала. Журнал только растёт, а спрашивают его на каждом тике поллинга —
    разбор повторяется лишь при смене размера или mtime файла."""

    def __init__(self, path: str):
        self._path = path
        self._seen: tuple[int, int] | None = None
        self._marks: dict[int, BotMark] = {}

    def current(self) -> dict[int, BotMark]:
        try:
            stat = os.stat(self._path)
            seen = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            seen = None
        if seen != self._seen:
            self._marks = bot_marks(ActionLog(self._path).read())
            self._seen = seen
        return self._marks
