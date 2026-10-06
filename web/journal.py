import json
from dataclasses import dataclass

from bot.agent.journal import ActionLog, ActionRecord

OUTCOMES = {
    "replied": ("ответила", ""),
    "needs_confirmation": ("ждёт «да»", ""),
    "confirmed": ("сделано по «да»", "ok"),
    "cancelled": ("отменено", ""),
    "gave_up": ("не успела", "bad"),
    "failed": ("сбой", "bad"),
}
VERDICTS = {"allowed": "разрешён", "refused": "отказ", "confirm": "нужно «да»"}
ROLES = {"owner": "владелец", "trusted": "доверенный"}
PLACES = {"chat": "беседа", "saved": "Избранное"}


@dataclass(frozen=True)
class CallView:
    method: str
    params: tuple[tuple[str, str], ...]
    verdict: str
    reason: str
    status: str
    bad: bool


@dataclass(frozen=True)
class Entry:
    record: ActionRecord
    calls: tuple[CallView, ...]
    outcome: str
    outcome_kind: str
    who: str
    where: str


def shown(value) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)


def call_view(raw) -> CallView:
    """Из записи вызова берутся только известные поля: всё остальное, окажись оно в файле, на страницу не попадёт —
    в результатах вызовов чужая переписка."""
    raw = raw if isinstance(raw, dict) else {}
    params = raw.get("params") if isinstance(raw.get("params"), dict) else {}
    verdict = str(raw.get("verdict") or "")
    ok, code = raw.get("ok"), raw.get("error_code")
    if ok is True:
        status = "выполнен"
    elif ok is False:
        status = f"ошибка {code}" if isinstance(code, int) else "сбой"
    else:
        status = ""
    return CallView(str(raw.get("method") or "—"), tuple((str(name), shown(value)) for name, value in params.items()),
                    VERDICTS.get(verdict, verdict), str(raw.get("reason") or ""), status,
                    ok is False or verdict == "refused")


def entry(record: ActionRecord) -> Entry:
    outcome, kind = OUTCOMES.get(record.outcome, (record.outcome, ""))
    return Entry(record, tuple(call_view(call) for call in record.calls), outcome, kind,
                 ROLES.get(record.role, record.role), PLACES.get(record.place, record.place))


def read_entries(state_dir: str) -> list[Entry]:
    return [entry(record) for record in ActionLog(f"{state_dir}/actions.jsonl").read()]


def reply_ids(state_dir: str, message_id: int) -> tuple[int, ...]:
    """Все части ответа, в который входит это сообщение; пусто — журнал такого ответа не знает."""
    for record in ActionLog(f"{state_dir}/actions.jsonl").read():
        ids = tuple(int(part) for part in record.reply_message_ids)
        if message_id in ids:
            return ids
    return ()
