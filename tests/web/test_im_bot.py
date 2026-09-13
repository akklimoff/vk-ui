import json

import pytest
from fastapi.testclient import TestClient

from tests.web.conftest import AUTH
from tests.web.im_fixtures import PEER_CHAT, PEER_USER
from tests.web.test_im_pages import FakeLlm, FakeVk
from web.app import create_app

HX = {"HX-Request": "true"}


@pytest.fixture
def client(settings):
    open(f"{settings.personas_dir}/rina.md", "w").write("# Рина\nперсона")
    open(f"{settings.personas_dir}/monika.md", "w").write("# Моника\nперсона")
    return TestClient(create_app(settings, vk_factory=FakeVk, llm_factory=FakeLlm), follow_redirects=False)


def access(settings):
    return json.load(open(settings.access_file))


def runtime(settings):
    return json.load(open(settings.runtime_file))


def test_panel_shows_mode_members_and_switches(client):
    r = client.get(f"/im/{PEER_CHAT}/bot", auth=AUTH, headers=HX)
    assert r.status_code == 200
    assert "по тегу" in r.text and 'name="on"' in r.text
    assert "Вася Пупкин" in r.text and "Аня Иванова" in r.text        # участники
    assert "Валентина Тина" not in r.text.split("Участники")[1]         # себя в списке нет
    assert "Рина" in r.text and "Моника" in r.text                      # персоны
    assert "Читать без отметки" in r.text


def test_switch_auto_in_chat_writes_access_and_updates_badge(client, settings):
    r = client.post(f"/im/{PEER_CHAT}/bot/auto", data={"on": "1"}, auth=AUTH, headers=HX)
    assert r.status_code == 200
    assert access(settings)["auto_reply_peers"] == [PEER_CHAT]
    assert 'id="chat-badge" hx-swap-oob="true"' in r.text and ">авто<" in r.text
    client.post(f"/im/{PEER_CHAT}/bot/auto", data={}, auth=AUTH, headers=HX)
    assert access(settings)["auto_reply_peers"] == []


def test_switch_auto_in_private_dialog_uses_user_list(client, settings):
    client.post(f"/im/{PEER_USER}/bot/auto", data={"on": "1"}, auth=AUTH, headers=HX)
    assert access(settings)["auto_reply_users"] == [PEER_USER]
    client.post(f"/im/{PEER_USER}/bot/blocked", data={"on": "1"}, auth=AUTH, headers=HX)
    assert access(settings)["blocked_users"] == [PEER_USER]


def test_onboarding_is_chats_only(client):
    assert client.post(f"/im/{PEER_USER}/bot/onboarding", data={"on": "1"}, auth=AUTH, headers=HX).status_code == 404
    assert client.post(f"/im/{PEER_CHAT}/bot/onboarding", data={"on": "1"}, auth=AUTH, headers=HX).status_code == 200


def test_pause_and_personas_go_to_runtime(client, settings):
    client.post(f"/im/{PEER_CHAT}/bot/paused", data={"on": "1"}, auth=AUTH, headers=HX)
    assert runtime(settings)["paused_peers"] == [PEER_CHAT]
    r = client.post(f"/im/{PEER_CHAT}/bot/personas", data={"slug": ["rina", "monika"]}, auth=AUTH, headers=HX)
    assert r.status_code == 200 and runtime(settings)["peer_personas"] == {str(PEER_CHAT): ["rina", "monika"]}
    client.post(f"/im/{PEER_CHAT}/bot/personas", data={"slug": ["nope"]}, auth=AUTH, headers=HX)
    assert runtime(settings)["peer_personas"] == {str(PEER_CHAT): ["rina", "monika"]}   # неизвестный slug — 422, файл не тронут
    client.post(f"/im/{PEER_CHAT}/bot/personas", data={}, auth=AUTH, headers=HX)
    assert runtime(settings)["peer_personas"] == {}


def test_prompt_goes_to_the_right_layer(client, settings):
    client.post(f"/im/{PEER_CHAT}/bot/prompt", data={"text": "тут все свои"}, auth=AUTH, headers=HX)
    assert access(settings)["peer_prompts"] == {str(PEER_CHAT): "тут все свои"}
    client.post(f"/im/{PEER_USER}/bot/prompt", data={"text": "подруга"}, auth=AUTH, headers=HX)
    assert access(settings)["user_prompts"] == {str(PEER_USER): "подруга"}


def test_member_block_in_chat(client, settings):
    client.post(f"/im/{PEER_CHAT}/bot/members/11", data={"on": "1"}, auth=AUTH, headers=HX)
    assert access(settings)["peer_blocked_users"] == {str(PEER_CHAT): [11]}
    r = client.get(f"/im/{PEER_CHAT}/bot", auth=AUTH, headers=HX)
    assert "checked" in r.text.split("Вася Пупкин")[1].split("</li>")[0]
