from bot.status import ReplyRecord
from web.im.marks import bot_marks
from web.services import model_label


def test_bot_marks_cover_every_part_and_fall_back_to_first_id():
    recs = [ReplyRecord(1, 1, 2, 3, 40, "a", None, 0.1, "rina", model="grok-4.6", reply_message_ids=(40, 41)),
            ReplyRecord(2, 1, 2, 3, 50, "b", None, 0.1, "", model="")]
    marks = bot_marks(recs)
    assert marks[40].persona == "rina" and marks[41].model == model_label("grok-4.6")
    assert marks[50].persona == "по умолчанию" and marks[50].model == ""
