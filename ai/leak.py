import json

# самое длинное имя метода — 34 знака, а обычная речь не делит с правилами и 20 знаков подряд
RULES_RUN = 40
# в личности есть образцы фраз, которыми модель и должна говорить; самая длинная — 115 знаков
PERSONA_RUN = 150
# заметка короче RULES_RUN ловится только целиком, а совсем короткая совпала бы с обычной фразой
SHORT_NOTE = 24


def normalized(text: str) -> str:
    return "".join(ch for ch in text.lower().replace("ё", "е") if ch.isalnum())


def runs(text: str, length: int) -> frozenset[str]:
    return frozenset(text[start:start + length] for start in range(len(text) - length + 1))


def parts_of(value, keys: list[str], values: list[str]) -> None:
    if isinstance(value, dict):
        keys.extend(str(key) for key in value)
        for item in value.values():
            parts_of(item, keys, values)
    elif isinstance(value, (list, tuple)):
        for item in value:
            parts_of(item, keys, values)
    elif isinstance(value, str):
        try:
            # параметры и отдельные значения модель иногда передаёт JSON-строкой
            nested = json.loads(value) if value.lstrip()[:1] in ("{", "[") else None
        except ValueError:
            nested = None
        if isinstance(nested, (dict, list)):
            parts_of(nested, keys, values)
        else:
            values.append(value)


def outgoing(step) -> list[str]:
    """Всё, что из шага модели может уйти наружу: ответ либо строки в аргументах вызовов."""
    if not step.tool_calls:
        return [step.text]
    found: list[str] = []
    for call in step.tool_calls:
        keys: list[str] = []
        values: list[str] = []
        parts_of(call.arguments, keys, values)
        # значения проверяются и склеенными: текст, разложенный по параметрам, остаётся тем же текстом;
        # имена параметров в склейку не идут — подряд они сами повторяют описание инструмента
        found += [*keys, *values, "".join(values)]
    return found


class LeakGuard:
    """Ловит дословный пересказ инструкций: длинный общий кусок после снятия регистра, пробелов и пунктуации."""

    def __init__(self, rules, note: str = "", persona: str = ""):
        self._rules = runs(normalized(" ".join(rules)), RULES_RUN)
        self._persona = runs(normalized(persona), PERSONA_RUN)
        note = normalized(note)
        self._note = note if SHORT_NOTE <= len(note) < RULES_RUN else ""

    def catches(self, text: str) -> bool:
        plain = normalized(text)
        if self._note and self._note in plain:
            return True
        return bool(runs(plain, RULES_RUN) & self._rules or runs(plain, PERSONA_RUN) & self._persona)
