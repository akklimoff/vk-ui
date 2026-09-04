import json
import os

import pytest

from tests.web.conftest import AUTH


def test_save_settings_writes_runtime(client, settings):
    r = client.post("/settings", data={"temperature": "0.5", "reply_delay_min": "1", "reply_delay_max": "2",
                                       "context_messages": "20", "dm_debounce_seconds": "8", "paused_peers": "2000000005, 7"}, auth=AUTH)
    assert r.status_code == 303
    d = json.load(open(settings.runtime_file))
    assert d["temperature"] == 0.5 and d["context_messages"] == 20 and d["paused_peers"] == [7, 2000000005]


def test_pause_toggle_keeps_other_fields(client, settings):
    json.dump({"active_persona": "v", "paused": False}, open(settings.runtime_file, "w"))
    client.post("/settings/pause", auth=AUTH)
    d = json.load(open(settings.runtime_file))
    assert d["paused"] is True and d["active_persona"] == "v"
    client.post("/settings/pause", auth=AUTH)
    assert json.load(open(settings.runtime_file))["paused"] is False


def test_bad_number_returns_400(client):
    r = client.post("/settings", data={"temperature": "hot", "reply_delay_min": "1", "reply_delay_max": "2",
                                       "context_messages": "20", "dm_debounce_seconds": "8", "paused_peers": ""}, auth=AUTH)
    assert r.status_code == 400


HX = {"HX-Request": "true"}
VALID = {"temperature": "0.5", "reply_delay_min": "1", "reply_delay_max": "2",
         "context_messages": "20", "dm_debounce_seconds": "8", "paused_peers": "2000000005, 7"}


def test_save_settings_hx_returns_form_partial_with_toast(client):
    r = client.post("/settings", data=VALID, auth=AUTH, headers=HX)
    assert r.status_code == 200 and "<html" not in r.text and 'id="settings-form"' in r.text
    assert 'value="0.5"' in r.text and "7, 2000000005" in r.text and "toast" in r.headers["HX-Trigger"]


def test_bad_number_hx_returns_422_with_error_and_kept_input(client, settings):
    r = client.post("/settings", data={**VALID, "temperature": "hot"}, auth=AUTH, headers=HX)
    assert r.status_code == 422 and 'class="error"' in r.text and 'value="hot"' in r.text
    assert not os.path.exists(settings.runtime_file)


def test_parse_runtime_form_names_bad_field():
    from web.services import parse_runtime_form
    with pytest.raises(ValueError, match="Температура.*hot"):
        parse_runtime_form({**VALID, "temperature": "hot"})
    with pytest.raises(ValueError, match="Чаты на паузе"):
        parse_runtime_form({**VALID, "paused_peers": "1, x"})
    assert parse_runtime_form(VALID) == {"temperature": 0.5, "reply_delay_min": 1.0, "reply_delay_max": 2.0,
                                         "context_messages": 20, "dm_debounce_seconds": 8.0,
                                         "paused_peers": [7, 2000000005]}
