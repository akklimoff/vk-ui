import json

import pytest
from fastapi.testclient import TestClient

from ai.service import AiService
from tests.web.conftest import AUTH
from web.app import create_app

ME = 1


def chat(peer_id, title, can_moderate, members=10):
    return {"peer": {"id": peer_id, "type": "chat"},
            "chat_settings": {"title": title, "members_count": members, "acl": {"can_moderate": can_moderate}}}


CHATS = [chat(2000000001, "Флуд", True, 40), chat(2000000002, "Чужая", False, 9)]
FRIENDS = [{"id": 20, "first_name": "Петя", "last_name": "П", "photo_50": "p.jpg"}]


class FakeVk:
    me_id = ME

    def __init__(self, token):
        pass

    def chats(self):
        return CHATS

    def friends(self):
        return FRIENDS


def app_client(settings, ai_settings, vk=FakeVk):
    return TestClient(create_app(settings, vk_factory=vk, ai_factory=lambda s: AiService(ai_settings)),
                      follow_redirects=False)


@pytest.fixture
def mclient(settings, ai_settings):
    return app_client(settings, ai_settings)


def test_page_lists_chats_with_rights_and_friends(mclient):
    body = mclient.get("/moderation", auth=AUTH).text
    assert "Флуд" in body and "Чужая" in body and "Петя П" in body
    assert body.count("нет прав админа") == 1


def test_saved_choices_are_checked(mclient, settings):
    with open(settings.moderation_file, "w") as f:
        json.dump({"admin_peers": [2000000002], "trusted_users": [20]}, f)
    body = mclient.get("/moderation", auth=AUTH).text
    assert 'value="2000000002" checked' in body and 'value="20" checked' in body
    assert 'value="2000000001" checked' not in body


def test_save_writes_config_and_redirects(mclient, settings):
    r = mclient.post("/moderation", auth=AUTH, data={"peer": ["2000000001"], "user": ["20"]})
    assert r.status_code == 303
    with open(settings.moderation_file) as f:
        assert json.load(f) == {"admin_peers": [2000000001], "trusted_users": [20]}


def test_save_with_nothing_checked_clears_config(mclient, settings):
    mclient.post("/moderation", auth=AUTH, data={"peer": ["2000000001"]})
    mclient.post("/moderation", auth=AUTH, data={})
    with open(settings.moderation_file) as f:
        assert json.load(f) == {"admin_peers": [], "trusted_users": []}


def test_htmx_save_returns_partial_with_toast(mclient):
    r = mclient.post("/moderation", auth=AUTH, data={"peer": ["2000000001"]}, headers={"HX-Request": "true"})
    assert r.status_code == 200 and "toast" in r.headers["HX-Trigger"] and "<html" not in r.text


def test_bad_id_is_rejected(mclient, settings):
    r = mclient.post("/moderation", auth=AUTH, data={"peer": ["abc"]}, headers={"HX-Request": "true"})
    assert r.status_code == 422


def test_lost_entries_stay_visible_to_uncheck(mclient, settings):
    with open(settings.moderation_file, "w") as f:
        json.dump({"admin_peers": [2000000077], "trusted_users": [77]}, f)
    body = mclient.get("/moderation", auth=AUTH).text
    assert "id77" in body and "не в друзьях" in body and "2000000077" in body


def test_vk_failure_shows_error_instead_of_500(settings, ai_settings):
    class Broken(FakeVk):
        def chats(self):
            raise RuntimeError("сеть упала")

    r = app_client(settings, ai_settings, Broken).get("/moderation", auth=AUTH)
    assert r.status_code == 200 and "сеть упала" in r.text
