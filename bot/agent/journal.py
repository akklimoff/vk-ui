import json
import math
import os
from dataclasses import asdict, dataclass

from common.redact import sanitize_reply

PARAM_LIMIT = 500


@dataclass(frozen=True)
class ActionRecord:
    ts: float
    peer_id: int
    from_id: int
    role: str
    place: str
    message_id: int
    request: str
    calls: tuple[dict, ...]
    outcome: str
    reply: str
    reply_message_ids: tuple[int, ...]
    steps: int
    duration_s: float
    model: str
    prompt_tokens: int
    completion_tokens: int
    persona: str
    cached_tokens: int = 0


def journal_value(value, secrets):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    text = sanitize_reply(text, secrets)
    return text if len(text) <= PARAM_LIMIT else text[:PARAM_LIMIT] + "…"


def call_entry(call, secrets=()) -> dict:
    entry = asdict(call)
    entry["params"] = {name: journal_value(value, secrets) for name, value in call.params.items()}
    return entry


def whole(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def moment(value) -> bool:
    # целое вне этих границ при вычитании из float бросает OverflowError
    return (isinstance(value, float) and math.isfinite(value)) or (whole(value) and abs(value) < 10 ** 18)


def load_record(raw: dict) -> ActionRecord:
    """Строка журнала с полями не того типа — ValueError: читатели сравнивают время и номера, не проверяя их."""
    record = ActionRecord(**{**raw, "calls": tuple(raw["calls"]), "reply_message_ids": tuple(raw["reply_message_ids"])})
    numbers = (record.ts, record.duration_s)
    ids = (record.peer_id, record.from_id, record.message_id, record.steps, record.prompt_tokens,
           record.completion_tokens, record.cached_tokens, *record.reply_message_ids)
    texts = (record.role, record.place, record.request, record.outcome, record.reply, record.model, record.persona)
    if not (all(map(moment, numbers)) and all(map(whole, ids)) and all(isinstance(text, str) for text in texts)):
        raise ValueError("в записи журнала поле не того типа")
    return record


class ActionLog:
    """Журнал просьб к агенту: одна строка JSON на просьбу, хранятся последние keep."""

    def __init__(self, path: str, keep: int = 500):
        self._path = path
        self._keep = keep

    def append(self, record: ActionRecord) -> None:
        lines = self._lines()
        lines.append(json.dumps(asdict(record), ensure_ascii=False))
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        tmp = f"{self._path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("\n".join(lines[-self._keep:]) + "\n")
        os.replace(tmp, self._path)

    def read(self) -> list[ActionRecord]:
        records = []
        for line in self._lines():
            try:
                records.append(load_record(json.loads(line)))
            except (ValueError, TypeError, KeyError):
                continue
        return list(reversed(records))

    def _lines(self) -> list[str]:
        try:
            with open(self._path, encoding="utf-8") as f:
                # не splitlines: он режет и по U+2028/U+2029/U+0085, которые json оставляет внутри строки как есть
                return [line for line in f.read().split("\n") if line.strip()]
        except OSError:
            return []
