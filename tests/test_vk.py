import pytest

from bot.vk import voice_attachment


def test_voice_attachment_includes_access_key():
    saved = {"type": "audio_message", "audio_message": {"id": 8, "owner_id": 1, "access_key": "abc"}}
    assert voice_attachment(saved) == "audio_message1_8_abc"


def test_voice_attachment_without_key():
    assert voice_attachment({"audio_message": {"id": 8, "owner_id": -5}}) == "audio_message-5_8"


def test_profile_fields_include_last_seen():
    from bot.vk import PROFILE_FIELDS
    assert "last_seen" in PROFILE_FIELDS.split(",") and "sex" in PROFILE_FIELDS.split(",")


class FakeSession:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.seen = []

    def method(self, method, values=None):
        self.seen.append((method, dict(values or {})))
        if self.error:
            raise self.error
        return self.result


def client_with(session):
    from bot.outbox import Outbox
    from bot.vk import VkClient

    client = object.__new__(VkClient)
    client._session = session
    client._outbox = Outbox()
    client._longpoll = None
    return client


def test_call_passes_method_and_params_to_the_session():
    session = FakeSession(result={"link": "https://vk.me/join/x"})
    assert client_with(session).call("messages.getInviteLink", {"peer_id": 2000000001}) == {"link": "https://vk.me/join/x"}
    assert session.seen == [("messages.getInviteLink", {"peer_id": 2000000001})]


def test_call_encodes_values_the_way_vk_expects():
    session = FakeSession(result=1)
    client_with(session).call("x.y", {"user_ids": [1, "durov"], "fields": ("sex", "online"), "reset": True,
                                     "extended": False, "forward": {"peer_id": 1, "cmids": [5]},
                                     "items": [{"a": 1}], "count": 5, "q": "да, нет", "empty": []})
    assert session.seen[0][1] == {"user_ids": "1,durov", "fields": "sex,online", "reset": 1, "extended": 0,
                                  "forward": '{"peer_id": 1, "cmids": [5]}', "items": '[{"a": 1}]',
                                  "count": 5, "q": "да, нет", "empty": ""}


def test_api_error_becomes_vk_call_error_with_code():
    import pytest
    from vk_api.exceptions import ApiError

    from bot.vk import VkCallError

    error = ApiError(None, "messages.pin", {}, {}, {"error_code": 917, "error_msg": "You don't have access to this chat"})
    with pytest.raises(VkCallError) as caught:
        client_with(FakeSession(error=error)).call("messages.pin", {})
    assert caught.value.code == 917 and "access" in caught.value.message


def test_captcha_and_other_vk_errors_become_vk_call_error():
    import pytest
    from vk_api.exceptions import Captcha, VkApiError

    from bot.vk import VkCallError

    captcha = Captcha(None, "sid", lambda *a: None, url="https://vk.com/captcha.php")
    with pytest.raises(VkCallError) as caught:
        client_with(FakeSession(error=captcha)).call("wall.post", {})
    assert caught.value.code == 14
    with pytest.raises(VkCallError) as other:
        client_with(FakeSession(error=VkApiError("сеть"))).call("users.get", {})
    assert other.value.code == 0 and "сеть" in other.value.message


def test_lost_connection_becomes_vk_call_error_with_the_network_code():
    import pytest
    import requests
    from vk_api.exceptions import ApiHttpError

    from bot.vk import NETWORK_CODE, VkCallError

    class BadGateway:
        status_code = 502

    for error in (requests.ConnectionError("reset"), requests.ReadTimeout("тишина"),
                  ApiHttpError(None, "wall.post", {}, False, BadGateway())):
        with pytest.raises(VkCallError) as caught:
            client_with(FakeSession(error=error)).call("wall.post", {})
        assert caught.value.code == NETWORK_CODE and caught.value.message


def test_client_gives_up_on_a_vk_that_accepts_the_connection_and_stays_silent(monkeypatch, tmp_path):
    import socket

    import pytest
    import requests
    import vk_api

    from bot.vk import VkClient

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(vk_api.VkApi, "method", lambda self, method, values=None, **kw: [{"id": 42}])
    client = VkClient("token", timeout=(0.2, 0.2))
    silent = socket.socket()
    silent.bind(("127.0.0.1", 0))
    silent.listen(1)
    try:
        with pytest.raises(requests.Timeout):
            client._session.http.post(f"http://127.0.0.1:{silent.getsockname()[1]}/method/users.get", {"v": "5.92"})
    finally:
        silent.close()


def test_message_sent_by_a_tool_call_is_marked_as_own():
    session = FakeSession(result=901)
    client = client_with(session)
    assert client.call("messages.send", {"peer_id": 2000000001, "message": "привет"}) == 901
    sent = session.seen[0][1]
    assert client._outbox.owns(901, 0)
    assert client._outbox.owns(None, sent["random_id"])


def test_tool_call_cannot_choose_its_own_random_id():
    session = FakeSession(result=902)
    client = client_with(session)
    client.call("Messages.Send", {"peer_id": 1, "message": "x", "random_id": 5})
    sent = session.seen[0][1]
    assert sent["random_id"] != 5
    assert client._outbox.owns(None, sent["random_id"])


def test_other_calls_do_not_touch_the_outbox():
    session = FakeSession(result=1)
    client = client_with(session)
    client.call("messages.pin", {"peer_id": 2000000001, "conversation_message_id": 3})
    assert "random_id" not in session.seen[0][1]
    assert not client._outbox.owns(1, 0)


class FakeApi:
    def __init__(self):
        self.sent = []
        self.messages = self

    def send(self, **params):
        self.sent.append(params)
        return 300 + len(self.sent)


def test_replies_are_marked_as_own():
    client = client_with(FakeSession())
    client.api = FakeApi()
    first = client.send_reply(2000000001, 5, "раз")
    second = client.send_message(42, "два")
    assert client._outbox.owns(first, 0) and client._outbox.owns(second, 0)
    assert all(client._outbox.owns(None, params["random_id"]) for params in client.api.sent)


def test_history_media_ask_for_photo_sizes_in_message_order():
    class AttachmentsApi(FakeApi):
        def getHistoryAttachments(self, **params):
            self.sent.append(params)
            return {"items": []}

    client = client_with(FakeSession())
    client.api = AttachmentsApi()
    client.history_media(2000000001, "photo", 60)
    client.history_media(2000000001, "photo", 60, start_from="9/1")
    first, more = client.api.sent
    assert first == {"peer_id": 2000000001, "media_type": "photo", "count": 60, "photo_sizes": 1, "preserve_order": 1}
    assert more["start_from"] == "9/1"


class GoneMessageApi(FakeApi):
    def send(self, **params):
        from vk_api.exceptions import ApiError

        if "reply_to" in params:
            self.sent.append(params)
            raise ApiError(None, "messages.send", {}, {}, {"error_code": 100, "error_msg": "cannot reply this message"})
        return super().send(**params)


def test_reply_to_a_deleted_message_goes_out_without_the_quote():
    client = client_with(FakeSession())
    client.api = GoneMessageApi()
    sent = client.send_reply(2000000001, 5, "раз")
    assert [("reply_to" in params, params["message"]) for params in client.api.sent] == [(True, "раз"), (False, "раз")]
    assert client._outbox.owns(sent, 0)


def test_other_send_failures_are_not_retried():
    import pytest
    from vk_api.exceptions import ApiError

    class Flooded(FakeApi):
        def send(self, **params):
            self.sent.append(params)
            raise ApiError(None, "messages.send", {}, {}, {"error_code": 9, "error_msg": "Flood control"})

    client = client_with(FakeSession())
    client.api = Flooded()
    with pytest.raises(ApiError):
        client.send_reply(2000000001, 5, "раз")
    assert len(client.api.sent) == 1

NEW_MESSAGE, MESSAGE_FLAGS = 4, 3


def raw_message(message_id, text="привет"):
    return [NEW_MESSAGE, message_id, 0, 2_000_000_001, 1791200000, text, {"from": "7"}, {}, 0]


class FakeLongPollSession:
    """Сессия VK для long poll: выдаёт сервер с текущим ts и считает обращения за ним."""

    def __init__(self, ts=100):
        self.ts = ts
        self.server_requests = 0

    def method(self, method, values=None):
        assert method == "messages.getLongPollServer"
        self.server_requests += 1
        return {"key": "k", "server": "lp.vk.test/im1", "ts": self.ts, "pts": 1}


class FakeLongPollHttp:
    """Сервер long poll: на каждый запрос отдаёт следующий ответ сценария или бросает исключение."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.asked_ts = []

    def get(self, url, params=None, timeout=None):
        self.asked_ts.append(params["ts"])
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return FakeResponse(answer)


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def listening(monkeypatch, session, http):
    from bot import vk as vk_module

    class Wired(vk_module.LongPoll):
        def __init__(self, vk_session):
            super().__init__(vk_session)
            self.session = http

    monkeypatch.setattr(vk_module, "LongPoll", Wired)
    return client_with(session)


def test_listener_resumes_from_its_own_ts_after_a_lost_connection(monkeypatch):
    import itertools

    import requests

    session = FakeLongPollSession(ts=100)
    http = FakeLongPollHttp(
        {"ts": 101, "updates": [raw_message(1)]},
        requests.ConnectionError("обрыв"),
        {"ts": 103, "updates": [raw_message(2), raw_message(3)]},
    )
    client = listening(monkeypatch, session, http)

    first = client.listen()
    assert next(first).message_id == 1
    with pytest.raises(requests.ConnectionError):
        next(first)
    session.ts = 500

    assert [event.message_id for event in itertools.islice(client.listen(), 2)] == [2, 3]
    assert http.asked_ts == [100, 101, 101]
    assert session.server_requests == 1


def test_listener_that_could_not_start_tries_again(monkeypatch):
    import requests

    class Down(FakeLongPollSession):
        def method(self, method, values=None):
            if not self.server_requests:
                self.server_requests += 1
                raise requests.ConnectionError("обрыв")
            return super().method(method, values)

    session = Down()
    client = listening(monkeypatch, session, FakeLongPollHttp({"ts": 101, "updates": [raw_message(1)]}))
    with pytest.raises(requests.ConnectionError):
        next(client.listen())
    assert next(client.listen()).message_id == 1


def test_unparsable_event_does_not_take_its_batch_with_it(monkeypatch, caplog):
    secret = "секретный текст"
    broken = [NEW_MESSAGE, 2, 0, 2_000_000_001, 1791200000, secret, "не словарь", {}, 0]
    http = FakeLongPollHttp({"ts": 101, "updates": [raw_message(1), broken, [MESSAGE_FLAGS, 9, 1], raw_message(3)]})
    client = listening(monkeypatch, FakeLongPollSession(), http)

    import itertools

    with caplog.at_level("WARNING"):
        got = [event.message_id for event in itertools.islice(client.listen(), 2)]
    assert got == [1, 3]
    assert "код 4" in caplog.text
    assert secret not in caplog.text


def test_listener_signals_batches_that_change_messages(monkeypatch):
    import itertools

    http = FakeLongPollHttp({"ts": 101, "updates": [[8, -5, 0]]}, {"ts": 102, "updates": [[7, 2_000_000_001, 9]]},
                            {"ts": 103, "updates": [raw_message(4)]})
    client = listening(monkeypatch, FakeLongPollSession(), http)
    batches = []
    assert [e.message_id for e in itertools.islice(client.listen(changed=lambda: batches.append(1)), 1)] == [4]
    assert batches == [1, 1]


def test_a_failing_change_signal_does_not_lose_the_batch(monkeypatch):
    import itertools

    def broken():
        raise RuntimeError("диск")

    http = FakeLongPollHttp({"ts": 101, "updates": [raw_message(4)]})
    client = listening(monkeypatch, FakeLongPollSession(), http)
    assert [e.message_id for e in itertools.islice(client.listen(changed=broken), 1)] == [4]

def test_inbox_mark_holds_only_the_time(tmp_path):
    from bot.status import InboxMark, read_json

    InboxMark(str(tmp_path / "state" / "inbox.json"), now=lambda: 42.0).changed()
    assert read_json(str(tmp_path / "state" / "inbox.json"), {}) == {"at": 42.0}


class FakeDownload:
    def __init__(self, status=200, kind="image/jpeg", data=b"\xff\xd8\xff"):
        self.status_code = status
        self.headers = {"content-type": kind}
        self.raw = self
        self._data = data

    def read(self, amount, decode_content=False):
        return self._data[:amount]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fetching(monkeypatch, download):
    import bot.vk

    asked = []

    def get(url, **kw):
        asked.append((url, kw))
        if isinstance(download, Exception):
            raise download
        return download

    monkeypatch.setattr(bot.vk.requests, "get", get)
    return asked


PHOTO_URL = "https://sun9-15.vkuserphoto.ru/x.jpg?sign=abc"


def test_picture_is_fetched_from_vk_storage_without_the_token_and_without_redirects(monkeypatch):
    asked = fetching(monkeypatch, FakeDownload(kind="image/JPEG; charset=binary"))
    assert client_with(FakeSession()).fetch_image(PHOTO_URL) == ("image/jpeg", b"\xff\xd8\xff")
    (url, kw), = asked
    assert url == PHOTO_URL and kw["allow_redirects"] is False and kw["timeout"] and kw["stream"] is True
    assert "headers" not in kw and "params" not in kw


@pytest.mark.parametrize("url", ["http://ai:8090/v1/models", "https://evil.example/x.jpg", "file:///app/.env",
                                 "https://sun9-15.vkuserphoto.ru@evil.example/x.jpg"])
def test_a_foreign_address_is_not_even_requested(monkeypatch, url):
    asked = fetching(monkeypatch, FakeDownload())
    assert client_with(FakeSession()).fetch_image(url) is None and asked == []


@pytest.mark.parametrize("download", [
    FakeDownload(status=302), FakeDownload(status=404), FakeDownload(kind="text/html"),
    FakeDownload(kind="image/svg+xml"), FakeDownload(data=b""), FakeDownload(data=b"x" * (3 * 1024 * 1024 + 1)),
    __import__("requests").ConnectionError("нет связи"),
    __import__("urllib3").exceptions.ReadTimeoutError(None, "u", "долго"), OSError("сокет"),
], ids=["перенаправление", "нет файла", "не картинка", "svg", "пусто", "слишком большая", "нет связи",
        "обрыв чтения", "сбой сокета"])
def test_anything_but_a_modest_picture_is_not_shown(monkeypatch, download):
    fetching(monkeypatch, download)
    assert client_with(FakeSession()).fetch_image(PHOTO_URL) is None


def test_reply_to_the_account_is_recognised_by_the_author_of_the_answered_message():
    def client(reply):
        message = {"id": 5, **({"reply_message": reply} if reply else {})}
        made = client_with(FakeSession(result={"items": [message]}))
        made.me_id = 42
        return made

    assert client({"from_id": 42, "text": "держи"}).replies_to_me(5) is True
    assert client({"from_id": 7, "text": "держи"}).replies_to_me(5) is False
    assert client(None).replies_to_me(5) is False
    empty = client_with(FakeSession(result={"items": []}))
    empty.me_id = 42
    assert empty.replies_to_me(5) is False


class FakeUpload:
    def __init__(self, error=None):
        self.seen = []
        self.error = error

    def _done(self, name, picture, *rest):
        self.seen.append((name, picture.name, picture.getvalue(), *rest))
        if self.error:
            raise self.error
        return {"saved": name}

    def photo_profile(self, picture):
        return self._done("profile", picture)

    def photo_chat(self, picture, chat_id):
        return self._done("chat", picture, chat_id)

    def photo_wall(self, picture, group_id=None):
        return [self._done("wall", picture, group_id)]


def test_photos_for_a_message_go_to_vk_one_per_upload():
    class MessageUpload:
        def __init__(self):
            self.seen = []

        def photo_messages(self, photo, peer_id=None):
            self.seen.append((photo.name, photo.getvalue(), peer_id))
            n = len(self.seen)
            return [{"owner_id": 7, "id": n, **({"access_key": "k"} if n == 1 else {})}]

    client = client_with(FakeSession())
    client._upload = MessageUpload()
    sent = client.upload_photos(2000000001, [(b"one", "png"), (b"two", "jpg")])
    assert client._upload.seen == [("photo.png", b"one", 2000000001), ("photo.jpg", b"two", 2000000001)]
    assert sent == ["photo7_1_k", "photo7_2"]

def uploading(monkeypatch, download=None, error=None):
    asked = fetching(monkeypatch, download or FakeDownload(kind="image/png", data=b"\x89PNG"))
    session = FakeSession()
    client = client_with(session)
    client._upload = FakeUpload(error)
    return client, session, asked


@pytest.mark.parametrize("method, params, done", [
    ("photos.saveOwnerPhoto", {}, ("profile",)), ("Messages.SetChatPhoto", {"chat_id": 7}, ("chat", 7)),
    ("photos.saveWallPhoto", {"group_id": 3}, ("wall", 3)), ("photos.saveWallPhoto", {}, ("wall", None)),
])
def test_a_call_with_a_picture_address_downloads_it_and_uploads_it_for_the_model(monkeypatch, method, params, done):
    client, session, asked = uploading(monkeypatch)
    client.call(method, {**params, "from_url": PHOTO_URL})
    assert [url for url, _ in asked] == [PHOTO_URL]
    name, *rest = done
    assert client._upload.seen == [(name, "picture.png", b"\x89PNG", *rest)]
    assert session.seen == []


def test_upload_through_a_method_that_takes_no_picture_reaches_neither_the_storage_nor_vk(monkeypatch):
    from bot.vk import VkCallError

    client, session, asked = uploading(monkeypatch)
    with pytest.raises(VkCallError):
        client.call("photos.saveMessagesPhoto", {"from_url": PHOTO_URL})
    assert asked == [] and session.seen == [] and client._upload.seen == []


@pytest.mark.parametrize("url", ["http://ai:8090/v1/models", "https://evil.example/x.jpg"])
def test_upload_from_a_foreign_address_fails_without_a_request(monkeypatch, url):
    from bot.vk import VkCallError

    client, session, asked = uploading(monkeypatch)
    with pytest.raises(VkCallError):
        client.call("photos.saveOwnerPhoto", {"from_url": url})
    assert asked == [] and client._upload.seen == []


def test_vk_refusing_the_upload_is_reported_as_a_vk_error(monkeypatch):
    import requests

    from bot.vk import NETWORK_CODE, VkCallError

    client, _, _ = uploading(monkeypatch, error=requests.ConnectionError("нет связи"))
    with pytest.raises(VkCallError) as caught:
        client.call("photos.saveOwnerPhoto", {"from_url": PHOTO_URL})
    assert caught.value.code == NETWORK_CODE


def test_a_chat_photo_without_its_chat_fails_as_a_plain_error_and_not_as_an_unknown_outcome(monkeypatch):
    from bot.vk import VkCallError

    client, _, _ = uploading(monkeypatch)
    with pytest.raises(VkCallError) as caught:
        client.call("messages.setChatPhoto", {"from_url": PHOTO_URL})
    assert caught.value.code == 0 and client._upload.seen == []
