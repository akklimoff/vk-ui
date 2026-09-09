from datetime import datetime
from zoneinfo import ZoneInfo

from tests.web.im_fixtures import HISTORY, CONVERSATIONS, ME, PEER_CHAT, PEER_USER
from web.im.views import (BotMark, Message, attachment_of, day_label, parse_conversations,
                          parse_history, preview, rows)

TZ = ZoneInfo("Europe/Moscow")


def test_parse_conversations_builds_dialogs_in_order():
    chat, user = parse_conversations(CONVERSATIONS, ME)
    assert chat.peer.id == PEER_CHAT and chat.peer.kind == "chat" and chat.peer.title == "лампочки"
    assert chat.peer.members == 23 and chat.peer.photo == "https://cdn.example/chat50.jpg"
    assert chat.unread == 2 and chat.muted and chat.pinned
    assert chat.last.author == "Вася Пупкин" and preview(chat.last) == "Стикер"
    assert user.peer.kind == "user" and user.peer.title == "Аня Иванова" and not user.peer.online
    assert user.unread == 0 and not user.muted and not user.pinned
    assert user.last.out and not user.last.read          # out_read=299 < id 300


def test_parse_history_is_chronological_with_read_marks_and_attachments():
    messages, out_read = parse_history(HISTORY, ME)
    assert out_read == 501
    assert [m.id for m in messages] == [499, 500, 501, 502]
    voice = messages[1]
    assert voice.attachments[0].kind == "voice" and voice.attachments[0].duration == 20
    assert voice.attachments[0].transcript == "после смены выкину"
    assert voice.attachments[0].url == "https://cdn.example/v.mp3"
    assert voice.reply.author == "Валентина Тина" and voice.reply.text == "выкидывай тогда"
    own = messages[2]
    assert own.out and own.read
    assert messages[0].action == "Вася Пупкин пригласил(а) Аня Иванова"
    assert messages[3].attachments[0].kind == "sticker"
    assert messages[3].attachments[0].url == "https://cdn.example/st256.png"


def test_bot_marks_attach_to_own_messages():
    messages, _ = parse_history(HISTORY, ME, marks={501: BotMark("rina", "grok-4.6")})
    assert messages[2].bot == BotMark("rina", "grok-4.6") and messages[1].bot is None


def test_attachment_of_picks_largest_photo_and_medium_preview():
    att = attachment_of({"type": "photo", "photo": {"sizes": [
        {"type": "s", "url": "s", "width": 75}, {"type": "x", "url": "x", "width": 604},
        {"type": "w", "url": "w", "width": 2560}]}})
    assert att.kind == "photo" and att.url == "w" and att.preview == "x"


def test_attachment_of_unknown_type_is_labelled():
    assert attachment_of({"type": "market", "market": {}}).kind == "other"
    assert attachment_of({"type": "wall", "wall": {}}).title == "репост"


def test_preview_prefers_text_then_attachment_label():
    msg = Message(1, 0, 11, "Вася", "", "привет", False, False)
    assert preview(msg) == "привет"
    voice = Message(1, 0, 11, "Вася", "", "", False, False,
                    attachments=(attachment_of(HISTORY["items"][2]["attachments"][0]),))
    assert preview(voice) == "Голосовое сообщение"


def test_day_label():
    now = datetime(2026, 9, 8, 18, 0, tzinfo=TZ).timestamp()
    assert day_label(now - 3600, now, TZ) == "сегодня"
    assert day_label(now - 86400, now, TZ) == "вчера"
    assert day_label(datetime(2026, 9, 1, 12, tzinfo=TZ).timestamp(), now, TZ) == "1 сентября"
    assert day_label(datetime(2025, 9, 1, 12, tzinfo=TZ).timestamp(), now, TZ) == "1 сентября 2025"


def test_rows_group_series_and_insert_day_chips():
    messages, _ = parse_history(HISTORY, ME)
    now = datetime(2026, 9, 8, 18, 0, tzinfo=TZ).timestamp()
    got = rows(messages, now, TZ)
    assert got[0].day == "вчера" and got[0].head
    assert got[1].day == "сегодня" and got[1].head          # новый день — заголовок серии
    assert got[2].head                                       # другой автор
    assert got[3].head                                       # снова Вася после Вали
