import json
import os

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
