import json

import pytest
from fastapi.testclient import TestClient

from tests.web.conftest import AUTH
from tests.web.fakes import FakeAi
from web.app import create_app

HX = {"HX-Request": "true"}
CHAT, LEFT_CHAT = 2000000001, 2000000002


class TrustVk:
    me_id = 1

    def __init__(self, token):
        pass

    def call(self, method, params):
        if method == "users.get":
            known = {"5": {"id": 5, "first_name": "Маша", "last_name": "Иванова", "screen_name": "id5"},
                     "11": {"id": 11, "first_name": "Вася", "last_name": "Пупкин", "screen_name": "vasya"},
                     "vasya": {"id": 11, "first_name": "Вася", "last_name": "Пупкин", "screen_name": "vasya"}}
            return [known[ref] for ref in params["user_ids"].split(",") if ref in known]
        return {"items": [{"peer": {"id": CHAT}, "chat_settings": {"title": "лампочки", "state": "in"}},
                          {"peer": {"id": LEFT_CHAT}, "chat_settings": {"title": "старая беседа", "state": "left"}}]}

    def resolve_screen_names(self, names):
        return frozenset({"masha": 77, "vasya": 11}[name] for name in names if name in ("masha", "vasya"))


@pytest.fixture
def client(settings):
    return TestClient(create_app(settings, vk_factory=TrustVk, ai_factory=FakeAi), follow_redirects=False)


def stored(settings):
    with open(settings.access_file, encoding="utf-8") as f:
        return json.load(f)


def write(settings, data):
    with open(settings.access_file, "w", encoding="utf-8") as f:
        f.write(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False))


def test_page_names_people_and_chats(client, settings):
    write(settings, {"agent_users": [5, "@sasha"], "agent_peers": [CHAT, LEFT_CHAT],
                     "peer_prompts": {str(CHAT): "первая\nвторая"}})
    page = client.get("/access", auth=AUTH).text
    assert "Маша Иванова" in page and "@sasha" in page
    assert "лампочки" in page and "старая беседа" in page
    assert page.count("аккаунт не в беседе") == 1
    assert "первая\nвторая</textarea>" in page
    assert "Доверие" in page and "blocked_users" not in page and "auto_reply" not in page
    assert page.count("не найден") == 1


def test_nick_from_the_file_is_shown_with_the_person_it_points_to(client, settings):
    write(settings, {"agent_users": ["@vasya"]})
    page = client.get("/access", auth=AUTH).text
    assert "Вася Пупкин" in page and "id11" in page and "@vasya" in page and "не найден" not in page


def test_removing_a_person_removes_the_nick_that_points_to_them(client, settings):
    write(settings, {"agent_users": [11, "@vasya", 5]})
    client.post("/access/users/remove", data={"ref": "11"}, auth=AUTH)
    assert stored(settings)["agent_users"] == [5]
    write(settings, {"agent_users": [11, "@vasya", 5]})
    client.post("/access/users/remove", data={"ref": "@vasya"}, auth=AUTH)
    assert stored(settings)["agent_users"] == [5]


def test_person_stays_trusted_and_the_page_says_so_when_the_nick_cannot_be_checked(settings):
    class NoNicksVk(TrustVk):
        def resolve_screen_names(self, names):
            raise RuntimeError("нет связи")

    write(settings, {"agent_users": [11, "@vasya"]})
    client = TestClient(create_app(settings, vk_factory=NoNicksVk, ai_factory=FakeAi), follow_redirects=False)
    r = client.post("/access/users/remove", data={"ref": "11"}, auth=AUTH, headers=HX)
    assert r.status_code == 422 and 'class="error"' in r.text and "@vasya" in r.text
    assert stored(settings)["agent_users"] == [11, "@vasya"]


def test_empty_page_says_who_is_heard(client):
    page = client.get("/access", auth=AUTH).text
    assert "только владельца" in page and "Доверенных бесед нет" in page


def test_person_is_added_by_nick_and_stored_by_id(client, settings):
    r = client.post("/access/users", data={"ref": "https://vk.com/masha"}, auth=AUTH)
    assert r.status_code == 303 and r.headers["location"] == "/access"
    assert stored(settings)["agent_users"] == [77]


def test_unknown_nick_is_a_form_error_with_the_input_kept(client, settings):
    r = client.post("/access/users", data={"ref": "@nobody"}, auth=AUTH, headers=HX)
    assert r.status_code == 422 and "<html" not in r.text
    assert 'class="error"' in r.text and 'value="@nobody"' in r.text
    assert client.post("/access/users", data={"ref": "@nobody"}, auth=AUTH).status_code == 400


def test_person_is_removed_by_id_or_by_the_nick_from_the_file(client, settings):
    write(settings, {"agent_users": [5, "@sasha", 9]})
    client.post("/access/users/remove", data={"ref": "5"}, auth=AUTH)
    client.post("/access/users/remove", data={"ref": "@sasha"}, auth=AUTH)
    assert stored(settings)["agent_users"] == [9]


def test_chat_is_trusted_by_peer_id_or_number_and_untrusted_again(client, settings):
    r = client.post("/access/peers", data={"ref": "1"}, auth=AUTH, headers=HX)
    assert r.status_code == 200 and 'id="trust"' in r.text and "toast" in r.headers["HX-Trigger"]
    client.post("/access/peers", data={"ref": str(LEFT_CHAT)}, auth=AUTH)
    assert stored(settings)["agent_peers"] == [CHAT, LEFT_CHAT]
    client.post(f"/access/peers/{CHAT}/remove", auth=AUTH)
    assert stored(settings)["agent_peers"] == [LEFT_CHAT]


def test_private_dialog_cannot_be_trusted(client, settings):
    r = client.post("/access/peers", data={"ref": "свои"}, auth=AUTH, headers=HX)
    assert r.status_code == 422 and 'value="свои"' in r.text
    assert client.post("/access/peers/22/note", data={"text": "x"}, auth=AUTH).status_code == 400
    assert client.post("/access/peers/22/remove", auth=AUTH).status_code == 303


def test_multiline_note_survives_a_save_and_empty_text_removes_it(client, settings):
    write(settings, {"agent_peers": [CHAT]})
    client.post(f"/access/peers/{CHAT}/note", data={"text": "первая\r\nвторая: с двоеточием\r\n"}, auth=AUTH)
    assert stored(settings)["peer_prompts"] == {str(CHAT): "первая\nвторая: с двоеточием"}
    client.post(f"/access/peers/{CHAT}/note", data={"text": "  "}, auth=AUTH)
    assert stored(settings)["peer_prompts"] == {}


def test_saving_keeps_every_key_the_page_does_not_show(client, settings):
    write(settings, {"blocked_users": ["5"], "user_prompts": {"@bob": "б"}, "agent_users": [7]})
    client.post("/access/peers", data={"ref": str(CHAT)}, auth=AUTH)
    assert stored(settings) == {"blocked_users": ["5"], "user_prompts": {"@bob": "б"}, "agent_users": [7],
                                "agent_peers": [CHAT], "peer_prompts": {}}


@pytest.mark.parametrize("content", ['{"peer_prompts": ["заметка"]}', '{"agent_peers": "2000000001"}'])
def test_file_of_a_foreign_shape_is_shown_as_an_error_and_never_overwritten(client, settings, content):
    write(settings, content)
    page = client.get("/access", auth=AUTH)
    assert page.status_code == 200 and 'class="error"' in page.text
    r = client.post("/access/peers", data={"ref": str(CHAT)}, auth=AUTH, headers=HX)
    assert r.status_code == 422 and 'class="error"' in r.text
    with open(settings.access_file, encoding="utf-8") as f:
        assert f.read() == content


def test_page_opens_when_vk_is_down(settings):
    class DownVk(TrustVk):
        def call(self, method, params):
            raise RuntimeError("нет связи")

    write(settings, {"agent_users": [5], "agent_peers": [CHAT]})
    client = TestClient(create_app(settings, vk_factory=DownVk, ai_factory=FakeAi), follow_redirects=False)
    page = client.get("/access", auth=AUTH)
    assert page.status_code == 200 and "id5" in page.text and "VK не ответил" in page.text


ASKED_HERE = "Агента отметили в этой беседе"


def test_chat_from_the_status_page_is_shown_with_its_title_and_trusted_only_by_the_form(client, settings):
    page = client.get(f"/access?trust={CHAT}", auth=AUTH)
    assert page.status_code == 200 and ASKED_HERE in page.text and "лампочки" in page.text
    with pytest.raises(FileNotFoundError):
        stored(settings)
    client.post("/access/peers", data={"ref": str(CHAT)}, auth=AUTH)
    assert stored(settings)["agent_peers"] == [CHAT]
    assert ASKED_HERE not in client.get(f"/access?trust={CHAT}", auth=AUTH).text


def test_candidate_the_account_has_left_is_flagged(client):
    page = client.get(f"/access?trust={LEFT_CHAT}", auth=AUTH).text
    assert ASKED_HERE in page and "старая беседа" in page and page.count("аккаунт не в беседе") == 1


@pytest.mark.parametrize("forged", ["22", "-5", "0", "2000000000", "свои", "²", "2000000001 or 1", ""])
def test_forged_trust_address_offers_nothing_and_writes_nothing(client, settings, forged):
    page = client.get("/access", params={"trust": forged}, auth=AUTH)
    assert page.status_code == 200 and ASKED_HERE not in page.text
    with pytest.raises(FileNotFoundError):
        stored(settings)
