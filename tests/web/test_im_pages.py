import pytest
from fastapi.testclient import TestClient

from tests.web.conftest import AUTH
from tests.web.im_fixtures import CONVERSATIONS, HISTORY, MEMBERS, ME, PEER_CHAT, SENT, UPLOADED_VOICE
from web.app import create_app


class FakeVk:
    me_id = ME

    def __init__(self, token):
        self.calls = []

    def conversations(self, count=60, offset=0):
        self.calls.append(("conversations", count, offset))
        return CONVERSATIONS

    def history_page(self, peer_id, count, before_id=None):
        self.calls.append(("history", peer_id, count, before_id))
        return HISTORY

    def members(self, peer_id):
        return MEMBERS

    def messages_by_id(self, ids):
        self.calls.append(("by_id", tuple(ids)))
        return SENT

    def send(self, peer_id, text="", reply_to=None, attachment=""):
        self.calls.append(("send", peer_id, text, reply_to, attachment))
        return 503

    def mark_read(self, peer_id):
        self.calls.append(("read", peer_id))

    def delete_message(self, message_id):
        self.calls.append(("delete", message_id))

    def upload_voice(self, peer_id, data, ext):
        self.calls.append(("voice", peer_id, len(data), ext))
        return "audio_message1_8_abc"

    def resolve_name(self, uid):
        return "Вася Пупкин"

    def resolve_screen_names(self, names):
        return frozenset()

    def history(self, peer_id, count):
        return HISTORY["items"]


class FakeLlm:
    def __init__(self, settings):
        self.calls = []

    def reply(self, conversation, asker, **kw):
        self.calls.append((conversation, asker, kw))
        return "черновик от llm"


@pytest.fixture
def client(settings):
    open(f"{settings.personas_dir}/rina.md", "w").write("# Рина\nперсона")
    return TestClient(create_app(settings, vk_factory=FakeVk, llm_factory=FakeLlm), follow_redirects=False)


def test_im_page_lists_dialogs_with_modes(client):
    r = client.get("/im", auth=AUTH)
    assert r.status_code == 200
    assert "лампочки" in r.text and "Аня Иванова" in r.text
    assert "Стикер" in r.text                       # превью последнего сообщения
    assert 'class="unread">2<' in r.text
    assert r.text.count("по тегу") >= 2              # бейдж режима у каждого диалога
    assert 'href="/im"' in r.text and "Мессенджер" in r.text


def test_im_page_with_sel_renders_chat(client):
    r = client.get(f"/im?sel={PEER_CHAT}", auth=AUTH)
    assert r.status_code == 200
    assert "ну все тогда" in r.text and "после смены выкину." in r.text
    assert "23 участника" in r.text
    assert 'src="https://cdn.example/v.mp3"' in r.text and "0:20" in r.text
    assert "после смены выкину</" in r.text          # расшифровка голосового
    assert "пригласил(а) Аня Иванова" in r.text
    assert 'src="https://cdn.example/st256.png"' in r.text
    assert "выкидывай тогда" in r.text               # цитата ответа
    assert r.text.count('class="im-day"') == 2          # два разных дня в фикстуре


def test_chat_partial_for_htmx_pushes_url(client):
    r = client.get(f"/im/{PEER_CHAT}", auth=AUTH, headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert r.headers["HX-Push-Url"] == f"/im?sel={PEER_CHAT}"
    assert "<nav" not in r.text and 'id="messages"' in r.text


def test_chat_marks_bot_replies(client, settings):
    import os
    os.makedirs(settings.state_dir, exist_ok=True)
    with open(f"{settings.state_dir}/replies.jsonl", "w") as f:
        f.write('{"ts": 1, "peer_id": 2000000001, "from_id": 11, "message_id": 500, "reply_message_id": 501, '
                '"reply": "ну все тогда", "tag": null, "latency_s": 1.0, "persona": "rina", "model": "grok-4.6"}\n')
    r = client.get(f"/im?sel={PEER_CHAT}", auth=AUTH)
    assert "бот · rina" in r.text


def test_dialogs_partial(client):
    r = client.get("/im/dialogs", auth=AUTH, headers={"HX-Request": "true"})
    assert r.status_code == 200 and "<li" in r.text and "<nav" not in r.text


def test_poll_returns_only_newer_rows_and_moves_cursor(client):
    r = client.get(f"/im/{PEER_CHAT}/messages?after=500", auth=AUTH, headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert 'data-id="501"' in r.text and 'data-id="502"' in r.text and 'data-id="500"' not in r.text
    assert 'id="chat-poll"' in r.text and "after=502" in r.text and 'hx-swap-oob="true"' in r.text
    assert 'id="chat-state"' in r.text and 'data-out-read="501"' in r.text


def test_poll_without_news_is_empty_but_keeps_cursor(client):
    r = client.get(f"/im/{PEER_CHAT}/messages?after=502", auth=AUTH, headers={"HX-Request": "true"})
    assert r.status_code == 200 and "<article" not in r.text and "after=502" in r.text


def test_older_page_replaces_sentinel(client):
    r = client.get(f"/im/{PEER_CHAT}/messages?before=499", auth=AUTH, headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert client.app.state.vk.calls[-1] == ("history", PEER_CHAT, 40, 499)
    assert 'class="im-more"' in r.text and "before=499" in r.text   # фикстура отдаёт те же id — сентинел на самый старый


def test_send_text_appends_sent_message(client):
    r = client.post(f"/im/{PEER_CHAT}/send", data={"text": "привет из админки", "reply_to": "500"},
                    auth=AUTH, headers={"HX-Request": "true"})
    assert r.status_code == 200
    vk = client.app.state.vk
    assert ("send", PEER_CHAT, "привет из админки", 500, "") in vk.calls
    assert ("by_id", (503,)) in vk.calls
    assert 'data-id="503"' in r.text and "привет из админки" in r.text
    assert "after=503" in r.text                    # курсор поллинга сдвинут, чтобы не продублировать


def test_send_empty_is_422(client):
    r = client.post(f"/im/{PEER_CHAT}/send", data={"text": "   "}, auth=AUTH, headers={"HX-Request": "true"})
    vk = client.app.state.vk
    assert r.status_code == 422 and (vk is None or "send" not in [c[0] for c in vk.calls])


def test_send_vk_error_is_sanitized(client, settings):
    def boom(*a, **k):
        raise RuntimeError(f"bad token {settings.vk_token}")
    client.app.state.vk = FakeVk("t")
    client.app.state.vk.send = boom
    r = client.post(f"/im/{PEER_CHAT}/send", data={"text": "x"}, auth=AUTH, headers={"HX-Request": "true"})
    assert r.status_code == 422 and settings.vk_token not in r.text and "[скрыто]" in r.text


def test_mark_read_and_delete(client):
    assert client.post(f"/im/{PEER_CHAT}/read", auth=AUTH, headers={"HX-Request": "true"}).status_code == 204
    assert client.post(f"/im/{PEER_CHAT}/messages/501/delete", auth=AUTH, headers={"HX-Request": "true"}).status_code == 200
    calls = client.app.state.vk.calls
    assert ("read", PEER_CHAT) in calls and ("delete", 501) in calls


def test_reply_button_payload_survives_attribute_quoting(client):
    r = client.get(f"/im?sel={PEER_CHAT}", auth=AUTH)
    assert "@click='$dispatch(\"im-reply\", { id: 501, author: \"" in r.text
