import json

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
