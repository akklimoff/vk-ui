from bot.agent.journal import ActionRecord
from web.im.views import BotMark
from web.services import model_label


def bot_marks(records: list[ActionRecord]) -> dict[int, BotMark]:
    marks = {}
    for record in records:
        mark = BotMark(record.persona or "по умолчанию", model_label(record.model) if record.model else "")
        for message_id in record.reply_message_ids:
            marks[int(message_id)] = mark
    return marks
