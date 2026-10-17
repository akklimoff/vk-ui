from bot.agent.journal import ActionRecord
from web.im.marks import bot_marks
from web.services import model_label


def record(ids, persona="rina", model="grok-4.6"):
    return ActionRecord(ts=1, peer_id=2000000001, from_id=2, role="trusted", place="chat", message_id=3,
                        request="просьба", calls=(), outcome="replied", reply="ответ", reply_message_ids=ids, steps=1,
                        duration_s=0.1, model=model, prompt_tokens=1, completion_tokens=1, persona=persona)


def test_bot_marks_cover_every_part_of_an_agent_reply():
    marks = bot_marks([record((40, 41)), record((50,), persona="", model=""), record(())])
    assert marks[40].persona == "rina" and marks[41].model == model_label("grok-4.6")
    assert marks[50].persona == "по умолчанию" and marks[50].model == ""
    assert set(marks) == {40, 41, 50}


def test_marks_file_parses_the_journal_only_when_it_changes(tmp_path, monkeypatch):
    import json
    from dataclasses import asdict

    from web.im import marks as marks_module
    from web.im.marks import MarksFile

    path = tmp_path / "actions.jsonl"
    path.write_text(json.dumps(asdict(record((40,)))) + "\n")
    reads = []
    real = marks_module.ActionLog.read
    monkeypatch.setattr(marks_module.ActionLog, "read", lambda self: reads.append(1) or real(self))
    cache = MarksFile(str(path))
    assert set(cache.current()) == {40} and set(cache.current()) == {40}
    assert len(reads) == 1
    with path.open("a") as f:
        f.write(json.dumps(asdict(record((41,)))) + "\n")
    assert set(cache.current()) == {40, 41} and len(reads) == 2
    assert MarksFile(str(tmp_path / "нет.jsonl")).current() == {}
