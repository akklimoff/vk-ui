import io
import logging
from contextlib import contextmanager

import requests
import urllib3
import vk_api
from requests.adapters import HTTPAdapter
from vk_api import VkUpload
from vk_api.exceptions import ApiError, ApiHttpError, Captcha, VkApiError
from vk_api.longpoll import VkEventType, VkLongPoll
from vk_api.utils import get_random_id

from bot.agent.pictures import is_photo_url
from bot.outbox import Outbox
from bot.wire import wire_value

log = logging.getLogger("vk-bot")

PROFILE_FIELDS = "photo_50,photo_100,online,last_seen,sex,screen_name"


def voice_attachment(saved: dict) -> str:
    doc = saved["audio_message"]
    key = doc.get("access_key")
    return f"audio_message{doc['owner_id']}_{doc['id']}" + (f"_{key}" if key else "")


# провайдеры принимают картинку до 5 МБ уже в base64, а он на треть длиннее
IMAGE_LIMIT = 3 * 1024 * 1024
IMAGE_EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif", "image/webp": "webp"}
UPLOAD_PARAM = "from_url"
NO_PICTURE = "картинку по этому адресу получить не удалось"
UPLOAD_FAILED = "загрузить картинку не удалось: проверь параметры (фото беседы требует chat_id)"
NO_UPLOAD = "этот метод не принимает from_url"
CAPTCHA_CODE = 14
NETWORK_CODE = -1
BAD_PARAM_CODE = 100
MESSAGE_EVENTS = frozenset({VkEventType.MESSAGE_FLAGS_REPLACE, VkEventType.MESSAGE_FLAGS_SET,
                            VkEventType.MESSAGE_FLAGS_RESET, VkEventType.MESSAGE_NEW, VkEventType.MESSAGE_EDIT,
                            VkEventType.READ_ALL_INCOMING_MESSAGES, VkEventType.READ_ALL_OUTGOING_MESSAGES})
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


class LongPoll(VkLongPoll):
    polled = None
    changed = None

    def check(self):
        events = super().check()
        if self.polled is not None:
            self.polled()
        if self.changed is not None and any(e is not None and e.type in MESSAGE_EVENTS for e in events):
            # ts уже сдвинут: исключение здесь потеряло бы пачку вместе с просьбами к агенту
            try:
                self.changed()
            except Exception as e:
                log.warning("Отметка о новых сообщениях не записана: %s", type(e).__name__)
        return events

    def _parse_event(self, raw_event):
        # check() сдвигает ts раньше разбора: исключение здесь унесло бы всю пачку событий безвозвратно
        try:
            return super()._parse_event(raw_event)
        except Exception as e:
            code = raw_event[0] if isinstance(raw_event, list) and raw_event else None
            log.warning("Событие long poll не разобрано и пропущено: код %s, %s", code, type(e).__name__)
            return None


class VkCallError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(f"VK {code}: {message}")
        self.code = code
        self.message = message


@contextmanager
def vk_errors():
    try:
        yield
    except Captcha:
        raise VkCallError(CAPTCHA_CODE, "VK просит капчу") from None
    except ApiError as e:
        raise VkCallError(e.code, str(e.error.get("error_msg", ""))) from None
    except (requests.RequestException, ApiHttpError):
        raise VkCallError(NETWORK_CODE, "нет связи с ВКонтакте") from None
    except VkApiError as e:
        raise VkCallError(0, str(e)) from None


class VkClient:
    def __init__(self, token: str, outbox: Outbox | None = None, timeout=HTTP_TIMEOUT):
        self._outbox = outbox or Outbox()
        self._session = vk_api.VkApi(token=token)
        # зависшее соединение навсегда заняло бы единственный поток агента
        for scheme in ("https://", "http://"):
            self._session.http.mount(scheme, TimeoutAdapter(timeout))
        self.api = self._session.get_api()
        self._upload = VkUpload(self._session)
        for scheme in ("https://", "http://"):
            self._upload.http.mount(scheme, TimeoutAdapter(timeout))
        self.me_id = self.api.users.get()[0]["id"]
        self._names: dict[int, str] = {}
        self._longpoll: LongPoll | None = None

    def listen(self, polled=None, changed=None):
        """`polled` зовётся после каждого ответа long poll, в том числе пустого: по нему видно, что связь жива;
        `changed` — раз на пачку, в которой есть новые, изменённые или прочитанные сообщения любого чата."""
        # новый VkLongPoll берёт у VK текущий ts: пересоздание после сбоя потеряло бы всё, что пришло за это время
        if self._longpoll is None:
            self._longpoll = LongPoll(self._session)
        self._longpoll.polled = polled
        self._longpoll.changed = changed
        for event in self._longpoll.listen():
            if event is not None and event.type == VkEventType.MESSAGE_NEW:
                yield event

    def set_typing(self, peer_id: int) -> None:
        self.api.messages.setActivity(peer_id=peer_id, type="typing")

    def send_reply(self, peer_id: int, message_id: int, text: str) -> int:
        try:
            return self._outbox.send(lambda random_id: self.api.messages.send(
                peer_id=peer_id, random_id=random_id, reply_to=message_id, message=text))
        except ApiError as e:
            if e.code != BAD_PARAM_CODE:
                raise
            # сообщение с просьбой уже удалили: VK отказал, ничего не отправив, и ответ уходит без цитаты
            return self.send_message(peer_id, text)

    def send_message(self, peer_id: int, text: str) -> int:
        return self._outbox.send(lambda random_id: self.api.messages.send(
            peer_id=peer_id, random_id=random_id, message=text))

    def delete_message(self, message_id: int) -> None:
        self.api.messages.delete(message_ids=message_id, delete_for_all=1)

    def resolve_screen_names(self, screen_names: frozenset[str]) -> frozenset[int]:
        if not screen_names:
            return frozenset()
        users = self.api.users.get(user_ids=",".join(sorted(screen_names)))
        return frozenset(user["id"] for user in users)

    def resolve_name(self, user_id: int) -> str:
        if user_id in self._names:
            return self._names[user_id]
        if user_id < 0:
            group = self.api.groups.getById(group_id=abs(user_id))[0]
            name = group["name"]
        else:
            user = self.api.users.get(user_ids=user_id)[0]
            name = f"{user['first_name']} {user['last_name']}"
        self._names[user_id] = name
        return name

    def replies_to_me(self, message_id: int) -> bool:
        items = self.call("messages.getById", {"message_ids": message_id})["items"]
        reply = items[0].get("reply_message") if items else None
        return bool(reply) and reply.get("from_id") == self.me_id

    def conversations(self, count: int = 60, offset: int = 0) -> dict:
        return self.api.messages.getConversations(count=count, offset=offset, extended=1, fields=PROFILE_FIELDS)

    def conversation(self, peer_id: int) -> dict:
        return self.api.messages.getConversationsById(peer_ids=peer_id, extended=1, fields=PROFILE_FIELDS)

    def history_page(self, peer_id: int, count: int, before_id: int | None = None) -> dict:
        params = dict(peer_id=peer_id, count=count, extended=1, fields=PROFILE_FIELDS)
        if before_id is not None:
            # offset считается от start_message_id: 1 — со следующего более старого сообщения
            params.update(start_message_id=before_id, offset=1)
        return self.api.messages.getHistory(**params)

    def history_media(self, peer_id: int, media_type: str, count: int, start_from: str = "") -> dict:
        params = dict(peer_id=peer_id, media_type=media_type, count=count, photo_sizes=1, preserve_order=1)
        if start_from:
            params["start_from"] = start_from
        return self.api.messages.getHistoryAttachments(**params)

    def search_conversations(self, query: str, count: int) -> dict:
        return self.api.messages.searchConversations(q=query, count=count, extended=1, fields=PROFILE_FIELDS)

    def members(self, peer_id: int) -> dict:
        return self.api.messages.getConversationMembers(peer_id=peer_id, fields=PROFILE_FIELDS)

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

    def fetch_image(self, url: str) -> tuple[str, bytes] | None:
        """Картинка по адресу хранилища VK; без токена и без переходов по перенаправлениям."""
        if not is_photo_url(url):
            return None
        try:
            with requests.get(url, timeout=HTTP_TIMEOUT, allow_redirects=False, stream=True) as response:
                kind = response.headers.get("content-type", "").partition(";")[0].strip().lower()
                if response.status_code != 200 or kind not in IMAGE_EXTENSIONS:
                    return None
                data = response.raw.read(IMAGE_LIMIT + 1, decode_content=True)
        except (requests.RequestException, urllib3.exceptions.HTTPError, OSError):
            return None
        return (kind, data) if 0 < len(data) <= IMAGE_LIMIT else None

    def call(self, method: str, params: dict) -> object:
        if UPLOAD_PARAM in params:
            return self._uploaded(method.lower(), params)
        values = {name: wire_value(value) for name, value in params.items()}
        if method.lower() == "messages.send":
            return self._outbox.send(lambda random_id: self._request(method, {**values, "random_id": random_id}))
        return self._request(method, values)

    def _uploaded(self, method: str, params: dict) -> object:
        """Загрузка картинки, уже лежащей в хранилище VK: скачать её и пройти за модель шаги «сервер — файл — сохранить»."""
        if method not in UPLOADS:
            raise VkCallError(0, NO_UPLOAD)
        fetched = self.fetch_image(str(params[UPLOAD_PARAM]))
        if fetched is None:
            raise VkCallError(0, NO_PICTURE)
        kind, data = fetched
        picture = io.BytesIO(data)
        # FilesOpener берёт расширение из name
        picture.name = f"picture.{IMAGE_EXTENSIONS[kind]}"
        try:
            with vk_errors():
                return UPLOADS[method](self._upload, picture, params)
        except (KeyError, ValueError, TypeError):
            # не хватило параметра или сервер загрузки ответил не тем: сохранить нечего, действие не выполнено
            raise VkCallError(0, UPLOAD_FAILED) from None

    def _request(self, method: str, values: dict) -> object:
        with vk_errors():
            return self._session.method(method, values)


UPLOADS = {
    "photos.saveownerphoto": lambda upload, picture, params: upload.photo_profile(picture),
    "messages.setchatphoto": lambda upload, picture, params: upload.photo_chat(picture, params["chat_id"]),
    "photos.savewallphoto": lambda upload, picture, params: upload.photo_wall(picture, group_id=params.get("group_id")),
}
