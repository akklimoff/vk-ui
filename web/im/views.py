from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from web.humanize import mmss, plural

GROUP_CHAT_PEER_BASE = 2_000_000_000
ATTACHMENT_LABELS = {
    "photo": "[фото]",
    "video": "[видео]",
    "audio_message": "[голосовое]",
    "audio": "[аудио]",
    "sticker": "[стикер]",
    "doc": "[документ]",
    "link": "[ссылка]",
    "graffiti": "[граффити]",
    "wall": "[репост]",
    "wall_reply": "[комментарий]",
    "story": "[история]",
    "gift": "[подарок]",
    "poll": "[опрос]",
    "call": "[звонок]",
    "market": "[товар]",
    "article": "[статья]",
    "audio_playlist": "[плейлист]",
    "money_transfer": "[денежный перевод]",
    "money_request": "[запрос денег]",
    "podcast": "[подкаст]",
    "event": "[мероприятие]",
    "mini_app": "[мини-приложение]",
    "artist": "[исполнитель]",
    "group_call_in_progress": "[групповой звонок]",
}
SERIES_GAP = 300.0
MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
          "сентября", "октября", "ноября", "декабря")
PREVIEW_LABELS = {"photo": "Фотография", "sticker": "Стикер", "voice": "Голосовое сообщение",
                  "doc": "Документ", "video": "Видео", "audio": "Аудиозапись", "link": "Ссылка",
                  "wall": "Запись на стене", "wall_reply": "Комментарий", "story": "История",
                  "gift": "Подарок", "poll": "Опрос", "call": "Звонок", "market": "Товар", "article": "Статья",
                  "audio_playlist": "Плейлист", "graffiti": "Граффити", "money": "Денежный перевод",
                  "other": "Вложение"}
CALL_STATES = {"canceled_by_initiator": "Отменён", "canceled_by_receiver": "Отклонён", "busy": "Занято"}
PHOTO_PREVIEW = 600
PHOTO_TILE = 300


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
    width: int = 0
    height: int = 0
    subtitle: str = ""
    href: str = ""
    lines: tuple[str, ...] = ()
    post: "Post | None" = None

    def fit(self, box: int) -> tuple[int, int]:
        """Размер превью в рамке box×box: заранее известный размер не даёт ленте прыгать, пока картинка грузится."""
        if not self.width or not self.height:
            return box, box
        scale = min(1.0, box / self.width, box / self.height)
        return max(1, round(self.width * scale)), max(1, round(self.height * scale))


@dataclass(frozen=True)
class Post:
    author: str
    photo: str
    ts: float
    text: str
    attachments: tuple[Attachment, ...]
    href: str
    original: "Post | None" = None


@dataclass(frozen=True)
class Forward:
    from_id: int
    author: str
    photo: str
    ts: float
    text: str
    attachments: tuple[Attachment, ...] = ()
    forwards: tuple["Forward", ...] = ()


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
    forwards: tuple[Forward, ...] = ()
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
        return f"club{-uid}" if uid < 0 else f"id{uid}"

    def photo(self, uid: int) -> str:
        return (self._users.get(uid) or self._groups.get(uid) or {}).get("photo_50", "")

    def online(self, uid: int) -> bool:
        return bool((self._users.get(uid) or {}).get("online"))

    def last_seen(self, uid: int) -> float:
        return float(((self._users.get(uid) or {}).get("last_seen") or {}).get("time", 0))

    def sex(self, uid: int) -> int:
        return int((self._users.get(uid) or {}).get("sex", 0))


def web_link(url) -> str:
    """Адрес из VK попадает в href: всё, кроме http(s), ссылкой не становится."""
    return url if isinstance(url, str) and url.startswith(("https://", "http://")) else ""


def best_size(sizes: list, at_least: int, key: str = "url") -> tuple[str, int, int]:
    """Наименьший размер не уже at_least, иначе самый большой; у документов адрес лежит в src, а не в url."""
    usable = sorted((s for s in sizes or [] if s.get(key)), key=lambda s: s.get("width") or 0)
    if not usable:
        return "", 0, 0
    chosen = next((s for s in usable if (s.get("width") or 0) >= at_least), usable[-1])
    return chosen[key], int(chosen.get("width") or 0), int(chosen.get("height") or 0)


def file_size(size: int) -> str:
    if size < 1024 * 1024:
        return f"{max(1, round(size / 1024))} КБ"
    return f"{size / 1024 / 1024:.1f} МБ"


def domain(url: str) -> str:
    try:
        return urlsplit(url).hostname or ""
    except ValueError:
        return ""


def author_of(body: dict, profiles: "Profiles") -> tuple[str, str]:
    """Автор записи: VK кладёт его в from, а если нет — его ищут в profiles/groups ответа."""
    who = body.get("from") or {}
    name = who.get("name") or " ".join(x for x in (who.get("first_name"), who.get("last_name")) if x)
    uid = body.get("from_id") or body.get("owner_id") or 0
    return name or profiles.name(uid), who.get("photo_50") or profiles.photo(uid)


def post_of(body: dict, profiles: "Profiles") -> Post:
    author, photo = author_of(body, profiles)
    owner = body.get("owner_id") or body.get("to_id") or body.get("from_id")
    history = body.get("copy_history") or []
    return Post(author=author, photo=photo, ts=float(body.get("date", 0)), text=body.get("text") or "",
                attachments=tuple(attachment_of(a, profiles) for a in body.get("attachments") or []),
                href=f"https://vk.com/wall{owner}_{body['id']}" if owner and body.get("id") else "",
                original=post_of(history[0], profiles) if history else None)


def photo_of(body: dict, at_least: int = PHOTO_PREVIEW) -> Attachment:
    full = web_link(best_size(body.get("sizes"), 10 ** 6)[0])
    preview, width, height = best_size(body.get("sizes"), at_least)
    if not full:
        return Attachment("photo", title="Фотография")
    return Attachment("photo", url=full, preview=web_link(preview) or full, width=width, height=height)


def attachment_of(att: dict, profiles: "Profiles | None" = None) -> Attachment:
    """Вложение, которое не разобралось, становится «Вложением»: иначе одно кривое поле VK роняет весь чат и список диалогов."""
    try:
        return parse_attachment(att, profiles or Profiles({}))
    except (KeyError, TypeError, ValueError, AttributeError):
        return Attachment("other", title="Вложение")


def parse_attachment(att: dict, profiles: "Profiles") -> Attachment:
    kind = att.get("type", "")
    body = att.get(kind) or {}
    if kind == "photo":
        return photo_of(body)
    if kind == "sticker":
        images = body.get("images") or []
        chosen = next((i for i in images if i.get("width") == 256), images[-1] if images else {})
        return Attachment("sticker", url=chosen.get("url", ""), title="Стикер")
    if kind == "graffiti":
        return Attachment("graffiti", url=web_link(body.get("url")), width=int(body.get("width") or 0),
                          height=int(body.get("height") or 0), title="Граффити")
    if kind == "audio_message":
        done = body.get("transcript_state") == "done"
        return Attachment("voice", url=body.get("link_mp3") or body.get("link_ogg", ""),
                          duration=int(body.get("duration") or 0),
                          transcript=body.get("transcript", "") if done else "",
                          waveform=tuple(int(v) for v in body.get("waveform") or ()))
    if kind == "doc":
        preview, width, height = best_size(((body.get("preview") or {}).get("photo") or {}).get("sizes"),
                                           PHOTO_PREVIEW, "src")
        details = " · ".join(x for x in ((body.get("ext") or "").upper(),
                                         file_size(body["size"]) if body.get("size") else "") if x)
        return Attachment("doc", url=web_link(body.get("url")), href=web_link(body.get("url")),
                          title=body.get("title") or "документ", subtitle=details, preview=web_link(preview),
                          width=width, height=height)
    if kind == "video":
        preview, width, height = best_size(body.get("image"), 320)
        owner, vid = body.get("owner_id"), body.get("id")
        return Attachment("video", preview=preview, width=width, height=height, title=body.get("title") or "видео",
                          duration=int(body.get("duration") or 0),
                          href=f"https://vk.com/video{owner}_{vid}" if owner and vid else "")
    if kind == "audio":
        return Attachment("audio", title=body.get("title") or "аудиозапись", subtitle=body.get("artist") or "",
                          duration=int(body.get("duration") or 0))
    if kind == "link":
        url = web_link(body.get("url"))
        preview, width, height = best_size((body.get("photo") or {}).get("sizes"), 150)
        return Attachment("link", url=url, href=url, title=body.get("title") or body.get("url", ""),
                          subtitle=body.get("caption") or domain(url), preview=preview, width=width, height=height)
    if kind == "wall":
        return Attachment("wall", title="Запись на стене", post=post_of(body, profiles))
    if kind == "wall_reply":
        owner, post, reply = body.get("owner_id"), body.get("post_id"), body.get("id")
        href = f"https://vk.com/wall{owner}_{post}" if owner and post else ""
        href += f"?reply={reply}" if href and reply else ""
        return Attachment("wall_reply", title="Комментарий", subtitle=body.get("text") or "", href=href)
    if kind == "story":
        owner, sid = body.get("owner_id"), body.get("id")
        href = f"https://vk.com/story{owner}_{sid}" if owner and sid else ""
        if body.get("is_expired") or body.get("is_deleted") or body.get("can_see") == 0:
            return Attachment("story", title="История недоступна", href=href)
        media = (body.get("photo") or {}).get("sizes") if body.get("type") == "photo" else (body.get("video") or {}).get("image")
        preview, width, height = best_size(media, 300)
        return Attachment("story", title="История", preview=preview, width=width, height=height, href=href)
    if kind == "gift":
        return Attachment("gift", title="Подарок", url=web_link(body.get("thumb_256") or body.get("thumb_96")))
    if kind == "poll":
        votes = int(body.get("votes") or 0)
        answers = tuple(f"{a.get('text', '')} — {round(float(a.get('rate') or 0))}%" for a in body.get("answers") or [])
        label = "Анонимный опрос" if body.get("anonymous") else "Опрос"
        return Attachment("poll", title=body.get("question") or "Опрос", lines=answers,
                          subtitle=f"{label} · {plural(votes, 'голос', 'голоса', 'голосов')}")
    if kind == "call":
        state = body.get("state", "")
        detail = mmss(int(body.get("duration") or 0)) if state == "reached" else CALL_STATES.get(state, "Без ответа")
        return Attachment("call", title="Видеозвонок" if body.get("video") else "Звонок", subtitle=detail)
    if kind == "market":
        owner, mid = body.get("owner_id"), body.get("id")
        return Attachment("market", title=body.get("title") or "Товар", subtitle=(body.get("price") or {}).get("text", ""),
                          preview=web_link(body.get("thumb_photo")),
                          href=f"https://vk.com/product{owner}_{mid}" if owner and mid else "")
    if kind == "article":
        preview, width, height = best_size((body.get("photo") or {}).get("sizes"), 150)
        return Attachment("article", title=body.get("title") or "Статья", subtitle=body.get("owner_name") or "",
                          preview=preview, href=web_link(body.get("view_url") or body.get("url")))
    if kind == "audio_playlist":
        owner, pid = body.get("owner_id"), body.get("id")
        return Attachment("audio_playlist", title=body.get("title") or "Плейлист", subtitle="Плейлист",
                          href=f"https://vk.com/music/playlist/{owner}_{pid}" if owner and pid else "")
    if kind in ("money_transfer", "money_request"):
        return Attachment("money", title="Денежный перевод" if kind == "money_transfer" else "Запрос денег",
                          subtitle=(body.get("amount") or {}).get("text", ""))
    return Attachment("other", title=ATTACHMENT_LABELS.get(kind, "[вложение]").strip("[]").capitalize())


def parse_photos(raw: dict) -> tuple[list[Attachment], str]:
    photos, items = [], raw.get("items") or []
    for item in items:
        att = item.get("attachment") or {}
        if att.get("type") == "photo":
            photo = photo_of(att.get("photo") or {}, PHOTO_TILE)
            if photo.url:
                photos.append(photo)
    return photos, (raw.get("next_from") or "") if items else ""


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


def forward_of(msg: dict, profiles: Profiles) -> Forward:
    from_id = msg.get("from_id", 0)
    return Forward(from_id=from_id, author=profiles.name(from_id), photo=profiles.photo(from_id),
                   ts=float(msg.get("date", 0)), text=msg.get("text") or "",
                   attachments=tuple(attachment_of(a, profiles) for a in msg.get("attachments") or []),
                   forwards=forwards_of(msg, profiles))


def forwards_of(msg: dict, profiles: Profiles) -> tuple[Forward, ...]:
    return tuple(forward_of(f, profiles) for f in msg.get("fwd_messages") or [])


def message_of(msg: dict, profiles: Profiles, me_id: int, out_read: int, marks: dict) -> Message:
    from_id = msg["from_id"]
    out = from_id == me_id
    reply = msg.get("reply_message")
    return Message(
        id=msg["id"], ts=float(msg["date"]), from_id=from_id,
        author=profiles.name(from_id), photo=profiles.photo(from_id),
        text=msg.get("text") or "", out=out, read=out and msg["id"] <= out_read,
        attachments=tuple(attachment_of(a, profiles) for a in msg.get("attachments") or []),
        reply=Quote(profiles.name(reply["from_id"]), reply.get("text") or preview_label(reply)) if reply else None,
        forwards=forwards_of(msg, profiles),
        action=action_text(msg.get("action"), profiles, from_id),
        bot=marks.get(msg["id"]),
    )


def attachments_label(attachments: tuple[Attachment, ...] | list[Attachment], forwards: int) -> str:
    if attachments:
        kinds = {a.kind for a in attachments}
        if kinds == {"photo"} and len(attachments) > 1:
            return plural(len(attachments), "фотография", "фотографии", "фотографий")
        return PREVIEW_LABELS.get(attachments[0].kind, "Вложение")
    if forwards == 1:
        return "Пересланное сообщение"
    return plural(forwards, "пересланное сообщение", "пересланных сообщения", "пересланных сообщений") if forwards else ""


def preview_label(raw_message: dict) -> str:
    atts = [attachment_of(a) for a in raw_message.get("attachments") or []]
    return attachments_label(atts, len(raw_message.get("fwd_messages") or []))


def preview(message: Message) -> str:
    if message.action:
        return message.action
    if message.text:
        return message.text
    return attachments_label(message.attachments, len(message.forwards))


def when(ts: float, now: float, tz: ZoneInfo) -> str:
    return f"{day_label(ts, now, tz)} в {datetime.fromtimestamp(ts, tz):%H:%M}"


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
