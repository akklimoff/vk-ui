import math
from dataclasses import dataclass

from bot.agent import gate
from bot.agent.journal import moment
from bot.agent.rejections import QUEUE_FULL, RATE_LIMITED, Rejection, read_rejections
from bot.status import read_json
from web.journal import Entry, read_entries, shown
from web.services import model_label
from web.trust import TrustLists, is_chat

CONNECTED_WITHIN = 90.0
# бот пишет статус раз в 5 секунд, но между записями может до 35 секунд ждать ответа VK
HEARTBEAT_WITHIN = 60.0

REASONS = {
    gate.CHAT_NOT_TRUSTED: "беседа не в доверенных",
    gate.USER_NOT_TRUSTED: "человек не в доверенных",
    gate.PAUSED: "пауза",
    gate.PRIVATE_DIALOG: "личный диалог: агент работает только в беседах",
    gate.COMMUNITY_SENDER: "пишет сообщество",
    gate.ADDRESSED_TO_BOTS: "сообщение со слешем — оно для ботов",
    gate.NO_SENDER: "у события нет автора",
    gate.NO_TAG: "нет обращения",
    RATE_LIMITED: "слишком часто: сработал лимит частоты",
    QUEUE_FULL: "очередь просьб была полна",
}


@dataclass(frozen=True)
class PendingView:
    peer_id: int
    user_id: int
    title: str
    params: tuple[tuple[str, str], ...]
    seconds_left: float


@dataclass(frozen=True)
class RejectionView:
    ts: float
    peer_id: int
    from_id: int
    reason: str
    count: int
    trustable: bool


def pending_now(state_dir: str, now: float) -> tuple[PendingView, ...]:
    data = read_json(f"{state_dir}/pending.json", {})
    rows = data.get("pending") if isinstance(data, dict) else None
    waiting = []
    for raw in rows if isinstance(rows, list) else []:
        try:
            left = float(raw["expires_at"]) - now
            params = raw.get("params") if isinstance(raw.get("params"), dict) else {}
            view = PendingView(int(raw["peer_id"]), int(raw["user_id"]), str(raw.get("title") or raw.get("method") or ""),
                               tuple((str(name), shown(value)) for name, value in params.items()), round(left, 1))
        except (AttributeError, KeyError, OverflowError, TypeError, ValueError):
            continue
        if math.isfinite(left) and left > 0:
            waiting.append(view)
    return tuple(waiting)


def paused_peers(runtime: dict) -> set[int]:
    try:
        return {int(peer) for peer in runtime.get("paused_peers") or []}
    except (TypeError, ValueError):
        return set()


def still_holds(row: Rejection, lists: TrustLists, runtime: dict, trusted_ids: frozenset[int] = frozenset()) -> bool:
    """Отказ, причину которого уже устранили, только путал бы: беседу добавили, а строка всё висит.
    `trusted_ids` — те же люди, что в `lists.users`, но с никами, уже разрешёнными в id: в самих списках ник — строка."""
    if row.reason == gate.CHAT_NOT_TRUSTED:
        return row.peer_id not in lists.peers
    if row.reason == gate.USER_NOT_TRUSTED:
        return row.from_id not in lists.users and row.from_id not in trusted_ids
    if row.reason == gate.PAUSED:
        return bool(runtime.get("paused")) or row.peer_id in paused_peers(runtime)
    return True


def trustable(row: Rejection, lists: TrustLists) -> bool:
    return row.reason == gate.CHAT_NOT_TRUSTED and is_chat(row.peer_id) and row.peer_id not in lists.peers


def recent_rejections(state_dir: str, lists: TrustLists, runtime: dict, limit: int = 10,
                      trusted_ids: frozenset[int] = frozenset()) -> tuple[RejectionView, ...]:
    rows = [row for row in read_rejections(f"{state_dir}/rejections.json")
            if still_holds(row, lists, runtime, trusted_ids)]
    return tuple(RejectionView(row.ts, row.peer_id, row.from_id, REASONS.get(row.reason, row.reason), row.count,
                               trustable(row, lists)) for row in rows[:limit])


@dataclass(frozen=True)
class StatusView:
    connected: bool
    me_id: int | None
    me_name: str
    model: str
    next_model: str
    active_persona: str
    paused: bool
    errors_last_hour: int
    last_event_ago: float | None
    last_reply_ago: float | None
    uptime: float | None
    last: Entry | None
    pending: tuple[PendingView, ...]
    rejections: tuple[RejectionView, ...]


def status_view(state_dir: str, now: float, runtime: dict | None = None, lists: TrustLists | None = None,
                trusted_ids: frozenset[int] = frozenset()) -> StatusView:
    """`runtime` — желаемое состояние из runtime.json; status.json отстаёт от него на flush бота.
    `lists` и `trusted_ids` — нынешние списки доверия: по ним прячутся отказы, причину которых уже устранили."""
    d = read_json(f"{state_dir}/status.json", {})
    d = d if isinstance(d, dict) else {}
    desired = d if runtime is None else runtime
    entries = read_entries(state_dir)

    def ago(ts):
        return round(now - ts, 1) if moment(ts) else None

    def errors() -> int:
        try:
            return int(d.get("errors_last_hour") or 0)
        except (TypeError, ValueError):
            return 0

    def fresh(ts, within: float) -> bool:
        return moment(ts) and now - ts < within

    last_event = d.get("last_event_at")
    if "heartbeat_at" in d:
        connected = fresh(d["heartbeat_at"], HEARTBEAT_WITHIN) and fresh(d.get("last_poll_at"), CONNECTED_WITHIN)
    else:
        # статус от бота, который ещё не писал heartbeat: о связи судим по последнему сообщению
        connected = fresh(last_event, CONNECTED_WITHIN)
    answered = str(d.get("model") or "") or next((e.record.model for e in entries if e.record.model), "")
    chosen = str(desired.get("active_model") or "")
    return StatusView(
        connected=connected,
        me_id=d.get("me_id"), me_name=str(d.get("me_name") or ""),
        model=model_label(answered) if answered else "",
        next_model=model_label(chosen) if chosen and chosen != answered else "",
        active_persona=str(desired.get("active_persona") or ""), paused=bool(desired.get("paused")),
        errors_last_hour=errors(),
        last_event_ago=ago(last_event), last_reply_ago=ago(d.get("last_reply_at")),
        uptime=ago(d.get("started_at")),
        last=entries[0] if entries else None,
        pending=pending_now(state_dir, now),
        rejections=recent_rejections(state_dir, lists or TrustLists(), desired, trusted_ids=trusted_ids),
    )
