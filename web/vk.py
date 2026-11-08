import io
import logging
from contextlib import nullcontext

import vk_api
from requests.adapters import HTTPAdapter
from vk_api import VkUpload
from vk_api.longpoll import VkEventType, VkLongPoll
from vk_api.utils import get_random_id

from web.pace import Pace

log = logging.getLogger("vk-ui")

PROFILE_FIELDS = "photo_50,photo_100,online,last_seen,sex,screen_name"
ARCHIVE_PAGE = 200
# фильтра archive нет в 5.92, которую vk_api шлёт по умолчанию: на ней VK отвечает [15] Access denied
ARCHIVE_API_VERSION = "5.199"
# чтение — на свежей версии: только в ней у видео есть type, по которому кружок отличается от обычного видео
READ_API_VERSION = "5.199"
ACCESS_DENIED = 15
# беседы и их последние сообщения одним запросом: execute занимает в лимите VK одно место, а не два
CHANGED_DIALOGS = """var c = API.messages.getConversationsById({"peer_ids": Args.peers, "extended": 1, "fields": Args.fields});
var m = API.messages.getById({"message_ids": c.items@.last_message_id, "extended": 1, "fields": Args.fields});
return {"conversations": c, "messages": m};"""


def voice_attachment(saved: dict) -> str:
    doc = saved["audio_message"]
    key = doc.get("access_key")
    return f"audio_message{doc['owner_id']}_{doc['id']}" + (f"_{key}" if key else "")


MESSAGE_EVENTS = frozenset({VkEventType.MESSAGE_FLAGS_REPLACE, VkEventType.MESSAGE_FLAGS_SET,
                            VkEventType.MESSAGE_FLAGS_RESET, VkEventType.MESSAGE_NEW, VkEventType.MESSAGE_EDIT,
                            VkEventType.READ_ALL_INCOMING_MESSAGES, VkEventType.READ_ALL_OUTGOING_MESSAGES,
                            VkEventType.PEER_DELETE_ALL, VkEventType.PEER_RESTORE_ALL, VkEventType.CHAT_UPDATE})
# соединение и чтение: сам vk_api ждёт ответа VK без срока
HTTP_TIMEOUT = (5.0, 30.0)


class TimeoutAdapter(HTTPAdapter):
    def __init__(self, timeout):
        super().__init__()
        self._timeout = timeout

    def send(self, request, **kwargs):
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = self._timeout
        return super().send(request, **kwargs)


class PacedVkApi(vk_api.VkApi):
    """vk_api держит общий замок на всё время HTTP-запроса и выдерживает 0,34 с между ответами: медленный
    getConversations (1,5 с) задерживал каждое открытие чата. Здесь частоту держит Pace, а запросы идут параллельно."""

    def __init__(self, *args, pace: Pace, **kwargs):
        super().__init__(*args, **kwargs)
        self.pace = pace
        self.RPS_DELAY = 0
        self.lock = nullcontext()

    def method(self, method, values=None, **kwargs):
        self.pace.acquire()
        return super().method(method, values, **kwargs)


def changed_peers(events) -> frozenset[int] | None:
    """Чаты, в которых пачка long poll что-то поменяла; None — событие без чата или неразобранное, и непонятно,
    что перечитывать."""
    peers = set()
    for e in events:
        if e is None:
            return None
        if e.type not in MESSAGE_EVENTS:
            continue
        if e.peer_id is None:
            return None
        peers.add(int(e.peer_id))
    return frozenset(peers)


class LongPoll(VkLongPoll):
    polled = None
    changed = None

    def check(self):
        ts = self.ts
        events = super().check()
        if self.polled is not None:
            self.polled()
        # failed 1 и 3: VK выдал новый ts без событий за пропущенное — что изменилось, неизвестно
        peers = None if not events and self.ts != ts else changed_peers(events)
        if self.changed is not None and peers != frozenset():
            # ts уже сдвинут: исключение здесь потеряло бы всю пачку событий
            try:
                self.changed(peers)
            except Exception as e:
                log.warning("Сигнал о новых сообщениях не передан: %s", type(e).__name__)
        return events

    def _parse_event(self, raw_event):
        # check() сдвигает ts раньше разбора: исключение здесь унесло бы всю пачку событий безвозвратно
        try:
            return super()._parse_event(raw_event)
        except Exception as e:
            code = raw_event[0] if isinstance(raw_event, list) and raw_event else None
            log.warning("Событие long poll не разобрано и пропущено: код %s, %s", code, type(e).__name__)
            return None


class VkClient:
    def __init__(self, token: str, timeout=HTTP_TIMEOUT, pace: Pace | None = None):
        self._session = PacedVkApi(token=token, pace=pace or Pace())
        # зависшее соединение навсегда заняло бы поток запроса или long poll
        for scheme in ("https://", "http://"):
            self._session.http.mount(scheme, TimeoutAdapter(timeout))
        self.api = self._session.get_api()
        self._upload = VkUpload(self._session)
        for scheme in ("https://", "http://"):
            self._upload.http.mount(scheme, TimeoutAdapter(timeout))
        self.me_id = self.api.users.get()[0]["id"]
        self._longpoll: LongPoll | None = None

    def listen(self, polled=None, changed=None):
        """`polled` зовётся после каждого ответа long poll, в том числе пустого: по нему видно, что связь жива;
        `changed(peers)` — раз на пачку, в которой есть новые, изменённые или прочитанные сообщения;
        peers — их чаты или None, если чат события неизвестен."""
        # новый VkLongPoll берёт у VK текущий ts: пересоздание после сбоя потеряло бы всё, что пришло за это время
        fresh = self._longpoll is None
        if fresh:
            self._longpoll = LongPoll(self._session)
        self._longpoll.polled = polled
        self._longpoll.changed = changed
        # пока long poll не слушал, события до его ts никто не видел: всё, что взято у VK раньше, могло устареть
        if fresh and changed is not None:
            changed(None)
        for event in self._longpoll.listen():
            if event is not None and event.type == VkEventType.MESSAGE_NEW:
                yield event

    def delete_message(self, message_id: int) -> None:
        self.api.messages.delete(message_ids=message_id, delete_for_all=1)

    def conversations(self, count: int = 60, offset: int = 0) -> dict:
        return self.api.messages.getConversations(count=count, offset=offset, extended=1, fields=PROFILE_FIELDS,
                                                  v=READ_API_VERSION)

    def changed_dialogs(self, peer_ids) -> dict:
        """Беседы peer_ids с последними сообщениями — в форме ответа getConversations."""
        raw = self.api.execute(code=CHANGED_DIALOGS, peers=",".join(map(str, peer_ids)), fields=PROFILE_FIELDS,
                               v=READ_API_VERSION)
        convs, msgs = raw.get("conversations") or {}, raw.get("messages") or {}
        last = {m["id"]: m for m in msgs.get("items") or []}
        items = [{"conversation": c, **({"last_message": last[c["last_message_id"]]}
                                         if c.get("last_message_id") in last else {})}
                 for c in convs.get("items") or []]
        return {"items": items, "profiles": (convs.get("profiles") or []) + (msgs.get("profiles") or []),
                "groups": (convs.get("groups") or []) + (msgs.get("groups") or [])}

    def video_player(self, owner_id: int, video_id: int, access_key: str = "") -> str:
        full = f"{owner_id}_{video_id}" + (f"_{access_key}" if access_key else "")
        items = self.api.video.get(videos=full, v=READ_API_VERSION).get("items") or []
        return (items[0].get("player") or "") if items else ""

    def archived_peers(self) -> frozenset[int]:
        peers, offset = set(), 0
        while True:
            raw = self.api.messages.getConversations(filter="archive", count=ARCHIVE_PAGE, offset=offset,
                                                     v=ARCHIVE_API_VERSION)
            items = raw.get("items") or []
            peers |= {item["conversation"]["peer"]["id"] for item in items}
            offset += len(items)
            if not items or offset >= int(raw.get("count", 0)):
                return frozenset(peers)

    def history_page(self, peer_id: int, count: int, before_id: int | None = None) -> dict:
        params = dict(peer_id=peer_id, count=count, extended=1, fields=PROFILE_FIELDS, v=READ_API_VERSION)
        if before_id is not None:
            # offset считается от start_message_id: 1 — со следующего более старого сообщения
            params.update(start_message_id=before_id, offset=1)
        return self.api.messages.getHistory(**params)

    def history_media(self, peer_id: int, media_type: str, count: int, start_from: str = "") -> dict:
        params = dict(peer_id=peer_id, media_type=media_type, count=count, photo_sizes=1, preserve_order=1,
                      v=READ_API_VERSION)
        if start_from:
            params["start_from"] = start_from
        return self.api.messages.getHistoryAttachments(**params)

    def search_conversations(self, query: str, count: int) -> dict:
        return self.api.messages.searchConversations(q=query, count=count, extended=1, fields=PROFILE_FIELDS,
                                                     v=READ_API_VERSION)

    def send(self, peer_id: int, text: str = "", reply_to: int | None = None, attachment: str = "") -> int:
        params = dict(peer_id=peer_id, random_id=get_random_id(), message=text)
        if reply_to:
            params["reply_to"] = reply_to
        if attachment:
            params["attachment"] = attachment
        return self.api.messages.send(**params)

    def mark_read(self, peer_id: int) -> None:
        self.api.messages.markAsRead(peer_id=peer_id, mark_conversation_as_read=1)

    def upload_photos(self, peer_id: int, photos: list[tuple[bytes, str]]) -> list[str]:
        attachments = []
        for data, ext in photos:
            buf = io.BytesIO(data)
            # как у голосового: без имени с расширением VkUpload назовёт файл .jpg, и png/gif VK примет криво
            buf.name = f"photo.{ext}"
            # сервер загрузки для сообщений берёт одно фото на запрос: пачка в одном POST потеряла бы все, кроме первого
            for saved in self._upload.photo_messages(buf, peer_id=peer_id):
                key = saved.get("access_key")
                attachments.append(f"photo{saved['owner_id']}_{saved['id']}" + (f"_{key}" if key else ""))
        return attachments

    def upload_voice(self, peer_id: int, data: bytes, ext: str) -> str:
        buf = io.BytesIO(data)
        # FilesOpener берёт расширение из name; без него VK получит file0.jpg и отклонит голосовое
        buf.name = f"voice.{ext}"
        return voice_attachment(self._upload.audio_message(buf, peer_id=peer_id))
