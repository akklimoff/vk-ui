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
