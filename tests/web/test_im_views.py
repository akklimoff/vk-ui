from datetime import datetime
from zoneinfo import ZoneInfo

from tests.web.im_fixtures import HISTORY, CONVERSATIONS, ME, PEER_CHAT, PEER_USER
from web.im.views import (Attachment, BotMark, Message, Peer, Profiles, attachment_of, day_label, parse_conversations,
                          parse_history, parse_media, parse_search, presence, preview, rows, wave_bars)

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
        {"type": "s", "url": "https://s", "width": 75}, {"type": "x", "url": "https://x", "width": 604},
        {"type": "w", "url": "https://w", "width": 2560}]}})
    assert att.kind == "photo" and att.url == "https://w" and att.preview == "https://x"


def test_attachment_of_unknown_type_is_labelled():
    other = attachment_of({"type": "widget", "widget": {}})
    assert other.kind == "other" and other.title == "Вложение"
    assert attachment_of({"type": "event", "event": {}}).title == "Мероприятие"


def test_photo_keeps_preview_size_and_fits_a_box():
    att = attachment_of({"type": "photo", "photo": {"sizes": [
        {"url": "https://x", "width": 604, "height": 1208}, {"url": "https://w", "width": 1280, "height": 2560}]}})
    assert (att.width, att.height) == (604, 1208) and att.fit(320) == (160, 320)
    assert Attachment("photo").fit(320) == (320, 320)


def test_wall_attachment_is_a_post_with_author_and_original():
    profiles = Profiles({"profiles": [{"id": 22, "first_name": "Аня", "last_name": "Иванова", "photo_50": "u22"}]})
    att = attachment_of({"type": "wall", "wall": {
        "id": 5, "from_id": 22, "to_id": 22, "date": 100, "text": "моя подпись", "attachments": [],
        "copy_history": [{"id": 9, "owner_id": -3, "from_id": -3, "date": 50, "text": "оригинал",
                          "attachments": [{"type": "photo", "photo": {"sizes": [{"url": "https://p", "width": 800}]}}]}]}},
        profiles)
    post = att.post
    assert att.kind == "wall" and post.author == "Аня Иванова" and post.photo == "u22"
    assert post.text == "моя подпись" and post.href == "https://vk.com/wall22_5"
    assert post.original.text == "оригинал" and post.original.href == "https://vk.com/wall-3_9"
    assert post.original.author == "club3"
    assert post.original.attachments[0].kind == "photo"


def test_wall_author_comes_from_the_from_field_first():
    att = attachment_of({"type": "wall", "wall": {"id": 1, "from_id": -7, "date": 1, "text": "",
                                                  "from": {"id": 7, "name": "Паблик", "photo_50": "g7"}}})
    assert att.post.author == "Паблик" and att.post.photo == "g7" and att.post.href == "https://vk.com/wall-7_1"


def test_forwarded_messages_are_parsed_recursively():
    raw = {**HISTORY, "items": [{"id": 700, "date": 10, "from_id": 11, "text": "", "attachments": [],
                                 "fwd_messages": [{"from_id": 22, "date": 5, "text": "раз",
                                                   "fwd_messages": [{"from_id": 11, "date": 1, "text": "два"}]},
                                                  {"from_id": 11, "date": 6, "text": "три"}]}]}
    (message,), _ = parse_history(raw, ME)
    first, second = message.forwards
    assert first.author == "Аня Иванова" and first.text == "раз" and first.forwards[0].text == "два"
    assert second.author == "Вася Пупкин" and preview(message) == "2 пересланных сообщения"


def test_other_vk_attachments_get_their_own_kind():
    story = attachment_of({"type": "story", "story": {"id": 3, "owner_id": 22, "type": "photo",
                                                      "photo": {"sizes": [{"url": "s", "width": 720}]}}})
    assert story.kind == "story" and story.preview == "s" and story.href == "https://vk.com/story22_3"
    gone = attachment_of({"type": "story", "story": {"id": 3, "owner_id": 22, "is_expired": True}})
    assert gone.title == "История недоступна" and not gone.preview
    assert attachment_of({"type": "gift", "gift": {"thumb_256": "https://cdn.example/g.png"}}).url == "https://cdn.example/g.png"
    poll = attachment_of({"type": "poll", "poll": {"question": "Куда?", "votes": 3, "answers": [
        {"text": "кино", "rate": 66.7}, {"text": "бар", "rate": 33.3}]}})
    assert poll.title == "Куда?" and poll.lines == ("кино — 67%", "бар — 33%") and poll.subtitle == "Опрос · 3 голоса"
    call = attachment_of({"type": "call", "call": {"state": "reached", "duration": 75, "video": True}})
    assert call.title == "Видеозвонок" and call.subtitle == "1:15"
    assert attachment_of({"type": "call", "call": {"state": "canceled_by_receiver"}}).subtitle == "Отклонён"
    video = attachment_of({"type": "video", "video": {"id": 4, "owner_id": -1, "duration": 61, "title": "клип",
                                                      "image": [{"url": "v1", "width": 130}, {"url": "v2", "width": 320}]}})
    assert video.preview == "v2" and video.href == "https://vk.com/video-1_4" and video.duration == 61
    doc = attachment_of({"type": "doc", "doc": {"title": "отчёт.pdf", "ext": "pdf", "size": 2_500_000,
                                                "url": "https://vk.com/doc1_2"}})
    assert doc.href == "https://vk.com/doc1_2" and doc.subtitle == "PDF · 2.4 МБ"
    link = attachment_of({"type": "link", "link": {"url": "https://example.com/a", "title": "Статья"}})
    assert link.subtitle == "example.com" and link.href == "https://example.com/a"


def test_preview_counts_photos_and_names_new_kinds():
    photo = attachment_of({"type": "photo", "photo": {"sizes": [{"url": "https://p", "width": 100}]}})
    assert preview(Message(1, 0, 11, "Вася", "", "", False, False, attachments=(photo, photo, photo))) == "3 фотографии"
    gift = attachment_of({"type": "gift", "gift": {}})
    assert preview(Message(1, 0, 11, "Вася", "", "", False, False, attachments=(gift,))) == "Подарок"


def test_parse_media_takes_tiles_and_cursor():
    raw = {"items": [{"attachment": {"type": "photo", "photo": {"sizes": [
        {"url": "https://t", "width": 320}, {"url": "https://f", "width": 1280}]}}},
        {"attachment": {"type": "video", "video": {}}}], "next_from": "n"}
    photos, cursor = parse_media(raw, "photo")
    assert [(p.url, p.preview) for p in photos] == [("https://f", "https://t")] and cursor == "n"
    assert parse_media({"items": [], "next_from": "n"}, "photo") == ([], "")
    videos, _ = parse_media(raw, "video")
    assert [v.kind for v in videos] == ["video"]


def test_search_results_become_dialogs_without_a_last_message():
    raw = {"count": 1, "items": [CONVERSATIONS["items"][1]["conversation"]], "profiles": CONVERSATIONS["profiles"]}
    (found,) = parse_search(raw, ME)
    assert found.peer.title == "Аня Иванова" and found.last is None


def test_avatars_prefer_the_sharper_photo_100():
    profiles = Profiles({"profiles": [{"id": 1, "photo_50": "small", "photo_100": "big"}, {"id": 2, "photo_50": "only"}]})
    assert profiles.photo(1) == "big" and profiles.photo(2) == "only"


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


def test_only_web_addresses_become_links():
    doc = {"type": "doc", "doc": {"url": "javascript:alert(1)", "title": "файл"}}
    link = {"type": "link", "link": {"url": "https://example.org/a", "title": "сайт"}}
    assert attachment_of(doc).url == "" and attachment_of(doc).title == "файл"
    assert attachment_of(link).url == "https://example.org/a"


def test_odd_vk_fields_do_not_break_parsing():
    assert attachment_of({"type": "link", "link": {"url": "https://[oops/x"}}).subtitle == ""
    assert attachment_of({"type": "poll", "poll": {"votes": None, "answers": [{"text": "да", "rate": None}]}}).lines == ("да — 0%",)
    assert attachment_of({"type": "photo", "photo": {"sizes": [{"url": "https://a", "width": None}]}}).url == "https://a"
    assert attachment_of({"type": "photo", "photo": {"sizes": [{"url": "javascript:alert(1)", "width": 9}]}}).url == ""
    assert attachment_of({"type": "video", "video": {"image": [{"url": "u", "width": "wide"}]}}) == Attachment("other", title="Вложение")
    assert attachment_of({"type": "wall_reply", "wall_reply": {"owner_id": 1, "post_id": 2}}).href == "https://vk.com/wall1_2"
