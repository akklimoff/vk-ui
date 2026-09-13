from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bot.context import ATTACHMENT_LABELS

GROUP_CHAT_PEER_BASE = 2_000_000_000
SERIES_GAP = 300.0
MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
          "сентября", "октября", "ноября", "декабря")
PREVIEW_LABELS = {"photo": "Фотография", "sticker": "Стикер", "voice": "Голосовое сообщение",
                  "doc": "Документ", "video": "Видео", "audio": "Аудиозапись", "link": "Ссылка",
                  "wall": "Запись на стене", "other": "Вложение"}


def is_chat(peer_id: int) -> bool:
    return peer_id >= GROUP_CHAT_PEER_BASE


@dataclass(frozen=True)
class Peer:
    id: int
    title: str
    photo: str = ""
    kind: str = "user"
    online: bool = False
    members: int = 0
    last_seen: float = 0
    sex: int = 0


@dataclass(frozen=True)
class Attachment:
    kind: str
    url: str = ""
    preview: str = ""
    title: str = ""
    duration: int = 0
    transcript: str = ""
    waveform: tuple[int, ...] = ()


@dataclass(frozen=True)
class Quote:
    author: str
    text: str


@dataclass(frozen=True)
class BotMark:
    persona: str
    model: str


@dataclass(frozen=True)
class Message:
    id: int
    ts: float
    from_id: int
    author: str
    photo: str
    text: str
    out: bool
    read: bool
    attachments: tuple[Attachment, ...] = ()
    reply: Quote | None = None
    fwd_count: int = 0
    action: str = ""
    bot: BotMark | None = None


@dataclass(frozen=True)
class Row:
    message: Message
    day: str | None
    head: bool
    unread: bool = False


@dataclass(frozen=True)
class Dialog:
    peer: Peer
    last: Message | None
    unread: int
    muted: bool
    pinned: bool


class Profiles:
    def __init__(self, raw: dict):
        self._users = {p["id"]: p for p in raw.get("profiles") or []}
        self._groups = {-g["id"]: g for g in raw.get("groups") or []}

    def name(self, uid: int) -> str:
        if uid in self._users:
            p = self._users[uid]
            return f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
        if uid in self._groups:
            return self._groups[uid].get("name", f"club{-uid}")
        return f"id{uid}"

    def photo(self, uid: int) -> str:
        return (self._users.get(uid) or self._groups.get(uid) or {}).get("photo_50", "")

    def online(self, uid: int) -> bool:
        return bool((self._users.get(uid) or {}).get("online"))

    def last_seen(self, uid: int) -> float:
        return float(((self._users.get(uid) or {}).get("last_seen") or {}).get("time", 0))

    def sex(self, uid: int) -> int:
        return int((self._users.get(uid) or {}).get("sex", 0))


def attachment_of(att: dict) -> Attachment:
    kind = att.get("type", "")
    body = att.get(kind) or {}
    if kind == "photo":
        sizes = sorted(body.get("sizes") or [], key=lambda s: s.get("width", 0))
        if not sizes:
            return Attachment("photo")
        medium = next((s for s in sizes if s.get("width", 0) >= 600), sizes[-1])
        return Attachment("photo", url=sizes[-1]["url"], preview=medium["url"])
    if kind == "sticker":
        images = body.get("images") or []
        chosen = next((i for i in images if i.get("width") == 256), images[-1] if images else {})
        return Attachment("sticker", url=chosen.get("url", ""))
    if kind == "audio_message":
        done = body.get("transcript_state") == "done"
        return Attachment("voice", url=body.get("link_mp3") or body.get("link_ogg", ""),
                          duration=int(body.get("duration", 0)),
                          transcript=body.get("transcript", "") if done else "",
                          waveform=tuple(int(v) for v in body.get("waveform") or ()))
    if kind == "doc":
        return Attachment("doc", url=body.get("url", ""), title=body.get("title") or "документ")
    if kind == "video":
        images = body.get("image") or []
        return Attachment("video", preview=images[-1]["url"] if images else "", title=body.get("title") or "видео")
    if kind == "audio":
        return Attachment("audio", title=" — ".join(x for x in (body.get("artist"), body.get("title")) if x))
    if kind == "link":
        return Attachment("link", url=body.get("url", ""), title=body.get("title") or body.get("url", ""))
    if kind == "wall":
        return Attachment("wall", title="репост")
    return Attachment("other", title=ATTACHMENT_LABELS.get(kind, "[вложение]").strip("[]"))


def action_text(action: dict | None, profiles: Profiles, from_id: int) -> str:
    if not action:
        return ""
    who = profiles.name(from_id)
    member = profiles.name(action["member_id"]) if action.get("member_id") else ""
    kind = action.get("type", "")
    if kind == "chat_invite_user":
        return f"{who} пригласил(а) {member}" if action.get("member_id") != from_id else f"{who} вернулся(ась) в беседу"
    if kind == "chat_invite_user_by_link":
        return f"{who} вошёл(ла) по ссылке"
    if kind == "chat_kick_user":
        return f"{who} исключил(а) {member}" if action.get("member_id") != from_id else f"{who} вышел(ла) из беседы"
    if kind == "chat_title_update":
        return f"{who} изменил(а) название: {action.get('text', '')}"
    if kind == "chat_pin_message":
        return f"{who} закрепил(а) сообщение"
    return f"{who}: {kind}"


def message_of(msg: dict, profiles: Profiles, me_id: int, out_read: int, marks: dict) -> Message:
    from_id = msg["from_id"]
    out = from_id == me_id
    reply = msg.get("reply_message")
    return Message(
        id=msg["id"], ts=float(msg["date"]), from_id=from_id,
        author=profiles.name(from_id), photo=profiles.photo(from_id),
        text=msg.get("text") or "", out=out, read=out and msg["id"] <= out_read,
        attachments=tuple(attachment_of(a) for a in msg.get("attachments") or []),
        reply=Quote(profiles.name(reply["from_id"]), reply.get("text") or preview_label(reply)) if reply else None,
        fwd_count=len(msg.get("fwd_messages") or []),
        action=action_text(msg.get("action"), profiles, from_id),
        bot=marks.get(msg["id"]),
    )


def preview_label(raw_message: dict) -> str:
    atts = raw_message.get("attachments") or []
    if atts:
        return PREVIEW_LABELS.get(attachment_of(atts[0]).kind, "Вложение")
    return "Пересланные сообщения" if raw_message.get("fwd_messages") else ""


def preview(message: Message) -> str:
    if message.action:
        return message.action
    if message.text:
        return message.text
    if message.attachments:
        return PREVIEW_LABELS.get(message.attachments[0].kind, "Вложение")
    return "Пересланные сообщения" if message.fwd_count else ""


def peer_of(conv: dict, profiles: Profiles) -> Peer:
    peer = conv["peer"]
    pid = peer["id"]
    if peer.get("type") == "chat":
        cs = conv.get("chat_settings") or {}
        return Peer(pid, cs.get("title") or f"беседа {peer.get('local_id', pid)}",
                    (cs.get("photo") or {}).get("photo_50", ""), "chat", False, int(cs.get("members_count", 0)))
    if pid < 0:
        return Peer(pid, profiles.name(pid), profiles.photo(pid), "group")
    return Peer(pid, profiles.name(pid), profiles.photo(pid), "user", profiles.online(pid),
                last_seen=profiles.last_seen(pid), sex=profiles.sex(pid))


def parse_conversations(raw: dict, me_id: int, marks: dict | None = None) -> list[Dialog]:
    profiles = Profiles(raw)
    dialogs = []
    for item in raw.get("items") or []:
        conv = item["conversation"]
        last = item.get("last_message")
        dialogs.append(Dialog(
            peer=peer_of(conv, profiles),
            last=message_of(last, profiles, me_id, int(conv.get("out_read", 0)), marks or {}) if last else None,
            unread=int(conv.get("unread_count", 0)),
            muted=bool((conv.get("push_settings") or {}).get("disabled_forever")),
            pinned=bool((conv.get("sort_id") or {}).get("major_id")),
        ))
    return dialogs


def parse_history(raw: dict, me_id: int, marks: dict | None = None) -> tuple[list[Message], int]:
    profiles = Profiles(raw)
    convs = raw.get("conversations") or []
    out_read = int(convs[0].get("out_read", 0)) if convs else 0
    messages = [message_of(m, profiles, me_id, out_read, marks or {}) for m in raw.get("items") or []]
    return list(reversed(messages)), out_read


def day_label(ts: float, now: float, tz: ZoneInfo) -> str:
    day = datetime.fromtimestamp(ts, tz).date()
    today = datetime.fromtimestamp(now, tz).date()
    if day == today:
        return "сегодня"
    if day == today - timedelta(days=1):
        return "вчера"
    label = f"{day.day} {MONTHS[day.month - 1]}"
    return label if day.year == today.year else f"{label} {day.year}"


WAVE_HEIGHT = 12
WAVE_MAX = 31


def wave_bars(waveform: tuple[int, ...], duration: int) -> tuple[int, ...]:
    """Столбики как у VK: секундное сообщение — 22, длиннее 80 не бывает; значения VK 0…31."""
    n = max(21, min(80, round(duration * 2) + 20))
    if not waveform:
        return (2,) * n
    bars = []
    for i in range(n):
        lo = i * len(waveform) // n
        hi = max((i + 1) * len(waveform) // n, lo + 1)
        chunk = waveform[lo:hi]
        bars.append(max(2, round(sum(chunk) / len(chunk) / WAVE_MAX * WAVE_HEIGHT)))
    return tuple(bars)


def presence(peer: Peer, now: float, tz: ZoneInfo) -> str:
    if peer.online:
        return "онлайн"
    if not peer.last_seen:
        return ""
    was = {1: "была в сети", 2: "был в сети"}.get(peer.sex, "был(а) в сети")
    ago = now - peer.last_seen
    if ago < 60:
        return f"{was} только что"
    if ago < 3600:
        return f"{was} {int(ago // 60)} мин назад"
    at = datetime.fromtimestamp(peer.last_seen, tz)
    return f"{was} {day_label(peer.last_seen, now, tz)} в {at:%H:%M}"


def rows(messages: list[Message], now: float, tz: ZoneInfo, prev: Message | None = None,
         in_read: int | None = None) -> list[Row]:
    """prev — последнее уже отрисованное сообщение: с ним склеивается серия и день первого нового.
    in_read — последнее прочитанное входящее: перед первым входящим новее него встаёт разделитель."""
    result: list[Row] = []
    prev_day = day_label(prev.ts, now, tz) if prev else None
    unread_pending = in_read is not None
    for m in messages:
        day = day_label(m.ts, now, tz)
        new_day = day != prev_day
        head = new_day or prev is None or prev.from_id != m.from_id or m.ts - prev.ts > SERIES_GAP or bool(prev.action)
        unread = unread_pending and not m.out and m.id > in_read
        unread_pending = unread_pending and not unread
        result.append(Row(m, day if new_day else None, head or bool(m.action), unread))
        prev, prev_day = m, day
    return result
