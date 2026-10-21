import pytest

from web.vk import voice_attachment


def test_voice_attachment_includes_access_key():
    saved = {"type": "audio_message", "audio_message": {"id": 8, "owner_id": 1, "access_key": "abc"}}
    assert voice_attachment(saved) == "audio_message1_8_abc"


def test_voice_attachment_without_key():
    assert voice_attachment({"audio_message": {"id": 8, "owner_id": -5}}) == "audio_message-5_8"


def test_profile_fields_include_last_seen():
    from web.vk import PROFILE_FIELDS
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
    from web.vk import VkClient

    client = object.__new__(VkClient)
    client._session = session
    client._longpoll = None
    return client


def test_client_gives_up_on_a_vk_that_accepts_the_connection_and_stays_silent(monkeypatch, tmp_path):
    import socket

    import pytest
    import requests
    import vk_api

    from web.vk import VkClient

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


class FakeApi:
    def __init__(self):
        self.sent = []
        self.messages = self

    def send(self, **params):
        self.sent.append(params)
        return 300 + len(self.sent)


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
    from web import vk as vk_module

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
        raise RuntimeError("сбой")

    http = FakeLongPollHttp({"ts": 101, "updates": [raw_message(4)]})
    client = listening(monkeypatch, FakeLongPollSession(), http)
    assert [e.message_id for e in itertools.islice(client.listen(changed=broken), 1)] == [4]


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


def test_archived_peers_are_read_page_by_page_through_the_archive_filter():
    class ArchiveApi(FakeApi):
        def getConversations(self, **params):
            self.sent.append(params)
            start = params["offset"]
            peers = [2000000001, 22, -5][start:start + params["count"]]
            return {"count": 3, "items": [{"conversation": {"peer": {"id": p}}} for p in peers]}

    import web.vk

    client = client_with(FakeSession())
    client.api = ArchiveApi()
    original, web.vk.ARCHIVE_PAGE = web.vk.ARCHIVE_PAGE, 2
    try:
        assert client.archived_peers() == {2000000001, 22, -5}
    finally:
        web.vk.ARCHIVE_PAGE = original
    assert [(p["filter"], p["offset"]) for p in client.api.sent] == [("archive", 0), ("archive", 2)]
