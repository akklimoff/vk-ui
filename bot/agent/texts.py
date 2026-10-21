import json
from collections import Counter

# тексты, которые пишет код, а не модель: от женского лица, как у персон, и без слов-команд vk-bot в начале
DONE = "Готово."
CANCELLED = "Отменила."
FAILED = "Не получилось, попробуй ещё раз."
GAVE_UP = "Не успела разобраться, попробуй попросить попроще."
STOPPED = "Не получилось: ВКонтакте сейчас не даёт это сделать, попробуй позже."
TOO_LONG = "Ответ не поместился и оборвался, попробуй попросить короче или по частям."
GARBLED = "Сбилась и не смогла ответить, попробуй ещё раз."
INTERRUPTED = "Ответ оборвался на полуслове, попробуй ещё раз."
CHECK_FIRST = "Проверь, прежде чем просить ещё раз."


def shown(value) -> str:
    """Значение целиком и в одну строку: после «да» уйдёт ровно то, что показано, и оно не изобразит соседние строки."""
    return json.dumps(value, ensure_ascii=False, default=str)


def confirm_text(title: str, params: dict, ttl_seconds: float) -> str:
    minutes = max(1, round(ttl_seconds / 60))
    return "\n".join([
        f"{title}?",
        *(f"{name}: {shown(value)}" for name, value in params.items()),
        f"Тегни меня и напиши «да» — сделаю, «нет» — отменю. Жду {minutes} мин.",
    ])


def listed(done) -> str:
    return ", ".join(f"«{title}» ×{times}" if times > 1 else f"«{title}»" for title, times in Counter(done).items())


def unfinished(done) -> str:
    """Конец просьбы без ответа модели, когда часть действий уже выполнена: повтор вслепую сделал бы их дважды."""
    return f"Довела не до конца. Уже сделано: {listed(done)}. {CHECK_FIRST}"


def unknown(title: str, done=()) -> str:
    before = f" До этого сделано: {listed(done)}." if done else ""
    return f"Сбой на полпути: не знаю, выполнилось ли «{title}».{before} {CHECK_FIRST}"


def cut(text: str) -> str:
    return f"{text}…\n(дальше не поместилось)"


def failed_text(reason: str) -> str:
    return f"Не получилось: {reason}" if reason else FAILED
