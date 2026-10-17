import json
import re

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

    def upload_photos(self, peer_id, photos):
        self.calls.append(("photos", peer_id, [ext for _, ext in photos]))
        return [f"photo1_{i}_key" for i, _ in enumerate(photos)]

    def search_conversations(self, query, count):
        self.calls.append(("search", query, count))
        return {"count": 1, "items": [CONVERSATIONS["items"][1]["conversation"]], "profiles": CONVERSATIONS["profiles"]}

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
    assert '#message_outline_20"' in nav and '#robot_outline_20"' in nav
    assert 'class="topnav"' not in r.text


def test_other_pages_keep_the_plain_nav(client):
    r = client.get("/", auth=AUTH)
    assert 'class="topnav"' in r.text and "vk-nav" not in r.text and 'href="/im"' in r.text


def test_dialog_rows_show_mute_icon_ticks_and_short_age(client):
    r = client.get("/im/dialogs", auth=AUTH, headers={"HX-Request": "true"})
    chat, user = r.text.split("<li")[1:]
    assert '#mute_cross_16"' in chat and '#pin_16"' in chat
    assert 'class="att">Стикер' in chat and "Вася:" in chat
    assert '#check_outline_16"' in user and "Вы:" in user     # своё, непрочитанное — одна галочка
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
    assert '#cancel_24"' in r.text and '#chevron_left_24"' in r.text


def test_only_own_messages_get_a_delete_button(client):
    r = client.get(f"/im?sel={PEER_CHAT}", auth=AUTH)
    own = r.text.split('data-id="501"')[1].split("</article>")[0]
    other = r.text.split('data-id="500"')[1].split("</article>")[0]
    assert "/messages/501/delete" in own and '#delete_outline_24"' in own
    assert "delete" not in other and '#reply_24"' in other
    assert 'class="info"' in own and '#check_double_outline_16"' in own


def test_photo_opens_in_viewer(client):
    photo = {"id": 600, "date": 1788876300, "peer_id": PEER_CHAT, "from_id": 11, "out": 0, "text": "",
             "attachments": [{"type": "photo", "photo": {"sizes": [{"url": "https://cdn.example/p_x.jpg", "width": 604},
                                                                    {"url": "https://cdn.example/p_w.jpg", "width": 1280}]}}]}
    client.app.state.vk = FakeVk("t")
    client.app.state.vk.history_page = lambda *a, **k: {**HISTORY, "items": [photo] + HISTORY["items"]}
    r = client.get(f"/im?sel={PEER_CHAT}", auth=AUTH)
    assert 'data-full="https://cdn.example/p_w.jpg" target="_blank" rel="noopener" @click.prevent="view($el)"' in r.text
    assert 'src="https://cdn.example/p_x.jpg" width="320" height="320"' in r.text   # у фикстуры нет высоты — квадрат
    assert 'class="im-viewer"' in r.text and 'id="messages" class="im-messages" x-ref="list" data-gallery' in r.text


def test_forwarded_messages_and_reposts_render_inline(client):
    message = {"id": 601, "date": 1788876300, "peer_id": PEER_CHAT, "from_id": 11, "out": 0, "text": "",
               "attachments": [{"type": "wall", "wall": {
                   "id": 77, "from_id": -5, "to_id": -5, "date": 1788800000, "text": "текст поста",
                   "from": {"id": 5, "name": "Паблик", "photo_50": "https://cdn.example/g5.jpg"}, "attachments": []}}],
               "fwd_messages": [{"from_id": 22, "date": 1788870000, "text": "пересланный текст",
                                 "fwd_messages": [{"from_id": 11, "date": 1788860000, "text": "вложенный"}]}]}
    client.app.state.vk = FakeVk("t")
    client.app.state.vk.history_page = lambda *a, **k: {**HISTORY, "items": [message] + HISTORY["items"]}
    r = client.get(f"/im?sel={PEER_CHAT}", auth=AUTH)
    article = r.text.split('data-id="601"')[1].split("</article>")[0]
    assert "Паблик" in article and "текст поста" in article and 'href="https://vk.com/wall-5_77"' in article
    assert article.count('class="fwd"') == 2 and "пересланный текст" in article and "вложенный" in article
    assert 'href="https://vk.com/id22"' in article and "Аня Иванова" in article
    assert ">репост<" not in article and "пересланных<" not in article


def test_media_panel_has_tabs_and_pages_on(client):
    raw = {"items": [{"message_id": 9, "attachment": {"type": "photo", "photo": {"sizes": [
        {"url": "https://cdn.example/t.jpg", "width": 320, "height": 240},
        {"url": "https://cdn.example/full.jpg", "width": 1280, "height": 960}]}}}], "next_from": "9/1"}
    client.app.state.vk = FakeVk("t")
    client.app.state.vk.history_media = lambda peer_id, media_type, count, start_from="": (
        client.app.state.vk.calls.append(("media", peer_id, media_type, start_from)) or raw)
    hx = {"HX-Request": "true"}
    r = client.get(f"/im/{PEER_CHAT}/media", auth=AUTH, headers=hx)
    assert r.status_code == 200 and 'class="im-media-items photo" data-gallery' in r.text
    assert 'data-full="https://cdn.example/full.jpg"' in r.text and 'src="https://cdn.example/t.jpg"' in r.text
    assert f'hx-get="/im/{PEER_CHAT}/media?type=photo&start_from=9/1"' in r.text
    assert r.text.count('class="im-tabs"') == 1 and ">Голосовые<" in r.text
    more = client.get(f"/im/{PEER_CHAT}/media?start_from=9/1", auth=AUTH, headers=hx)
    assert "im-media-panel" not in more.text and "im-media-items" not in more.text and 'class="tile"' in more.text
    assert client.app.state.vk.calls[-1] == ("media", PEER_CHAT, "photo", "9/1")
    tab = client.get(f"/im/{PEER_CHAT}/media?type=doc&tab=1", auth=AUTH, headers=hx)
    assert "im-tabs" not in tab.text and 'class="im-media-items doc"' in tab.text
    assert client.get(f"/im/{PEER_CHAT}/media?type=wall", auth=AUTH, headers=hx).status_code == 404
    assert client.get(f"/im/{PEER_CHAT}/media", auth=AUTH).status_code == 303


def test_icon_sprite_url_carries_its_version(client):
    r = client.get(f"/im?sel={PEER_CHAT}", auth=AUTH)
    assert re.search(r'href="/static/vk-icons\.svg\?v=\d+#send_24"', r.text)
    assert "/static/vk-icons.svg#" not in r.text


def test_chat_header_toggles_photos_and_bot_panels(client):
    r = client.get(f"/im?sel={PEER_CHAT}", auth=AUTH)
    assert f'hx-get="/im/{PEER_CHAT}/media" hx-target="#media-slot"' in r.text
    assert "x-show=\"panel === 'media'\"" in r.text and "x-show=\"panel === 'bot'\"" in r.text


def test_voice_player_renders_wave_bars_and_transcript_toggle(client):
    r = client.get(f"/im?sel={PEER_CHAT}", auth=AUTH)
    voice = r.text.split('class="voice"')[1].split("</article>")[0]
    assert voice.count('rx="1"') == 60                       # 20 с → 60 столбиков
    assert 'id="w500-1"' in voice and 'clip-path="url(#w500-1c)"' in voice
    assert '#play_circle_32"' in voice and '#pause_circle_32"' in voice
    assert 'class="aa"' in voice and "после смены выкину</p>" in voice
    assert "<audio" not in voice and "0:20" in voice


def test_composer_is_a_vk_card_with_icon_buttons(client):
    r = client.get(f"/im?sel={PEER_CHAT}", auth=AUTH)
    form = r.text.split('class="im-composer"')[1].split("</form>")[0]
    assert 'class="box"' in form and '#send_24"' in form and "magic_wand" not in form
    assert '#add_circle_outline_24"' in form and 'placeholder="Сообщение"' in form
    assert ':class="{ ready }"' in form and "✨" not in form
    assert 'class="im-down"' in r.text


def test_composer_has_no_draft_button_and_the_route_is_gone(client):
    page = client.get(f"/im?sel={PEER_CHAT}", auth=AUTH).text
    assert "Черновик от бота" not in page and "/draft" not in page
    assert client.post(f"/im/{PEER_CHAT}/draft", auth=AUTH).status_code in (404, 405)


JPEG = b"\xff\xd8\xff\xe0" + b"0" * 16


def test_photos_go_out_with_the_text_in_one_message(client):
    r = client.post(f"/im/{PEER_CHAT}/send", auth=AUTH, headers={"HX-Request": "true"}, data={"text": "смотри"},
                    files=[("photos", ("a.jpg", JPEG, "image/jpeg")), ("photos", ("b.png", b"\x89PNG\r\n\x1a\n0", "image/png"))])
    assert r.status_code == 200
    calls = client.app.state.vk.calls
    assert ("photos", PEER_CHAT, ["jpg", "png"]) in calls
    assert ("send", PEER_CHAT, "смотри", None, "photo1_0_key,photo1_1_key") in calls


def test_a_non_picture_is_refused_before_anything_is_sent(client):
    r = client.post(f"/im/{PEER_CHAT}/send", auth=AUTH, headers={"HX-Request": "true"}, data={"text": ""},
                    files=[("photos", ("x.jpg", b"%PDF-1.7", "image/jpeg"))])
    assert r.status_code == 422 and "JPEG" in r.text
    vk = client.app.state.vk
    assert vk is None or not [c for c in vk.calls if c[0] in ("send", "photos")]


def test_unchanged_dialog_list_answers_204(client):
    hx = {"HX-Request": "true"}
    first = client.get("/im/dialogs?count=2", auth=AUTH, headers=hx)
    version = first.headers["X-Dialogs-Version"]
    again = client.get(f"/im/dialogs?count=2&v={version}", auth=AUTH, headers=hx)
    assert again.status_code == 204
    assert ("conversations", 2, 0) in client.app.state.vk.calls
    assert client.get("/im/dialogs?count=5000", auth=AUTH, headers=hx).status_code == 200
    assert ("conversations", 200, 0) in client.app.state.vk.calls


def test_more_dialogs_page_on_while_vk_has_them(client):
    client.app.state.vk = FakeVk("t")
    client.app.state.vk.conversations = lambda count=60, offset=0: {**CONVERSATIONS, "count": 150}
    r = client.get("/im/dialogs", auth=AUTH, headers={"HX-Request": "true"})
    assert 'hx-get="/im/dialogs/more?offset=2"' in r.text
    sentinel = r.text.split('class="dlg-more"')[1].split(">")[0]
    assert 'hx-target="this"' in sentinel and 'hx-swap="outerHTML"' in sentinel
    client.app.state.vk.conversations = lambda count=60, offset=0: {**CONVERSATIONS, "count": 4}
    more = client.get("/im/dialogs/more?offset=2", auth=AUTH, headers={"HX-Request": "true"})
    assert "dlg-more" not in more.text and "лампочки" in more.text


def test_search_reaches_chats_beyond_the_loaded_list(client):
    r = client.get("/im/dialogs/search?q=аня", auth=AUTH, headers={"HX-Request": "true"})
    assert "Аня Иванова" in r.text and 'data-peer="22"' in r.text and 'x-show="true"' in r.text
    assert ("search", "аня", 20) in client.app.state.vk.calls
    empty = client.get("/im/dialogs/search?q=", auth=AUTH, headers={"HX-Request": "true"})
    assert empty.status_code == 200 and "data-peer" not in empty.text


def test_opening_a_chat_never_marks_it_read(client):
    hx = {"HX-Request": "true"}
    r = client.get(f"/im?sel={PEER_CHAT}", auth=AUTH)
    client.get(f"/im/{PEER_CHAT}", auth=AUTH, headers=hx)
    client.get(f"/im/{PEER_CHAT}/messages?after=500", auth=AUTH, headers=hx)
    assert not [c for c in client.app.state.vk.calls if c[0] == "read"]
    assert f'chat({PEER_CHAT}, 501, 2)' in r.text and 'x-show="unread"' in r.text and "/read-marks" not in r.text


def test_a_refused_send_gives_the_composer_back(client):
    r = client.get(f"/im?sel={PEER_CHAT}", auth=AUTH)
    assert "sent($event.detail.successful && $event.detail.xhr.status < 300)" in r.text


def test_hovered_chat_opens_from_the_warmed_history(client):
    client.post(f"/im/{PEER_CHAT}/warm", auth=AUTH, headers={"HX-Request": "true"})
    client.get(f"/im/{PEER_CHAT}", auth=AUTH, headers={"HX-Request": "true"})
    client.get(f"/im/{PEER_CHAT}", auth=AUTH, headers={"HX-Request": "true"})
    fetched = [c for c in client.app.state.vk.calls if c[0] == "history"]
    assert len(fetched) == 2          # прогрев и второе открытие; первое открытие взяло прогретое


def test_more_dialogs_stop_at_the_cap(client):
    hx = {"HX-Request": "true"}
    client.get("/im/dialogs/more?offset=180", auth=AUTH, headers=hx)
    assert ("conversations", 20, 180) in client.app.state.vk.calls
    r = client.get("/im/dialogs/more?offset=200", auth=AUTH, headers=hx)
    assert r.status_code == 200 and "dlg" not in r.text
    assert not [c for c in client.app.state.vk.calls if c[0] == "conversations" and c[2] == 200]


def test_warmed_history_is_dropped_once_the_bot_saw_new_messages(client, settings):
    import os
    hx = {"HX-Request": "true"}
    inbox = f"{settings.state_dir}/inbox.json"
    os.makedirs(settings.state_dir, exist_ok=True)
    open(inbox, "w").write('{"at": 1}')
    client.post(f"/im/{PEER_CHAT}/warm", auth=AUTH, headers=hx)
    os.utime(inbox, ns=(os.stat(inbox).st_mtime_ns + 10**9,) * 2)
    client.get(f"/im/{PEER_CHAT}", auth=AUTH, headers=hx)
    assert len([c for c in client.app.state.vk.calls if c[0] == "history"]) == 2


def test_voice_with_photos_is_refused_before_any_upload(client):
    r = client.post(f"/im/{PEER_CHAT}/send", auth=AUTH, headers={"HX-Request": "true"},
                    files=[("voice", ("hello.ogg", b"OggS" + b"\0" * 100, "audio/ogg")),
                           ("photos", ("a.jpg", JPEG, "image/jpeg"))])
    assert r.status_code == 422 and "без фото" in r.text
    vk = client.app.state.vk
    assert vk is None or not [c for c in vk.calls if c[0] in ("photos", "voice", "send")]
