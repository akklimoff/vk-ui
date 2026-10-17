import html
import json
import re

import pytest
from fastapi.testclient import TestClient

from tests.web.conftest import AUTH
from tests.web.im_fixtures import ME, PEER_CHAT, PEER_USER
from tests.web.test_im_pages import FakeAi, FakeVk
from web.app import create_app

HX = {"HX-Request": "true"}


@pytest.fixture
def client(settings):
    for slug, name in (("rina", "Рина"), ("monika", "Моника")):
        with open(f"{settings.personas_dir}/{slug}.md", "w", encoding="utf-8") as f:
            f.write(f"# {name}\nперсона")
    return TestClient(create_app(settings, vk_factory=FakeVk, ai_factory=FakeAi), follow_redirects=False)


def access(settings):
    with open(settings.access_file, encoding="utf-8") as f:
        return json.load(f)


def runtime(settings):
    with open(settings.runtime_file, encoding="utf-8") as f:
        return json.load(f)


def write_access(settings, data):
    with open(settings.access_file, "w", encoding="utf-8") as f:
        f.write(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False))


def test_chat_page_calls_the_panel_the_agent(client):
    page = client.get(f"/im/{PEER_CHAT}", auth=AUTH, headers=HX).text
    assert 'title="Агент в этом чате"' in page and "Бот в этом чате" not in page


def test_panel_of_an_untrusted_chat_says_the_agent_is_silent(client):
    r = client.get(f"/im/{PEER_CHAT}/bot", auth=AUTH, headers=HX)
    assert r.status_code == 200 and "не слушает" in r.text and "не в доверенных" in r.text
    assert f"/im/{PEER_CHAT}/bot/listens" in r.text and f"/im/{PEER_CHAT}/bot/paused" in r.text
    assert "Вася Пупкин" in r.text and "Аня Иванова" in r.text
    assert "Валентина Тина" not in r.text.split("Участники")[1]
    assert "Рина" in r.text and "Моника" in r.text and "Читать без отметки" not in r.text
    for gone in ("Отвечать без тега", "Знакомиться", "Заблокировать", "игнор", "user_prompts"):
        assert gone not in r.text


def test_listen_switch_trusts_the_chat_and_updates_the_badge(client, settings):
    write_access(settings, {"blocked_users": ["5"]})
    r = client.post(f"/im/{PEER_CHAT}/bot/listens", data={"on": "1"}, auth=AUTH, headers=HX)
    assert r.status_code == 200 and 'id="chat-badge" hx-swap-oob="true"' in r.text and ">слушает<" in r.text
    assert access(settings) == {"blocked_users": ["5"], "agent_users": [], "agent_peers": [PEER_CHAT],
                                "peer_prompts": {}}
    r = client.post(f"/im/{PEER_CHAT}/bot/listens", data={}, auth=AUTH, headers=HX)
    assert access(settings)["agent_peers"] == [] and ">не слушает<" in r.text


def test_private_dialog_has_nothing_to_switch(client, settings):
    panel = client.get(f"/im/{PEER_USER}/bot", auth=AUTH, headers=HX).text
    assert "В личных диалогах агент не работает" in panel and "/bot/listens" not in panel and "/bot/note" not in panel
    assert client.post(f"/im/{PEER_USER}/bot/listens", data={"on": "1"}, auth=AUTH, headers=HX).status_code == 404
    assert client.post(f"/im/{PEER_USER}/bot/note", data={"text": "x"}, auth=AUTH, headers=HX).status_code == 404
    assert client.post(f"/im/{PEER_USER}/bot/members/11", data={"on": "1"}, auth=AUTH, headers=HX).status_code == 404


def test_saved_messages_always_listen(client):
    panel = client.get(f"/im/{ME}/bot", auth=AUTH, headers=HX).text
    assert ">слушает<" in panel and "Избранное" in panel and "/bot/listens" not in panel
    assert f"/im/{ME}/bot/paused" in panel


def test_pause_and_personas_go_to_runtime(client, settings):
    r = client.post(f"/im/{PEER_CHAT}/bot/paused", data={"on": "1"}, auth=AUTH, headers=HX)
    assert runtime(settings)["paused_peers"] == [PEER_CHAT] and ">пауза<" in r.text
    r = client.post(f"/im/{PEER_CHAT}/bot/personas", data={"slug": ["rina", "monika"]}, auth=AUTH, headers=HX)
    assert r.status_code == 200 and runtime(settings)["peer_personas"] == {str(PEER_CHAT): ["rina", "monika"]}
    bad = client.post(f"/im/{PEER_CHAT}/bot/personas", data={"slug": ["nope"]}, auth=AUTH, headers=HX)
    assert bad.status_code == 422 and runtime(settings)["peer_personas"] == {str(PEER_CHAT): ["rina", "monika"]}
    client.post(f"/im/{PEER_CHAT}/bot/personas", data={}, auth=AUTH, headers=HX)
    assert runtime(settings)["peer_personas"] == {}


def test_chat_note_survives_being_posted_back_from_the_panel(client, settings):
    note = "тут друзья\n2000000002: шутки\n\nи абзац"
    write_access(settings, {"peer_prompts": {str(PEER_CHAT): note}})
    panel = client.get(f"/im/{PEER_CHAT}/bot", auth=AUTH, headers=HX).text
    shown = html.unescape(re.search(r'<textarea name="text"[^>]*>(.*?)</textarea>', panel, re.S).group(1))
    assert shown == note
    # браузер отправляет переводы строк textarea как CRLF
    client.post(f"/im/{PEER_CHAT}/bot/note", data={"text": shown.replace("\n", "\r\n")}, auth=AUTH, headers=HX)
    assert access(settings)["peer_prompts"] == {str(PEER_CHAT): note}
    client.post(f"/im/{PEER_CHAT}/bot/note", data={"text": ""}, auth=AUTH, headers=HX)
    assert access(settings)["peer_prompts"] == {}


def test_members_header_says_a_trusted_person_reads_the_private_correspondence(client):
    panel = client.get(f"/im/{PEER_CHAT}/bot", auth=AUTH, headers=HX).text
    assert "личную переписку аккаунта" in panel.split("Участники")[1].split("</h4>")[0]


def test_member_becomes_trusted_and_untrusted(client, settings):
    client.post(f"/im/{PEER_CHAT}/bot/members/11", data={"on": "1"}, auth=AUTH, headers=HX)
    assert access(settings)["agent_users"] == [11]
    panel = client.get(f"/im/{PEER_CHAT}/bot", auth=AUTH, headers=HX).text
    assert "checked" in panel.split("Вася Пупкин")[1].split("</li>")[0]
    assert "checked" not in panel.split("Аня Иванова")[1].split("</li>")[0]
    client.post(f"/im/{PEER_CHAT}/bot/members/11", data={}, auth=AUTH, headers=HX)
    assert access(settings)["agent_users"] == []


def test_untrusting_a_member_removes_the_nick_written_by_hand(settings):
    class NickVk(FakeVk):
        def resolve_screen_names(self, names):
            return frozenset({11}) if "vasya" in names else frozenset()

    write_access(settings, {"agent_users": ["@vasya", 22]})
    client = TestClient(create_app(settings, vk_factory=NickVk, ai_factory=FakeAi), follow_redirects=False)
    panel = client.get(f"/im/{PEER_CHAT}/bot", auth=AUTH, headers=HX).text
    assert "checked" in panel.split("Вася Пупкин")[1].split("</li>")[0]
    client.post(f"/im/{PEER_CHAT}/bot/members/11", data={}, auth=AUTH, headers=HX)
    assert access(settings)["agent_users"] == [22]


def test_access_file_of_a_foreign_shape_is_never_overwritten_from_the_panel(client, settings):
    content = '{"agent_peers": [], "peer_prompts": ["заметка списком"]}'
    write_access(settings, content)
    for url, form in ((f"/im/{PEER_CHAT}/bot/listens", {"on": "1"}), (f"/im/{PEER_CHAT}/bot/note", {"text": "x"}),
                      (f"/im/{PEER_CHAT}/bot/members/11", {"on": "1"})):
        r = client.post(url, data=form, auth=AUTH, headers=HX)
        assert r.status_code == 422 and "peer_prompts" in json.loads(r.headers["HX-Trigger"])["toast"]["text"]
    with open(settings.access_file, encoding="utf-8") as f:
        assert f.read() == content


def test_bot_forms_without_htmx_redirect_to_chat(client, settings):
    r = client.post(f"/im/{PEER_CHAT}/bot/paused", data={"on": "1"}, auth=AUTH)
    assert r.status_code == 303 and r.headers["location"] == f"/im?sel={PEER_CHAT}"
    assert client.get(f"/im/{PEER_CHAT}/bot", auth=AUTH).status_code == 303


def test_panel_keeps_its_vk_look(client):
    r = client.get(f"/im/{PEER_CHAT}/bot", auth=AUTH, headers=HX)
    assert 'class="im-bot-head"' in r.text and '#cancel_24"' in r.text and '@click="panel = null"' in r.text
    assert r.text.count('role="switch" class="sw"') >= 4
    assert 'class="chip-p"' in r.text and 'name="slug" value="rina"' in r.text
    assert 'class="vk-btn"' in r.text and ">Сохранить<" in r.text
