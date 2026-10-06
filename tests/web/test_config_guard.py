import json

import pytest
from fastapi.testclient import TestClient

from tests.web.conftest import AUTH
from tests.web.im_fixtures import PEER_CHAT
from tests.web.test_im_pages import DraftAi, FakeVk
from web.app import create_app
from web.services import BrokenConfig, read_config_for_update

HX = {"HX-Request": "true"}
TRAILING_COMMA = '{"agent_users": ["@masha"], "agent_peers": [2000000001], "peer_prompts": {"2000000001": "свои"},}'
NOT_AN_OBJECT = '["agent_users"]'
SETTINGS_FORM = {"temperature": "0.5", "reply_delay_min": "1", "reply_delay_max": "2", "context_messages": "20",
                 "dm_debounce_seconds": "8", "active_model": "", "paused_peers": ""}
ACCESS_WRITES = [
    ("/access/users", {"ref": "5"}),
    ("/access/users/remove", {"ref": "5"}),
    ("/access/peers", {"ref": "2000000009"}),
    (f"/access/peers/{PEER_CHAT}/remove", {}),
    (f"/access/peers/{PEER_CHAT}/note", {"text": "новая заметка"}),
    (f"/im/{PEER_CHAT}/bot/prompt", {"text": "новая заметка"}),
    (f"/im/{PEER_CHAT}/bot/members/11", {"on": "1"}),
    (f"/im/{PEER_CHAT}/bot/auto", {"on": "1"}),
]
RUNTIME_WRITES = [
    ("/settings", SETTINGS_FORM),
    ("/settings/pause", {}),
    ("/personas/rina/activate", {}),
    (f"/im/{PEER_CHAT}/bot/personas", {"slug": ["rina"]}),
    (f"/im/{PEER_CHAT}/bot/paused", {"on": "1"}),
]
WRITES = ([("access_file", url, form) for url, form in ACCESS_WRITES]
          + [("runtime_file", url, form) for url, form in RUNTIME_WRITES])


@pytest.fixture
def client(settings):
    with open(f"{settings.personas_dir}/rina.md", "w", encoding="utf-8") as f:
        f.write("# Рина\nперсона")
    return TestClient(create_app(settings, vk_factory=FakeVk, ai_factory=DraftAi), follow_redirects=False)


def spoil(path: str, content: str) -> bytes:
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return content.encode()


def read_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def file_name(settings, which: str) -> str:
    return getattr(settings, which).rsplit("/", 1)[-1]


@pytest.mark.parametrize("content", [TRAILING_COMMA, NOT_AN_OBJECT])
@pytest.mark.parametrize("which,url,form", WRITES)
def test_plain_save_over_broken_file_is_400_and_leaves_it_untouched(client, settings, which, url, form, content):
    before = spoil(getattr(settings, which), content)
    r = client.post(url, data=form, auth=AUTH)
    assert r.status_code == 400 and file_name(settings, which) in r.json()["detail"]
    assert read_bytes(getattr(settings, which)) == before


@pytest.mark.parametrize("content", [TRAILING_COMMA, NOT_AN_OBJECT])
@pytest.mark.parametrize("which,url,form", WRITES)
def test_htmx_save_over_broken_file_is_422_and_leaves_it_untouched(client, settings, which, url, form, content):
    before = spoil(getattr(settings, which), content)
    r = client.post(url, data=form, auth=AUTH, headers=HX)
    assert r.status_code == 422 and "<html" not in r.text
    assert file_name(settings, which) in json.loads(r.headers["HX-Trigger"])["toast"]["text"]
    assert read_bytes(getattr(settings, which)) == before


def test_broken_access_is_named_on_the_trust_page(client, settings):
    spoil(settings.access_file, TRAILING_COMMA)
    r = client.post("/access/users", data={"ref": "777"}, auth=AUTH, headers=HX)
    assert 'class="error"' in r.text and "access.json" in r.text
    assert "access.json" in client.get("/access", auth=AUTH).text


def test_broken_runtime_keeps_the_entered_settings(client, settings):
    spoil(settings.runtime_file, TRAILING_COMMA)
    r = client.post("/settings", data={**SETTINGS_FORM, "temperature": "0.33"}, auth=AUTH, headers=HX)
    assert 'class="error"' in r.text and "runtime.json" in r.text and 'value="0.33"' in r.text


def test_broken_access_keeps_the_entered_chat_note(client, settings):
    spoil(settings.access_file, TRAILING_COMMA)
    r = client.post(f"/im/{PEER_CHAT}/bot/prompt", data={"text": "новая заметка"}, auth=AUTH, headers=HX)
    assert 'class="error"' in r.text and "access.json" in r.text and ">новая заметка</textarea>" in r.text


def test_missing_file_is_an_empty_config(tmp_path):
    assert read_config_for_update(str(tmp_path / "nope.json")) == {}


@pytest.mark.parametrize("content", [TRAILING_COMMA, NOT_AN_OBJECT, "", "null"])
def test_unusable_file_is_refused_by_name(tmp_path, content):
    path = tmp_path / "access.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(BrokenConfig, match="access.json"):
        read_config_for_update(str(path))


class VkWithoutMembers(FakeVk):
    def members(self, peer_id):
        raise RuntimeError("VK недоступен")


def test_refusal_names_the_file_even_when_the_panel_cannot_be_rebuilt(settings):
    client = TestClient(create_app(settings, vk_factory=VkWithoutMembers, ai_factory=DraftAi), follow_redirects=False)
    before = spoil(settings.access_file, TRAILING_COMMA)
    r = client.post(f"/im/{PEER_CHAT}/bot/prompt", data={"text": "новая заметка"}, auth=AUTH, headers=HX)
    assert r.status_code == 422
    assert "access.json" in json.loads(r.headers["HX-Trigger"])["toast"]["text"]
    assert read_bytes(settings.access_file) == before
