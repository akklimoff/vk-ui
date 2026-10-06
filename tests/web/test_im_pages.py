import json

import pytest
from fastapi.testclient import TestClient

from tests.web.conftest import AUTH
from tests.web.fakes import FakeAi
from tests.web.im_fixtures import CONVERSATIONS, HISTORY, MEMBERS, ME, PEER_CHAT, PEER_USER, SENT, UPLOADED_VOICE
from web.app import create_app


class FakeVk:
    me_id = ME

    def __init__(self, token):
        self.calls = []
        self.sent = False

    def conversations(self, count=60, offset=0):
        self.calls.append(("conversations", count, offset))
        return CONVERSATIONS

    def history_page(self, peer_id, count, before_id=None):
        self.calls.append(("history", peer_id, count, before_id))
        return {**HISTORY, "items": SENT["items"] + HISTORY["items"]} if self.sent else HISTORY

    def members(self, peer_id):
        return MEMBERS

    def send(self, peer_id, text="", reply_to=None, attachment=""):
        self.calls.append(("send", peer_id, text, reply_to, attachment))
        self.sent = True
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


@pytest.fixture
def client(settings):
    open(f"{settings.personas_dir}/rina.md", "w").write("# Рина\nперсона")
    return TestClient(create_app(settings, vk_factory=FakeVk, ai_factory=FakeAi), follow_redirects=False)


def test_im_page_lists_dialogs_with_modes(client):
    r = client.get("/im", auth=AUTH)
    assert r.status_code == 200
    assert "лампочки" in r.text and "Аня Иванова" in r.text
    assert "Стикер" in r.text                       # превью последнего сообщения
    assert 'class="unread quiet">2<' in r.text          # беседа в фикстуре без звука
    assert r.text.count("не слушает") >= 2           # бейдж у каждого диалога: ни один чат не в доверенных
    assert 'href="/im"' in r.text and "Мессенджер" in r.text


def test_im_page_with_sel_renders_chat(client):
    r = client.get(f"/im?sel={PEER_CHAT}", auth=AUTH)
    assert r.status_code == 200
    assert "ну все тогда" in r.text and "после смены выкину." in r.text
    assert "23 участника" in r.text
    assert 'voice("https://cdn.example/v.mp3", 20)' in r.text and "0:20" in r.text
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
    from bot.agent.journal import ActionLog, ActionRecord

    ActionLog(f"{settings.state_dir}/actions.jsonl").append(ActionRecord(
        ts=1, peer_id=PEER_CHAT, from_id=11, role="trusted", place="chat", message_id=500, request="просьба",
        calls=(), outcome="replied", reply="ну все тогда", reply_message_ids=(501,), steps=1, duration_s=1.0,
        model="grok-4.6", prompt_tokens=1, completion_tokens=1, persona="rina"))
    r = client.get(f"/im?sel={PEER_CHAT}", auth=AUTH)
    assert "бот · rina" in r.text


def test_dialogs_partial(client):
    r = client.get("/im/dialogs", auth=AUTH, headers={"HX-Request": "true"})
    assert r.status_code == 200 and "<li" in r.text and "<nav" not in r.text


def test_poll_returns_only_newer_rows_and_moves_cursor(client):
    r = client.get(f"/im/{PEER_CHAT}/messages?after=500", auth=AUTH, headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert 'data-id="501"' in r.text and 'data-id="502"' in r.text and 'data-id="500"' not in r.text
    assert 'id="chat-state"' in r.text and 'data-out-read="501"' in r.text


def test_poll_without_news_is_empty(client):
    r = client.get(f"/im/{PEER_CHAT}/messages?after=502", auth=AUTH, headers={"HX-Request": "true"})
    assert r.status_code == 200 and "<article" not in r.text


def test_older_page_replaces_sentinel(client):
    r = client.get(f"/im/{PEER_CHAT}/messages?before=499", auth=AUTH, headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert client.app.state.vk.calls[-1] == ("history", PEER_CHAT, 40, 499)
    assert 'class="im-more"' not in r.text                         # страница неполная — старее ничего нет


def test_full_page_keeps_sentinel_on_oldest(client):
    full = {**HISTORY, "items": [{**HISTORY["items"][1], "id": 600 - i} for i in range(40)]}
    client.app.state.vk = FakeVk("t")
    client.app.state.vk.history_page = lambda *a, **k: full
    r = client.get(f"/im/{PEER_CHAT}/messages?before=600", auth=AUTH, headers={"HX-Request": "true"})
    assert 'class="im-more"' in r.text and "before=561" in r.text
    r = client.get(f"/im?sel={PEER_CHAT}", auth=AUTH)
    assert 'class="im-more"' in r.text


def test_send_text_appends_sent_message(client):
    r = client.post(f"/im/{PEER_CHAT}/send", data={"text": "привет из админки", "reply_to": "500", "after": "502"},
                    auth=AUTH, headers={"HX-Request": "true"})
    assert r.status_code == 200
    vk = client.app.state.vk
    assert ("send", PEER_CHAT, "привет из админки", 500, "") in vk.calls
    assert 'data-id="503"' in r.text and "привет из админки" in r.text and 'data-id="502"' not in r.text


def test_send_also_renders_messages_that_arrived_since_last_render(client):
    r = client.post(f"/im/{PEER_CHAT}/send", data={"text": "привет из админки", "after": "500"},
                    auth=AUTH, headers={"HX-Request": "true"})
    assert r.text.index('data-id="501"') < r.text.index('data-id="502"') < r.text.index('data-id="503"')
    assert 'data-out-read="501"' in r.text


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


def test_send_voice_uploads_then_sends_attachment(client):
    r = client.post(f"/im/{PEER_CHAT}/send", data={"text": ""},
                    files={"voice": ("hello.ogg", b"OggS" + b"\0" * 100, "audio/ogg")},
                    auth=AUTH, headers={"HX-Request": "true"})
    assert r.status_code == 200
    calls = client.app.state.vk.calls
    assert ("voice", PEER_CHAT, 104, "ogg") in calls
    assert ("send", PEER_CHAT, "", None, "audio_message1_8_abc") in calls


def test_send_mp3_is_converted_before_upload(client, monkeypatch):
    monkeypatch.setattr("web.im.routes.prepare_voice", lambda data, name: b"OggS" + b"\0" * 10)
    r = client.post(f"/im/{PEER_CHAT}/send", data={"text": "с голосом"},
                    files={"voice": ("hello.mp3", b"ID3\x04" + b"\0" * 100, "audio/mpeg")},
                    auth=AUTH, headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert ("voice", PEER_CHAT, 14, "ogg") in client.app.state.vk.calls


def test_send_bad_voice_is_422_without_vk_calls(client):
    r = client.post(f"/im/{PEER_CHAT}/send", data={"text": ""},
                    files={"voice": ("x.wav", b"RIFF" + b"\0" * 100, "audio/wav")},
                    auth=AUTH, headers={"HX-Request": "true"})
    assert r.status_code == 422 and "ogg" in r.text
    vk = client.app.state.vk
    assert vk is None or not [c for c in vk.calls if c[0] in ("voice", "send")]


def test_poll_continues_series_of_same_author(client):
    r = client.get(f"/im/{PEER_CHAT}/messages?after=501&last_from=11&last_ts=1788876200", auth=AUTH, headers={"HX-Request": "true"})
    assert 'class="msg  "' in r.text or 'class="msg "' in r.text        # 502 от Васи без head
    r = client.get(f"/im/{PEER_CHAT}/messages?after=501&last_from=1&last_ts=1788876200", auth=AUTH, headers={"HX-Request": "true"})
    assert 'class="msg head' in r.text


def test_poll_skips_day_chip_when_day_continues(client):
    r = client.get(f"/im/{PEER_CHAT}/messages?after=501&last_from=1&last_ts=1788876200", auth=AUTH, headers={"HX-Request": "true"})
    assert 'class="im-day"' not in r.text


def test_sent_message_continues_own_series(client):
    r = client.post(f"/im/{PEER_CHAT}/send", data={"text": "ещё", "after": "502", "last_from": "1", "last_ts": "1788876290"},
                    auth=AUTH, headers={"HX-Request": "true"})
    assert 'class="msg  out"' in r.text and 'class="im-day"' not in r.text


def test_empty_chat_shows_placeholder(client):
    client.app.state.vk = FakeVk("t")
    client.app.state.vk.history_page = lambda *a, **k: {"items": [], "profiles": [], "groups": [], "conversations": []}
    r = client.get(f"/im?sel={PEER_CHAT}", auth=AUTH)
    assert "Сообщений пока нет" in r.text


def test_send_counts_as_sent_when_only_rendering_fails(client):
    client.app.state.vk = FakeVk("t")

    def rate_limited(*a, **k):
        raise RuntimeError("[6] Too many requests per second")

    client.app.state.vk.history_page = rate_limited
    r = client.post(f"/im/{PEER_CHAT}/send", data={"text": "ещё", "after": "502"}, auth=AUTH, headers={"HX-Request": "true"})
    assert r.status_code == 200 and json.loads(r.headers["HX-Trigger"])["toast"] == "Отправлено" and "<article" not in r.text


def test_im_page_wears_the_vk_shell(client):
    r = client.get("/im", auth=AUTH)
    assert 'class="page-im"' in r.text
    nav = r.text.split('class="vk-nav"')[1].split("</nav>")[0]
    assert 'aria-current="page"' in nav.split("Мессенджер")[0]
    assert "vk-icons.svg#message_outline_20" in nav and "vk-icons.svg#robot_outline_20" in nav
    assert 'class="topnav"' not in r.text


def test_other_pages_keep_the_plain_nav(client):
    r = client.get("/", auth=AUTH)
    assert 'class="topnav"' in r.text and "vk-nav" not in r.text and 'href="/im"' in r.text


def test_dialog_rows_show_mute_icon_ticks_and_short_age(client):
    r = client.get("/im/dialogs", auth=AUTH, headers={"HX-Request": "true"})
    chat, user = r.text.split("<li")[1:]
    assert "vk-icons.svg#mute_cross_16" in chat and "vk-icons.svg#pin_16" in chat
    assert 'class="att">Стикер' in chat and "Вася:" in chat
    assert "vk-icons.svg#check_outline_16" in user and "Вы:" in user     # своё, непрочитанное — одна галочка
    assert '<span class="when"> · ' in user and "pinned-last" in chat and "pinned-last" not in user


def test_empty_state_template_is_on_the_page(client):
    r = client.get("/im", auth=AUTH)
    assert r.text.count("Выберите чат") == 2 and '<template id="im-empty">' in r.text


def test_chat_opening_puts_unread_separator_before_first_unread_incoming(client):
    r = client.get(f"/im?sel={PEER_CHAT}", auth=AUTH)
    assert r.text.index('data-id="501"') < r.text.index('class="im-unread"') < r.text.index('data-id="502"')
    poll = client.get(f"/im/{PEER_CHAT}/messages?after=500", auth=AUTH, headers={"HX-Request": "true"})
    assert "im-unread" not in poll.text


def test_chat_header_shows_presence_for_users(client):
    client.app.state.vk = FakeVk("t")
    client.app.state.vk.history_page = lambda *a, **k: {**HISTORY, "conversations": [CONVERSATIONS["items"][1]["conversation"]]}
    r = client.get(f"/im?sel={PEER_USER}", auth=AUTH)
    assert "была в сети 3 июля" in r.text and "в 09:15" in r.text
    assert "vk-icons.svg#cancel_24" in r.text and "vk-icons.svg#chevron_left_24" in r.text


def test_only_own_messages_get_a_delete_button(client):
    r = client.get(f"/im?sel={PEER_CHAT}", auth=AUTH)
    own = r.text.split('data-id="501"')[1].split("</article>")[0]
    other = r.text.split('data-id="500"')[1].split("</article>")[0]
    assert "/messages/501/delete" in own and "vk-icons.svg#delete_outline_24" in own
    assert "delete" not in other and "vk-icons.svg#reply_24" in other
    assert 'class="info"' in own and "vk-icons.svg#check_double_outline_16" in own


def test_photo_opens_in_viewer(client):
    photo = {"id": 600, "date": 1788876300, "peer_id": PEER_CHAT, "from_id": 11, "out": 0, "text": "",
             "attachments": [{"type": "photo", "photo": {"sizes": [{"url": "https://cdn.example/p_x.jpg", "width": 604},
                                                                    {"url": "https://cdn.example/p_w.jpg", "width": 1280}]}}]}
    client.app.state.vk = FakeVk("t")
    client.app.state.vk.history_page = lambda *a, **k: {**HISTORY, "items": [photo] + HISTORY["items"]}
    r = client.get(f"/im?sel={PEER_CHAT}", auth=AUTH)
    assert """@click.prevent='viewer = "https://cdn.example/p_w.jpg"'""" in r.text
    assert 'class="im-viewer"' in r.text


def test_voice_player_renders_wave_bars_and_transcript_toggle(client):
    r = client.get(f"/im?sel={PEER_CHAT}", auth=AUTH)
    voice = r.text.split('class="voice"')[1].split("</article>")[0]
    assert voice.count('rx="1"') == 60                       # 20 с → 60 столбиков
    assert 'id="w500-1"' in voice and 'clip-path="url(#w500-1c)"' in voice
    assert "vk-icons.svg#play_circle_32" in voice and "vk-icons.svg#pause_circle_32" in voice
    assert 'class="aa"' in voice and "после смены выкину</p>" in voice
    assert "<audio" not in voice and "0:20" in voice


def test_composer_is_a_vk_card_with_icon_buttons(client):
    r = client.get(f"/im?sel={PEER_CHAT}", auth=AUTH)
    form = r.text.split('class="im-composer"')[1].split("</form>")[0]
    assert 'class="box"' in form and "vk-icons.svg#send_24" in form and "magic_wand" not in form
    assert "vk-icons.svg#add_circle_outline_24" in form and 'placeholder="Сообщение"' in form
    assert ':class="{ ready }"' in form and "✨" not in form
    assert 'class="im-down"' in r.text


def test_composer_has_no_draft_button_and_the_route_is_gone(client):
    page = client.get(f"/im?sel={PEER_CHAT}", auth=AUTH).text
    assert "Черновик от бота" not in page and "/draft" not in page
    assert client.post(f"/im/{PEER_CHAT}/draft", auth=AUTH).status_code in (404, 405)
