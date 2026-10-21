import json

from bot.agent.journal import PARAM_LIMIT, ActionLog, ActionRecord, call_entry
from bot.agent.loop import ALLOWED, REFUSED, CallRecord


def record(ts=1.0, **kw):
    fields = dict(ts=ts, peer_id=2_000_000_001, from_id=7, role="trusted", place="chat", message_id=5,
                  request="дай ссылку", calls=(), outcome="replied", reply="держи", reply_message_ids=(101,),
                  steps=2, duration_s=3.5, model="grok-4.6", prompt_tokens=900, completion_tokens=40, persona="rina")
    return ActionRecord(**{**fields, **kw})


def test_call_entry_keeps_the_verdict_and_never_a_result():
    entry = call_entry(CallRecord("messages.pin", {"peer_id": 1, "conversation_message_id": 9}, ALLOWED, ok=True))
    assert entry == {"method": "messages.pin", "params": {"peer_id": 1, "conversation_message_id": 9},
                     "verdict": "allowed", "reason": "", "ok": True, "error_code": None}
    refused = call_entry(CallRecord("wall.post", {"message": "пост"}, REFUSED, "этому человеку так нельзя"))
    assert (refused["verdict"], refused["reason"], refused["ok"]) == ("refused", "этому человеку так нельзя", None)


def test_params_lose_the_token_and_long_values():
    call = CallRecord("messages.send", {"message": "я" * 2000, "note": "ключ vk1.secret", "count": 5,
                                        "ids": list(range(1000)), "nested": {"token": "vk1.secret"}}, ALLOWED)
    params = call_entry(call, ["vk1.secret"])["params"]
    assert len(params["message"]) == PARAM_LIMIT + 1 and params["message"].endswith("…")
    assert params["note"] == "ключ [скрыто]" and params["count"] == 5
    assert len(params["ids"]) == PARAM_LIMIT + 1
    assert "vk1.secret" not in json.dumps(params, ensure_ascii=False)


def test_record_with_unicode_line_separators_survives_later_appends(tmp_path):
    log = ActionLog(str(tmp_path / "actions.jsonl"))
    odd = record(ts=1.0, request="первая\u2028вторая", reply="раз\u2029два\u0085три")
    log.append(odd)
    log.append(record(ts=2.0))
    assert log.read() == [record(ts=2.0), odd]


def test_records_come_back_newest_first(tmp_path):
    log = ActionLog(str(tmp_path / "state" / "actions.jsonl"))
    call = call_entry(CallRecord("users.get", {"user_ids": "1"}, ALLOWED, ok=True))
    log.append(record(ts=1.0))
    log.append(record(ts=2.0, calls=(call,), outcome="needs_confirmation", reply_message_ids=(102, 103)))
    newest, oldest = log.read()
    assert oldest == record(ts=1.0)
    assert newest.calls == (call,) and newest.reply_message_ids == (102, 103)
    assert newest.outcome == "needs_confirmation"


def test_only_the_last_records_are_kept(tmp_path):
    log = ActionLog(str(tmp_path / "actions.jsonl"), keep=3)
    for ts in range(5):
        log.append(record(ts=float(ts)))
    assert [r.ts for r in log.read()] == [4.0, 3.0, 2.0]


def test_missing_file_and_broken_lines_are_skipped(tmp_path):
    path = tmp_path / "actions.jsonl"
    assert ActionLog(str(path)).read() == []
    log = ActionLog(str(path))
    log.append(record())
    with open(path, "a", encoding="utf-8") as f:
        f.write("не json\n{\"ts\": 1}\n")
    assert log.read() == [record()]
