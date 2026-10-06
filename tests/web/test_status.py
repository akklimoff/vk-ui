import json
import os

from bot.agent import gate
from bot.agent.journal import ActionLog, ActionRecord
from bot.agent.rejections import RATE_LIMITED
from bot.status import write_json_atomic
from fastapi.testclient import TestClient

from tests.web.conftest import AUTH
from tests.web.fakes import FakeAi
from web.app import create_app
from web.state import status_view

HX = {"HX-Request": "true"}
CHAT, OTHER_CHAT, STRANGER = 2000000001, 2000000002, 9


def record(ts=1.0, model="grok-4.6", request="дай ссылку", outcome="replied"):
    return ActionRecord(ts=ts, peer_id=CHAT, from_id=5, role="trusted", place="chat", message_id=10, request=request,
                        calls=(), outcome=outcome, reply="держи", reply_message_ids=(21,), steps=1, duration_s=1.0,
                        model=model, prompt_tokens=1, completion_tokens=1, persona="rina")


def reject(settings, *rows):
    write_json_atomic(f"{settings.state_dir}/rejections.json", {"rejections": [
        {"ts": ts, "peer_id": peer, "from_id": user, "reason": reason, "count": count}
        for ts, peer, user, reason, count in rows]})


def test_requires_auth(client):
    assert client.get("/").status_code == 401
    assert client.get("/", auth=("x", "wrong")).status_code == 401
    assert client.get("/", auth=AUTH).status_code == 200


def test_status_view_connected_by_recent_event(settings):
    write_json_atomic(f"{settings.state_dir}/status.json",
                      {"me_id": 1, "me_name": "Валя", "model": "grok-4.6",
                       "last_event_at": 1000.0, "last_reply_at": None, "errors_last_hour": 2,
                       "active_persona": "valentina", "paused": False, "started_at": 900.0})
    v = status_view(settings.state_dir, now=1050.0)
    assert v.connected and v.last_event_ago == 50.0 and v.errors_last_hour == 2 and v.uptime == 150.0
    assert not status_view(settings.state_dir, now=2000.0).connected


def test_status_page_without_state_shows_offline(client):
    r = client.get("/", auth=AUTH)
    assert r.status_code == 200 and "не подключён" in r.text and "ещё не отвечала" in r.text


def test_status_hx_returns_partial_only(client):
    r = client.get("/", auth=AUTH, headers=HX)
    assert r.status_code == 200 and "<html" not in r.text and 'id="status"' in r.text


def test_pause_toggle_hx_returns_status_partial_with_toast(client):
    r = client.post("/settings/pause", auth=AUTH, headers=HX)
    assert r.status_code == 200 and 'id="status"' in r.text and "<html" not in r.text
    assert "на паузе" in r.text and json.loads(r.headers["HX-Trigger"])["toast"] == "Агент на паузе"
    again = client.post("/settings/pause", auth=AUTH, headers=HX)
    assert json.loads(again.headers["HX-Trigger"])["toast"] == "Агент снова слушает"


def test_status_view_takes_pause_and_persona_from_runtime(settings):
    write_json_atomic(f"{settings.state_dir}/status.json", {"paused": False, "active_persona": "old"})
    v = status_view(settings.state_dir, now=1.0, runtime={"paused": True, "active_persona": "new"})
    assert v.paused and v.active_persona == "new"


def test_model_is_the_one_that_answered_last(settings):
    assert status_view(settings.state_dir, now=1.0).model == ""
    ActionLog(f"{settings.state_dir}/actions.jsonl").append(record(model="claude-opus-5"))
    assert status_view(settings.state_dir, now=1.0).model == "Claude Opus 5"
    write_json_atomic(f"{settings.state_dir}/status.json", {"model": "grok-4.6"})
    same = status_view(settings.state_dir, now=1.0, runtime={"active_model": "grok-4.6"})
    assert (same.model, same.next_model) == ("Grok 4.6", "")
    switched = status_view(settings.state_dir, now=1.0, runtime={"active_model": "claude-opus-5"})
    assert (switched.model, switched.next_model) == ("Grok 4.6", "Claude Opus 5")


def test_status_json_of_the_previous_version_still_renders(client, settings):
    write_json_atomic(f"{settings.state_dir}/status.json",
                      {"me_id": 1, "me_name": "Валя", "provider": "grok", "model": "grok-4.3", "last_event_at": 1.0})
    from web.services import model_label

    page = client.get("/", auth=AUTH)
    assert page.status_code == 200 and model_label("grok-4.3") in page.text


def test_last_request_and_its_outcome_are_shown(client, settings):
    ActionLog(f"{settings.state_dir}/actions.jsonl").append(record(request="закрепи это", outcome="failed"))
    page = client.get("/", auth=AUTH).text
    assert "закрепи это" in page and "сбой" in page and 'href="/journal"' in page


def test_pending_confirmation_is_shown_until_it_expires(client, settings):
    import time

    rows = [{"peer_id": CHAT, "user_id": 1, "method": "wall.post", "title": "Опубликовать пост",
             "params": {"message": "текст поста"}, "asked_at": time.time(), "expires_at": time.time() + 200},
            {"peer_id": CHAT, "user_id": 2, "method": "messages.delete", "title": "Удалить сообщения", "params": {},
             "asked_at": 1.0, "expires_at": 2.0}]
    write_json_atomic(f"{settings.state_dir}/pending.json", {"pending": rows})
    page = client.get("/", auth=AUTH).text
    assert "Опубликовать пост" in page and "текст поста" in page and "Удалить сообщения" not in page


def test_rejections_explain_the_silence(client, settings):
    reject(settings, (3.0, CHAT, STRANGER, gate.CHAT_NOT_TRUSTED, 3), (2.0, 22, STRANGER, gate.PRIVATE_DIALOG, 1),
           (1.0, OTHER_CHAT, STRANGER, RATE_LIMITED, 1))
    page = client.get("/", auth=AUTH).text
    assert "беседа не в доверенных" in page and "×3" in page and "личный диалог" in page
    assert "сработал лимит частоты" in page


def test_rejection_that_no_longer_holds_is_not_shown(client, settings):
    reject(settings, (2.0, CHAT, STRANGER, gate.CHAT_NOT_TRUSTED, 1))
    with open(settings.access_file, "w", encoding="utf-8") as f:
        json.dump({"agent_peers": [CHAT]}, f)
    assert "беседа не в доверенных" not in client.get("/", auth=AUTH).text


def test_page_opens_over_garbage_in_every_state_file(client, settings):
    os.makedirs(settings.state_dir, exist_ok=True)
    for name in ("status.json", "pending.json", "rejections.json", "actions.jsonl"):
        with open(f"{settings.state_dir}/{name}", "w", encoding="utf-8") as f:
            f.write('{не json\n[1, 2]\n')
    assert client.get("/", auth=AUTH).status_code == 200
    for name in ("status.json", "pending.json", "rejections.json"):
        with open(f"{settings.state_dir}/{name}", "w", encoding="utf-8") as f:
            f.write("[1, 2]")
    assert client.get("/", auth=AUTH).status_code == 200


def test_untrusted_chat_links_to_the_trust_page_and_the_status_page_grants_nothing(client, settings):
    reject(settings, (2.0, CHAT, STRANGER, gate.CHAT_NOT_TRUSTED, 3), (1.0, 22, STRANGER, gate.PRIVATE_DIALOG, 1))
    page = client.get("/", auth=AUTH).text
    assert page.count("Доверять беседе") == 1 and f'href="/access?trust={CHAT}"' in page
    assert "/rejections/" not in page and page.count("<form") == 1
    assert client.post(f"/rejections/{CHAT}/trust", auth=AUTH).status_code == 404
    assert not os.path.exists(settings.access_file)


def test_person_trusted_by_a_hand_written_nick_is_not_shown_as_untrusted(settings):
    class NickVk:
        def __init__(self, token):
            pass

        def resolve_screen_names(self, names):
            return frozenset({STRANGER}) if names == {"masha"} else frozenset()

    reject(settings, (2.0, CHAT, STRANGER, gate.USER_NOT_TRUSTED, 1))
    with open(settings.access_file, "w", encoding="utf-8") as f:
        json.dump({"agent_users": ["@masha"], "agent_peers": [CHAT]}, f)
    client = TestClient(create_app(settings, vk_factory=NickVk, ai_factory=FakeAi), follow_redirects=False)
    assert "человек не в доверенных" not in client.get("/", auth=AUTH).text


def test_status_page_opens_while_vk_does_not_answer_about_nicks(settings):
    def no_vk(token):
        raise RuntimeError("VK недоступен")

    reject(settings, (2.0, CHAT, STRANGER, gate.USER_NOT_TRUSTED, 1))
    with open(settings.access_file, "w", encoding="utf-8") as f:
        json.dump({"agent_users": ["@masha"], "agent_peers": [CHAT]}, f)
    client = TestClient(create_app(settings, vk_factory=no_vk, ai_factory=FakeAi), follow_redirects=False)
    page = client.get("/", auth=AUTH)
    assert page.status_code == 200 and "человек не в доверенных" in page.text


def test_status_page_opens_over_times_that_are_not_finite(client, settings):
    os.makedirs(settings.state_dir, exist_ok=True)
    with open(f"{settings.state_dir}/status.json", "w", encoding="utf-8") as f:
        f.write('{"started_at": -Infinity, "last_event_at": Infinity, "last_reply_at": NaN}')
    page = client.get("/", auth=AUTH)
    assert page.status_code == 200
    view = status_view(settings.state_dir, now=1000.0)
    assert (view.connected, view.uptime, view.last_event_ago, view.last_reply_ago) == (False, None, None, None)
