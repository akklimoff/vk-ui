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
