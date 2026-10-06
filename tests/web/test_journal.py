import json
import os

import pytest
from fastapi.testclient import TestClient

from bot.agent.journal import ActionLog, ActionRecord
from tests.web.conftest import AUTH
from web import journal
from web.app import create_app

HX = {"HX-Request": "true"}
CHAT = 2000000001
PIN = {"method": "messages.pin", "params": {"peer_id": CHAT, "conversation_message_id": 7}, "verdict": "allowed",
       "reason": "", "ok": True, "error_code": None}
DENIED = {"method": "wall.post", "params": {"message": "пост"}, "verdict": "refused",
          "reason": "этому человеку так нельзя", "ok": None, "error_code": None}
FLOOD = {"method": "messages.send", "params": {"message": "эй"}, "verdict": "allowed", "reason": "", "ok": False,
         "error_code": 9}


class FakeVk:
    def __init__(self, token):
        self.deleted = []

    def delete_message(self, message_id):
        self.deleted.append(message_id)


@pytest.fixture
def client(settings):
    return TestClient(create_app(settings, vk_factory=FakeVk), follow_redirects=False)


def record(ts=1.0, peer_id=CHAT, request="закрепи это", reply="закрепила", calls=(PIN,), outcome="replied",
           ids=(21,), role="trusted", place="chat"):
    return ActionRecord(ts=ts, peer_id=peer_id, from_id=5, role=role, place=place, message_id=10, request=request,
                        calls=tuple(calls), outcome=outcome, reply=reply, reply_message_ids=tuple(ids), steps=2,
                        duration_s=1.5, model="grok-4.6", prompt_tokens=100, completion_tokens=20, persona="rina")


def log(settings, *records):
    actions = ActionLog(f"{settings.state_dir}/actions.jsonl")
    for item in records:
        actions.append(item)


def test_journal_shows_the_request_its_calls_and_the_outcome(client, settings):
    log(settings, record(calls=(PIN, DENIED, FLOOD)))
    page = client.get("/journal", auth=AUTH).text
    assert "закрепи это" in page and "закрепила" in page
    assert "messages.pin" in page and "conversation_message_id" in page and "выполнен" in page
    assert "wall.post" in page and "отказ" in page and "этому человеку так нельзя" in page
    assert "ошибка 9" in page
    assert "доверенный" in page and "беседа 1" in page and "ответила" in page
    assert "шагов 2" in page and "1.5 с" in page and "100+20" in page and "rina" in page
    assert "Журнал" in page


def test_newest_request_is_first(client, settings):
    log(settings, record(1.0, request="первая"), record(2.0, request="вторая"))
    page = client.get("/journal", auth=AUTH).text
    assert page.index("вторая") < page.index("первая")


def test_outcome_and_place_are_named_for_the_owner_in_saved(client, settings):
    log(settings, record(peer_id=1, role="owner", place="saved", outcome="needs_confirmation", calls=(), ids=()))
    page = client.get("/journal", auth=AUTH).text
    assert "владелец" in page and "Избранное" in page and "ждёт «да»" in page
    assert "/journal/replies/" not in page


def test_page_shows_only_the_known_fields_of_a_call(client, settings):
    os.makedirs(settings.state_dir, exist_ok=True)
    line = json.loads(json.dumps(record().__dict__))
    line["calls"] = [{**PIN, "result": "ЧУЖАЯ ПЕРЕПИСКА", "response": {"items": ["ЕЩЁ ЧУЖОЕ"]}}]
    with open(f"{settings.state_dir}/actions.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
    page = client.get("/journal", auth=AUTH).text
    assert "messages.pin" in page and "ЧУЖАЯ ПЕРЕПИСКА" not in page and "ЕЩЁ ЧУЖОЕ" not in page


def test_call_view_survives_a_malformed_call():
    assert journal.call_view("строка").method == "—"
    odd = journal.call_view({"method": "users.get", "params": ["не объект"], "verdict": "новый вердикт", "ok": False})
    assert (odd.params, odd.verdict, odd.status, odd.bad) == ((), "новый вердикт", "сбой", True)
    assert journal.call_view({"params": {"ids": [1, 2]}}).params == (("ids", "[1, 2]"),)


def test_journal_opens_over_garbage_and_lines_of_another_format(client, settings):
    os.makedirs(settings.state_dir, exist_ok=True)
    with open(f"{settings.state_dir}/actions.jsonl", "w", encoding="utf-8") as f:
        f.write('{не json\n{"ts": 1, "reply": "строка старого журнала ответов"}\n[]\n')
    log(settings, record(request="настоящая"))
    page = client.get("/journal", auth=AUTH)
    assert page.status_code == 200 and "настоящая" in page.text and "строка старого" not in page.text


def test_empty_journal_says_so(client):
    page = client.get("/journal", auth=AUTH).text
    assert 'id="feed-empty"' in page and "hidden" not in page.split('id="feed-empty"')[1].split(">")[0]


def test_hx_after_returns_only_newer_cards_and_the_next_poller(client, settings):
    log(settings, record(1.0, request="первая"), record(2.0, peer_id=CHAT + 1, request="вторая"))
    r = client.get("/journal?after=1", auth=AUTH, headers=HX)
    assert r.status_code == 200 and "<html" not in r.text
    assert "вторая" in r.text and "первая" not in r.text
    assert 'id="journal-poll"' in r.text and "after=2.0" in r.text and "hx-swap-oob" in r.text
    assert "hx-swap-oob" in r.text.split('id="feed-empty"')[1].split(">")[0]


def test_filter_by_chat_stays_in_the_poller(client, settings):
    log(settings, record(1.0, request="первая"), record(2.0, peer_id=CHAT + 1, request="вторая"))
    page = client.get(f"/journal?peer={CHAT + 1}", auth=AUTH).text
    assert "вторая" in page and "первая" not in page and f"peer={CHAT + 1}" in page
    assert page.count('id="journal-poll"') == 1 and page.index('id="journal-poll"') < page.index('id="feed"')


def test_reply_is_deleted_with_all_its_parts(client, settings):
    log(settings, record(ids=(21, 22)))
    r = client.post("/journal/replies/21/delete", auth=AUTH)
    assert r.status_code == 303 and r.headers["location"] == "/journal"
    assert client.app.state.vk.deleted == [21, 22]
    hx = client.post("/journal/replies/22/delete", auth=AUTH, headers=HX)
    assert hx.status_code == 200 and "удалён" in hx.text


def test_only_a_message_the_journal_knows_can_be_deleted(client, settings):
    log(settings, record(ids=(21,)))
    assert client.post("/journal/replies/999/delete", auth=AUTH).status_code == 404
    assert client.app.state.vk is None or client.app.state.vk.deleted == []


def damaged(settings, **fields):
    from dataclasses import asdict

    os.makedirs(settings.state_dir, exist_ok=True)
    with open(f"{settings.state_dir}/actions.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({**asdict(record(request="испорченная запись")), **fields}, ensure_ascii=False) + "\n")


@pytest.mark.parametrize("fields", [
    {"ts": "вчера"}, {"ts": None}, {"ts": float("inf")}, {"ts": float("nan")}, {"ts": True}, {"ts": 10 ** 400},
    {"peer_id": "беседа"}, {"peer_id": 1.5}, {"from_id": None}, {"outcome": ["replied"]}, {"role": {"a": 1}},
    {"model": 5}, {"request": None}, {"duration_s": "долго"}, {"steps": "много"},
    {"reply_message_ids": ["21"]}, {"reply_message_ids": [None]}, {"reply_message_ids": [21.5]},
], ids=lambda fields: next(iter(fields)))
def test_records_with_fields_of_a_wrong_type_are_skipped(client, settings, fields):
    log(settings, record(request="целая запись"))
    damaged(settings, **fields)
    for url in ("/journal", "/"):
        for headers in ({}, HX):
            page = client.get(url, auth=AUTH, headers=headers)
            assert page.status_code == 200 and "испорченная запись" not in page.text
    assert "целая запись" in client.get("/journal", auth=AUTH).text


@pytest.mark.parametrize("ids", [["x"], [None], [21.5], [21, "22"]])
def test_reply_with_ids_that_are_not_numbers_cannot_be_deleted(client, settings, ids):
    damaged(settings, reply_message_ids=ids)
    assert client.post("/journal/replies/21/delete", auth=AUTH).status_code == 404
    assert client.app.state.vk is None or client.app.state.vk.deleted == []


def test_delete_address_that_is_not_a_number_is_refused(client, settings):
    log(settings, record(ids=(21,)))
    assert client.post("/journal/replies/abc/delete", auth=AUTH).status_code == 422
    assert client.app.state.vk is None or client.app.state.vk.deleted == []


def test_delete_failure_is_502_with_the_reason(settings):
    class BrokenVk(FakeVk):
        def delete_message(self, message_id):
            raise RuntimeError("[15] Access denied")

    log(settings, record(ids=(21,)))
    client = TestClient(create_app(settings, vk_factory=BrokenVk), follow_redirects=False)
    r = client.post("/journal/replies/21/delete", auth=AUTH)
    assert r.status_code == 502 and "Access denied" in r.json()["detail"]


def test_old_replies_page_is_gone(client):
    assert client.get("/replies", auth=AUTH).status_code == 404


def test_peer_link_and_label_distinguish_group_chats():
    from web.services import peer_label, peer_link

    assert peer_link(2000000001) == "https://vk.com/im?sel=c1" and peer_label(2000000001) == "беседа 1"
    assert peer_link(77) == "https://vk.com/im?sel=77" and peer_label(77) == "id77"
