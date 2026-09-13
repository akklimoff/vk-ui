from bot.status import ReplyRecord
from web.im.views import BotMark
from web.services import model_label


def bot_marks(records: list[ReplyRecord]) -> dict[int, BotMark]:
    marks = {}
    for r in records:
        mark = BotMark(r.persona or "по умолчанию", model_label(r.model) if r.model else "")
        for mid in tuple(r.reply_message_ids) or (r.reply_message_id,):
            marks[int(mid)] = mark
    return marks
