import html
import json
import os
import re

from tests.web.conftest import AUTH
from web.services import parse_access_form


def test_parse_access_form_builds_config():
    data = parse_access_form({
        "blocked_users": "123\n@spam", "blocked_peers": "2000000005", "allowed_peers": "",
        "auto_reply_users": "@bob", "private_prompt": "лично\nдве строки",
        "user_prompts": "@bob: это Боб\n@ann: это Аня",
    })
    assert data["blocked_users"] == ["123", "@spam"]
    assert data["allowed_peers"] == []
    assert data["private_prompt"] == ["лично", "две строки"]
    assert data["user_prompts"] == {"@bob": "это Боб", "@ann": "это Аня"}


def test_save_access_roundtrip(client, settings):
    r = client.post("/access", data={"blocked_users": "1", "blocked_peers": "", "allowed_peers": "",
                                     "auto_reply_users": "@bob", "private_prompt": "п",
                                     "user_prompts": "@bob: б"}, auth=AUTH)
    assert r.status_code == 303
    saved = json.load(open(settings.access_file))
    assert saved["auto_reply_users"] == ["@bob"] and saved["user_prompts"] == {"@bob": "б"}
    page = client.get("/access", auth=AUTH).text
    assert "@bob: б" in page


def test_saving_the_form_keeps_the_keys_it_does_not_show(client, settings):
    with open(settings.access_file, "w", encoding="utf-8") as f:
        json.dump({"agent_users": ["@masha", 7], "agent_peers": [2000000001], "blocked_users": ["5"]}, f)
    r = client.post("/access", data={**BLANK, "blocked_users": "1"}, auth=AUTH)
    assert r.status_code == 303
    saved = json.load(open(settings.access_file))
    assert saved["agent_users"] == ["@masha", 7] and saved["agent_peers"] == [2000000001]
    assert saved["blocked_users"] == ["1"]


def test_invalid_peer_returns_400(client):
    r = client.post("/access", data={"blocked_users": "", "blocked_peers": "abc", "allowed_peers": "",
                                     "auto_reply_users": "", "private_prompt": "", "user_prompts": ""}, auth=AUTH)
    assert r.status_code == 400


HX = {"HX-Request": "true"}
BLANK = {"blocked_users": "", "blocked_peers": "", "allowed_peers": "", "auto_reply_users": "",
         "private_prompt": "", "user_prompts": ""}


def test_save_access_hx_returns_form_partial_with_toast(client):
    r = client.post("/access", data={**BLANK, "auto_reply_users": "@bob"}, auth=AUTH, headers=HX)
    assert r.status_code == 200 and "<html" not in r.text and 'id="access-form"' in r.text
    assert "@bob" in r.text and "toast" in r.headers["HX-Trigger"]


def test_invalid_peer_hx_returns_422_with_error_and_kept_input(client, settings):
    r = client.post("/access", data={**BLANK, "blocked_peers": "abc"}, auth=AUTH, headers=HX)
    assert r.status_code == 422 and 'class="error"' in r.text and ">abc</textarea>" in r.text
    assert not os.path.exists(settings.access_file)


def posted_back(client) -> dict:
    """Форма страницы в том виде, в каком её отправит браузер: переводы строк в textarea — CRLF."""
    page = client.get("/access", auth=AUTH).text
    fields = re.findall(r'<textarea name="(\w+)"[^>]*>(.*?)</textarea>', page, re.S)
    return {name: html.unescape(text).replace("\n", "\r\n") for name, text in fields}


AWKWARD_NOTES = {
    "peer_prompts": {"2000000001": "тут друзья\n2000000002: шутки", "2000000003": "одна строка",
                     "2000000004": "абзац\n\nещё абзац", "2000000005": "  с отступом ",
                     "2000000006": ["строка", "ещё строка"], "2000000007": "ссылка: https://vk.com"},
    "user_prompts": {"@bob": "это Боб\nлюбит кофе", "@ann": "это Аня", "42": "без двоеточия\nстрока"},
}


def store_awkward_notes(settings) -> None:
    with open(settings.access_file, "w", encoding="utf-8") as f:
        json.dump(AWKWARD_NOTES, f, ensure_ascii=False)


def stored(settings) -> dict:
    with open(settings.access_file, encoding="utf-8") as f:
        return json.load(f)


def test_posting_the_rendered_form_back_keeps_every_note(client, settings):
    store_awkward_notes(settings)
    r = client.post("/access", data=posted_back(client), auth=AUTH)
    assert r.status_code == 303
    assert stored(settings)["peer_prompts"] == AWKWARD_NOTES["peer_prompts"]
    assert stored(settings)["user_prompts"] == AWKWARD_NOTES["user_prompts"]


def test_one_line_notes_stay_editable_next_to_kept_ones(client, settings):
    store_awkward_notes(settings)
    form = posted_back(client)
    assert form["peer_prompts"].splitlines() == ["2000000003: одна строка", "2000000007: ссылка: https://vk.com"]
    form["peer_prompts"] = "2000000003: по-новому\r\n2000000009: новая беседа"
    client.post("/access", data=form, auth=AUTH)
    saved = stored(settings)["peer_prompts"]
    assert saved["2000000003"] == "по-новому" and saved["2000000009"] == "новая беседа"
    assert "2000000007" not in saved
    assert saved["2000000001"] == "тут друзья\n2000000002: шутки" and saved["2000000004"] == "абзац\n\nещё абзац"


def test_page_names_the_notes_it_does_not_show(client, settings):
    store_awkward_notes(settings)
    for page in (client.get("/access", auth=AUTH).text,
                 client.post("/access", data=posted_back(client), auth=AUTH, headers=HX).text):
        assert "2000000001, 2000000004, 2000000005, 2000000006" in page and "@bob, 42" in page
        assert "шутки" not in page
