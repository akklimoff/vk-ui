from bot.status import write_json_atomic
from tests.web.conftest import AUTH
from web.services import status_view


def test_requires_auth(client):
    assert client.get("/").status_code == 401
    assert client.get("/", auth=("x", "wrong")).status_code == 401
    assert client.get("/", auth=AUTH).status_code == 200


def test_status_view_connected_by_recent_event(settings):
    write_json_atomic(f"{settings.state_dir}/status.json",
                      {"me_id": 1, "me_name": "Валя", "provider": "grok", "model": "m",
                       "last_event_at": 1000.0, "last_reply_at": None, "errors_last_hour": 2,
                       "active_persona": "valentina", "paused": False, "started_at": 900.0})
    v = status_view(settings.state_dir, now=1050.0)
    assert v.connected and v.last_event_ago == 50.0 and v.errors_last_hour == 2
    assert not status_view(settings.state_dir, now=2000.0).connected


def test_status_page_without_state_shows_offline(client):
    r = client.get("/", auth=AUTH)
    assert r.status_code == 200 and "не подключён" in r.text


def test_status_view_uptime_from_started_at(settings):
    write_json_atomic(f"{settings.state_dir}/status.json", {"started_at": 900.0, "last_event_at": 1000.0})
    assert status_view(settings.state_dir, now=1050.0).uptime == 150.0
    assert status_view(settings.state_dir, now=1050.0).connected


def test_status_hx_returns_partial_only(client):
    r = client.get("/", auth=AUTH, headers={"HX-Request": "true"})
    assert r.status_code == 200 and "<html" not in r.text and 'id="status"' in r.text


def test_pause_toggle_hx_returns_status_partial_with_toast(client):
    r = client.post("/settings/pause", auth=AUTH, headers={"HX-Request": "true"})
    assert r.status_code == 200 and 'id="status"' in r.text and "<html" not in r.text
    assert "на паузе" in r.text and "toast" in r.headers["HX-Trigger"]


def test_status_view_takes_pause_and_persona_from_runtime(settings):
    write_json_atomic(f"{settings.state_dir}/status.json", {"paused": False, "active_persona": "old"})
    v = status_view(settings.state_dir, now=1.0, runtime={"paused": True, "active_persona": "new"})
    assert v.paused and v.active_persona == "new"


def test_status_view_shows_the_model_chosen_in_runtime(settings):
    write_json_atomic(f"{settings.state_dir}/status.json", {"provider": "grok", "model": "grok-4.3"})
    same = status_view(settings.state_dir, now=1.0, runtime={})
    assert (same.provider, same.model) == ("grok", "grok-4.3")
    switched = status_view(settings.state_dir, now=1.0, runtime={"active_model": "claude-opus-5"})
    assert (switched.provider, switched.model) == ("claude", "Claude Opus 5")


def test_status_page_labels_interview_chat(client, settings):
    write_json_atomic(f"{settings.state_dir}/onboarding.json", {"2000000001": {"558": {"asked": 1}}})
    assert "беседа 1" in client.get("/", auth=AUTH).text
