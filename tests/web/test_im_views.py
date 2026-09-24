from datetime import datetime
from zoneinfo import ZoneInfo

from tests.web.im_fixtures import HISTORY, CONVERSATIONS, ME, PEER_CHAT, PEER_USER
from web.im.views import (BotMark, Message, Peer, attachment_of, day_label, parse_conversations,
                          parse_history, presence, preview, rows, wave_bars)

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


def test_attachment_of_keeps_voice_waveform():
    att = attachment_of(HISTORY["items"][2]["attachments"][0])
    assert att.waveform == (1, 5, 9)
    assert attachment_of({"type": "audio_message", "audio_message": {"duration": 3}}).waveform == ()


def test_wave_bars_follow_vk_sizing():
    assert wave_bars((), 1) == (2,) * 22                      # секунда — 22 столбика, пустая волна — плоская
    assert len(wave_bars((31,) * 128, 60)) == 80             # не длиннее 80
    assert wave_bars((31,), 1) == (12,) * 22                  # максимум 12px
    bars = wave_bars((1, 5, 9), 20)
    assert len(bars) == 60 and bars[:20] == (2,) * 20 and bars[-20:] == (3,) * 20


def test_peer_of_reads_last_seen_and_sex_for_users():
    chat, user = parse_conversations(CONVERSATIONS, ME)
    assert user.peer.last_seen == 1783059300 and user.peer.sex == 1
    assert chat.peer.last_seen == 0 and chat.peer.sex == 0


def test_presence():
    now = datetime(2026, 9, 8, 18, 0, tzinfo=TZ).timestamp()
    assert presence(Peer(1, "x", online=True), now, TZ) == "онлайн"
    assert presence(Peer(1, "x"), now, TZ) == ""
    assert presence(Peer(1, "x", sex=1, last_seen=now - 30), now, TZ) == "была в сети только что"
    assert presence(Peer(1, "x", sex=1, last_seen=now - 300), now, TZ) == "была в сети 5 мин назад"
    assert presence(Peer(1, "x", sex=2, last_seen=now - 7200), now, TZ) == "был в сети сегодня в 16:00"
    assert presence(Peer(1, "x", sex=2, last_seen=now - 86400), now, TZ) == "был в сети вчера в 18:00"
    july = datetime(2026, 7, 3, 9, 15, tzinfo=TZ).timestamp()
    assert presence(Peer(1, "x", last_seen=july), now, TZ) == "был(а) в сети 3 июля в 09:15"


def test_rows_mark_first_unread_incoming_message():
    messages, _ = parse_history(HISTORY, ME)
    now = datetime(2026, 9, 8, 18, 0, tzinfo=TZ).timestamp()
    assert [r.unread for r in rows(messages, now, TZ, in_read=500)] == [False, False, False, True]
    assert not any(r.unread for r in rows(messages, now, TZ))
    assert not any(r.unread for r in rows(messages, now, TZ, in_read=502))
