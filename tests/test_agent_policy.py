import pytest

from bot.agent.gate import CHAT, OWNER, SAVED, TRUSTED, Caller
from bot.agent.methods import (DESTRUCTIVE, METHODS, OUTWARD, READ, UNLISTED, WRITE_HERE, denied, find_method,
                               reads_by_name)
from bot.agent.policy import Allow, Confirm, Refuse, judge
from common.commands import looks_like_command

ME, PEER, OTHER = 42, 2_000_000_001, 2_000_000_002
TRUSTED_IN_CHAT = Caller(CHAT, TRUSTED)
OWNER_IN_CHAT = Caller(CHAT, OWNER)
OWNER_IN_SAVED = Caller(SAVED, OWNER)


def ask(method, params=None, caller=TRUSTED_IN_CHAT, tainted=False, secrets=()):
    return judge(method, params or {}, caller, PEER, ME, tainted, secrets)


def test_read_in_chat_gets_the_current_peer():
    assert ask("messages.getHistory", {"count": 50}) == Allow("messages.getHistory", {"count": 50, "peer_id": PEER}, READ)
    assert ask("messages.getHistory", {"peer_id": str(PEER)}).params == {"peer_id": str(PEER)}
    assert ask("messages.getConversationsById").params == {"peer_ids": PEER}


CHAT_CALLS = [
    ("messages.getHistory", {"count": 5}),
    ("messages.send", {"message": "привет"}),
    ("messages.send", {"peer_id": 555, "message": "привет"}),
    ("wall.post", {"message": "пост"}),
    ("messages.createChat", {"user_ids": "5", "title": "новая"}),
    ("messages.delete", {"cmids": "5", "delete_for_all": 1}),
    ("messages.removeChatUser", {"user_id": 9}),
    ("messages.editChat", {"title": "новое имя"}),
    ("messages.getInviteLink", {"reset": 1}),
    ("wall.delete", {"post_id": 3}),
    ("account.ban", {"owner_id": 9}),
    ("messages.getHistory", {"peer_id": OTHER}),
    ("notes.add", {"text": "x"}),
    ("execute", {"code": "return 1;"}),
    ("auth.restore", {}),
    ("users.get", {"access_token": "x"}),
    ("users.get", {"v": "5.0"}),
]
BOTH_IN_CHAT = pytest.mark.parametrize("caller", [TRUSTED_IN_CHAT, OWNER_IN_CHAT], ids=["доверенный", "владелец"])
CLEAN_OR_TAINTED = pytest.mark.parametrize("tainted", [False, True], ids=["чистый", "запачканный"])


@CLEAN_OR_TAINTED
@pytest.mark.parametrize("method, params", CHAT_CALLS)
def test_trusted_person_in_a_chat_has_exactly_the_rights_of_the_owner(method, params, tainted):
    assert ask(method, dict(params), TRUSTED_IN_CHAT, tainted) == ask(method, dict(params), OWNER_IN_CHAT, tainted)


@BOTH_IN_CHAT
@CLEAN_OR_TAINTED
def test_outward_call_from_a_chat_runs_at_once_even_when_tainted(caller, tainted):
    assert ask("wall.post", {"message": "пост"}, caller, tainted) == Allow("wall.post", {"message": "пост"}, OUTWARD)
    assert ask("messages.send", {"peer_id": 555, "message": "привет"}, caller, tainted) == Allow(
        "messages.send", {"peer_id": 555, "message": "привет"}, OUTWARD)
    assert ask("messages.createChat", {"user_ids": "5", "title": "новая"}, caller, tainted).kind == OUTWARD


@BOTH_IN_CHAT
@CLEAN_OR_TAINTED
@pytest.mark.parametrize("method, params, sent", [
    ("messages.delete", {"cmids": "5", "delete_for_all": 1}, {"cmids": "5", "delete_for_all": 1, "peer_id": PEER}),
    ("messages.removeChatUser", {"user_id": 9}, {"user_id": 9, "chat_id": 1}),
    ("messages.editChat", {"title": "новое имя"}, {"title": "новое имя", "chat_id": 1}),
    ("messages.getInviteLink", {"reset": 1}, {"reset": 1, "peer_id": PEER}),
    ("wall.delete", {"post_id": 3}, {"post_id": 3}),
    ("account.ban", {"owner_id": 9}, {"owner_id": 9}),
])
def test_destructive_call_from_a_chat_runs_at_once(caller, tainted, method, params, sent):
    assert ask(method, params, caller, tainted) == Allow(method, sent, DESTRUCTIVE)


@BOTH_IN_CHAT
@CLEAN_OR_TAINTED
def test_no_call_from_a_chat_ever_waits_for_yes(caller, tainted):
    for row in METHODS:
        for params in ({}, {name: 1 for name in row.escalate}):
            assert not isinstance(ask(row.name, params, caller, tainted), Confirm), row.name


@CLEAN_OR_TAINTED
def test_destructive_in_saved_messages_always_asks(tainted):
    assert ask("messages.delete", {"cmids": "5", "peer_id": PEER}, OWNER_IN_SAVED, tainted) == Confirm(
        "messages.delete", {"cmids": "5", "peer_id": PEER}, DESTRUCTIVE, "Удалить сообщения")
    for method, params in (("messages.removeChatUser", {"chat_id": 1, "user_id": 9}), ("wall.delete", {"post_id": 3}),
                           ("account.ban", {"owner_id": 9})):
        verdict = ask(method, params, OWNER_IN_SAVED, tainted)
        assert isinstance(verdict, Confirm) and verdict.kind == DESTRUCTIVE, method


def test_outward_in_saved_messages_asks_only_when_tainted():
    assert ask("wall.post", {"message": "пост"}, OWNER_IN_SAVED) == Allow("wall.post", {"message": "пост"}, OUTWARD)
    assert ask("wall.post", {"message": "пост"}, OWNER_IN_SAVED, tainted=True) == Confirm(
        "wall.post", {"message": "пост"}, OUTWARD, "Опубликовать пост")


def test_invite_link_reset_is_destructive_and_plain_link_is_a_read():
    assert ask("messages.getInviteLink", {"reset": 0}).kind == READ
    assert ask("messages.getInviteLink", {"reset": "false"}).kind == READ
    assert ask("messages.getInviteLink", {"reset": 1}, OWNER_IN_CHAT).kind == DESTRUCTIVE
    reset = ask("messages.getInviteLink", {"peer_id": PEER, "reset": 1}, OWNER_IN_SAVED)
    assert isinstance(reset, Confirm) and reset.kind == DESTRUCTIVE and reset.title == "Сбросить ссылку-приглашение"


@pytest.mark.parametrize("method", ["execute", "Execute", "execute.getAll", "auth.restore", "secure.sendNotification",
                                    "ads.createAds", "orders.cancelSubscription", "account.changePassword",
                                    "ACCOUNT.REGISTERDEVICE", "messages.deleteConversation", "messages.deleteDialog",
                                    "friends.deleteAllRequests", "messages.getLongPollServer",
                                    "groups.getLongPollServer", "groups.addCallbackServer",
                                    "groups.getCallbackConfirmationCode"])
def test_denied_methods_are_refused_even_for_the_owner_in_saved(method):
    assert denied(method)
    assert isinstance(ask(method, {}, OWNER_IN_SAVED), Refuse)


@pytest.mark.parametrize("method", ["", "messages.send?x=1", "../users.get", "users.get.extra", "users get", None, 5])
def test_garbage_method_names_never_reach_vk(method):
    assert isinstance(ask(method, {}, OWNER_IN_SAVED), Refuse)


@pytest.mark.parametrize("param", ["access_token", "v", "Access_Token", "V", " v ", "ACCESS_TOKEN"])
def test_token_and_version_parameters_are_refused(param):
    assert isinstance(ask("users.get", {param: "x"}, OWNER_IN_SAVED), Refuse)
    assert isinstance(ask("users.get", {param: "x"}), Refuse)


def test_saved_messages_open_the_whole_account_for_reading():
    assert ask("messages.getConversations", {"count": 20}, OWNER_IN_SAVED) == Allow(
        "messages.getConversations", {"count": 20}, READ)
    other = ask("messages.getHistory", {"peer_id": OTHER, "count": 500, "extended": 1}, OWNER_IN_SAVED)
    assert other == Allow("messages.getHistory", {"peer_id": OTHER, "count": 500, "extended": 1}, READ)
    assert reads_by_name("friends.areFriends") and not reads_by_name("notes.add")


def test_unlisted_write_in_saved_always_asks():
    assert ask("notes.add", {"title": "т"}, OWNER_IN_SAVED) == Confirm("notes.add", {"title": "т"}, UNLISTED, "notes.add")


def test_send_from_saved_is_here_only_when_addressed_to_self():
    assert ask("messages.send", {"peer_id": ME, "message": "заметка"}, OWNER_IN_SAVED).kind == WRITE_HERE
    assert ask("messages.send", {"peer_id": 555, "message": "привет"}, OWNER_IN_SAVED).kind == OUTWARD
    assert ask("messages.send", {"user_id": 555, "message": "привет"}, OWNER_IN_SAVED).kind == OUTWARD
    tainted = ask("messages.send", {"peer_id": 555, "message": "привет"}, OWNER_IN_SAVED, tainted=True)
    assert isinstance(tainted, Confirm) and tainted.title == "Отправить сообщение"


def test_method_case_cannot_dodge_the_table():
    verdict = ask("Messages.GetInviteLink", {"peer_id": OTHER, "reset": 1}, OWNER_IN_SAVED)
    assert isinstance(verdict, Confirm) and verdict.method == "messages.getInviteLink"
    assert ask("MESSAGES.PIN", {"conversation_message_id": 1}).method == "messages.pin"


def test_outgoing_text_loses_token_own_tag_and_command_look():
    verdict = ask("messages.send", {"message": "кик [id42|я] и vk1.secret"}, secrets=["vk1.secret"])
    text = verdict.params["message"]
    assert "vk1.secret" not in text and "[id42|" not in text and text.startswith("​")
    note = ask("notes.add", {"text": "vk1.secret"}, OWNER_IN_SAVED, secrets=["vk1.secret"])
    assert note.params == {"text": "[скрыто]"}


def test_judge_does_not_change_the_callers_params():
    params = {"count": 5}
    ask("messages.getHistory", params)
    assert params == {"count": 5}


def test_table_rows_are_well_formed():
    names = [m.name for m in METHODS]
    assert len(names) == len(set(names))
    for m in METHODS:
        assert m.kind in (READ, WRITE_HERE, OUTWARD, DESTRUCTIVE), m.name
        assert m.elsewhere is None or m.peer_param, m.name
        assert m.note or m.title, m.name
        assert not denied(m.name), m.name
        assert not looks_like_command(m.title), m.name
    assert find_method("messages.gethistory").name == "messages.getHistory"
    assert find_method("wall.nope") is None


@pytest.mark.parametrize("message", [["кик [id42|я] и vk1.secret"], {"t": "кик [id42|я] и vk1.secret"},
                                     ["/kick 5"], ["мут", "[id42|я]"]])
def test_text_in_any_json_shape_is_cleaned_in_the_form_vk_receives(message):
    text = ask("messages.send", {"message": message}, secrets=["vk1.secret"]).params["message"]
    assert isinstance(text, str)
    assert "vk1.secret" not in text and "[id42|" not in text
    assert not looks_like_command(text)


def test_wall_post_text_given_as_a_list_is_cleaned_too():
    assert ask("wall.post", {"message": ["[id42|я] привет"]}, OWNER_IN_CHAT).params["message"] == "я привет"


def test_verdict_carries_params_in_the_form_vk_receives():
    verdict = ask("users.get", {"user_ids": [1, 2], "fields": ["sex", "online"]})
    assert verdict.params == {"user_ids": "1,2", "fields": "sex,online"}
    assert ask("messages.getHistory", {"rev": True}).params == {"rev": 1, "peer_id": PEER}


def test_poll_may_be_created_for_a_community():
    assert ask("polls.create", {"question": "когда?"}).params == {"question": "когда?"}
    assert ask("polls.create", {"question": "когда?", "owner_id": -5}).params["owner_id"] == -5


def test_poll_answers_given_as_a_list_reach_vk_as_a_json_array():
    verdict = ask("polls.create", {"question": "куда?", "add_answers": ["Кино", "Бар, потом кино"]})
    assert verdict.params["add_answers"] == '["Кино", "Бар, потом кино"]'
    ready = ask("polls.create", {"question": "куда?", "add_answers": '["а","б"]'})
    assert ready.params["add_answers"] == '["а","б"]'


@pytest.mark.parametrize("off", [0, "0", "false", False, [0], ""])
def test_flag_judged_as_off_is_not_sent_at_all(off):
    assert ask("messages.getInviteLink", {"reset": off}) == Allow("messages.getInviteLink", {"peer_id": PEER}, READ)


def test_flag_wrapped_in_a_list_still_escalates():
    assert ask("messages.getInviteLink", {"reset": [1]}, OWNER_IN_CHAT).kind == DESTRUCTIVE


@pytest.mark.parametrize("method, params", [
    ("messages.pin", {"peer_id": OTHER, "conversation_message_id": 1}),
    ("messages.unpin", {"peer_id": OTHER}),
    ("messages.sendReaction", {"peer_id": OTHER, "cmid": 1, "reaction_id": 1}),
    ("messages.pin", {"conversation_message_id": 1}),
])
def test_write_from_saved_into_another_chat_is_outward(method, params):
    assert ask(method, params, OWNER_IN_SAVED).kind == OUTWARD
    asked = ask(method, params, OWNER_IN_SAVED, tainted=True)
    assert isinstance(asked, Confirm) and not asked.title.startswith("messages.")
    assert not looks_like_command(asked.title)


def test_write_into_saved_messages_themselves_stays_here():
    assert ask("messages.pin", {"peer_id": ME, "conversation_message_id": 1}, OWNER_IN_SAVED, tainted=True) == Allow(
        "messages.pin", {"peer_id": ME, "conversation_message_id": 1}, WRITE_HERE)


@pytest.mark.parametrize("extra", ["user_id", "user_ids", "chat_id", "domain", "peer_ids"])
def test_second_addressee_makes_a_send_from_saved_outward(extra):
    verdict = ask("messages.send", {"peer_id": ME, extra: 555, "message": "привет"}, OWNER_IN_SAVED, tainted=True)
    assert isinstance(verdict, Confirm) and verdict.kind == OUTWARD


def test_chat_number_is_filled_in_for_methods_addressed_by_chat_id():
    assert ask("messages.editChat", {"title": "Новое"}, OWNER_IN_CHAT) == Allow(
        "messages.editChat", {"title": "Новое", "chat_id": 1}, DESTRUCTIVE)
    assert ask("messages.removeChatUser", {"member_id": 5, "chat_id": "1"}, OWNER_IN_CHAT).params == {
        "member_id": 5, "chat_id": "1"}
    assert ask("messages.addChatUser", {"user_id": 5}, OWNER_IN_CHAT) == Allow(
        "messages.addChatUser", {"user_id": 5, "chat_id": 1}, OUTWARD)


def test_messages_are_deleted_from_a_chat_by_their_numbers_in_it():
    assert ask("messages.delete", {"cmids": [7, 8], "delete_for_all": 1}, OWNER_IN_CHAT) == Allow(
        "messages.delete", {"cmids": "7,8", "delete_for_all": 1, "peer_id": PEER}, DESTRUCTIVE)


def test_saved_messages_keep_free_addressing_for_chat_methods():
    assert ask("messages.editChat", {"chat_id": 9, "title": "x"}, OWNER_IN_SAVED) == Confirm(
        "messages.editChat", {"chat_id": 9, "title": "x"}, DESTRUCTIVE, "Переименовать беседу")
    assert isinstance(ask("messages.delete", {"message_ids": "100"}, OWNER_IN_SAVED), Confirm)


@BOTH_IN_CHAT
@CLEAN_OR_TAINTED
@pytest.mark.parametrize("method, params, kind", [
    ("friends.get", {}, READ), ("users.search", {"q": "Анжелика Вершинина"}, READ),
    ("users.get", {"user_ids": "1", "fields": "bdate,status,about,contacts"}, READ),
    ("messages.getDialogs", {}, READ), ("photos.getAll", {"owner_id": 9}, READ),
    ("likes.add", {"type": "photo", "owner_id": 9, "item_id": 3}, OUTWARD),
    ("account.saveProfileInfo", {"status": "сплю"}, OUTWARD), ("friends.delete", {"user_id": 9}, DESTRUCTIVE),
    ("notes.add", {"text": "x"}, UNLISTED), ("stories.delete", {"story_id": 1}, UNLISTED),
])
def test_the_whole_page_is_open_from_a_chat(caller, tainted, method, params, kind):
    assert ask(method, params, caller, tainted) == Allow(method, params, kind)


@BOTH_IN_CHAT
@pytest.mark.parametrize("method, params, kind", [
    ("messages.getHistory", {"peer_id": OTHER, "count": 200}, READ),
    ("messages.getHistory", {"peer_id": 555}, READ), ("messages.getHistory", {"peer_id": ME}, READ),
    ("messages.search", {"q": "пароль", "peer_id": OTHER}, READ),
    ("messages.getConversationMembers", {"peer_id": OTHER}, READ),
    ("messages.getConversationsById", {"peer_ids": f"{PEER},{OTHER}"}, READ),
    ("messages.pin", {"peer_id": OTHER, "conversation_message_id": 1}, OUTWARD),
    ("messages.send", {"peer_id": OTHER, "message": "x", "attachment": "photo1_2"}, OUTWARD),
    ("messages.delete", {"cmids": "7", "peer_id": OTHER}, DESTRUCTIVE),
    ("messages.editChat", {"title": "x", "chat_id": 2}, DESTRUCTIVE),
    ("messages.removeChatUser", {"member_id": 5, "chat_id": 2}, DESTRUCTIVE),
    ("messages.addChatUser", {"user_id": 5, "chat_id": 2}, OUTWARD),
])
def test_another_conversation_named_in_a_call_from_a_chat_is_left_as_named(caller, method, params, kind):
    assert ask(method, params, caller) == Allow(method, params, kind)


@pytest.mark.parametrize("address", ["user_id", "domain", "chat_id", "peer_ids", "user_ids"])
def test_a_send_addressed_otherwise_does_not_also_get_this_chat(address):
    verdict = ask("messages.send", {address: 555, "message": "привет"})
    assert verdict == Allow("messages.send", {address: 555, "message": "привет"}, OUTWARD)


def test_send_without_an_address_goes_to_this_chat_with_any_attachment():
    assert ask("messages.send", {"message": "фото", "attachment": "photo1_2"}) == Allow(
        "messages.send", {"message": "фото", "attachment": "photo1_2", "peer_id": PEER}, WRITE_HERE)
    assert ask("messages.pin", {"conversation_message_id": 9}) == Allow(
        "messages.pin", {"conversation_message_id": 9, "peer_id": PEER}, WRITE_HERE)


@BOTH_IN_CHAT
@pytest.mark.parametrize("method, params", [
    ("execute", {"code": "return 1;"}), ("auth.restore", {}), ("account.changePassword", {}),
    ("messages.deleteConversation", {}), ("messages.getLongPollServer", {}),
    ("users.get", {"access_token": "x"}), ("users.get", {"v": "5.0"}),
])
def test_what_is_denied_stays_denied_in_a_chat(caller, method, params):
    assert isinstance(ask(method, params, caller), Refuse)


def test_listed_writes_in_saved_ask_only_when_tainted_and_removals_always():
    assert isinstance(ask("likes.add", {"type": "post", "owner_id": 1, "item_id": 2}, OWNER_IN_SAVED), Allow)
    assert isinstance(ask("likes.add", {"type": "post", "owner_id": 1, "item_id": 2}, OWNER_IN_SAVED, True), Confirm)
    assert isinstance(ask("friends.delete", {"user_id": 9}, OWNER_IN_SAVED), Confirm)


PICTURE = "https://sun9-15.vkuserphoto.ru/x.jpg?sign=abc"


@BOTH_IN_CHAT
def test_a_picture_from_vk_storage_may_become_the_avatar_or_the_chat_photo(caller):
    assert ask("photos.saveOwnerPhoto", {"from_url": PICTURE}, caller) == Allow(
        "photos.saveOwnerPhoto", {"from_url": PICTURE}, OUTWARD)
    assert ask("messages.setChatPhoto", {"from_url": PICTURE}, caller) == Allow(
        "messages.setChatPhoto", {"from_url": PICTURE, "chat_id": 1}, OUTWARD)
    assert ask("photos.saveWallPhoto", {"from_url": PICTURE}, caller).kind == WRITE_HERE


@pytest.mark.parametrize("caller", [TRUSTED_IN_CHAT, OWNER_IN_CHAT, OWNER_IN_SAVED])
@pytest.mark.parametrize("url", ["http://ai:8090/v1/models", "https://evil.example/x.jpg", "file:///app/.env",
                                 "https://169.254.169.254/", ["https://sun9-15.vkuserphoto.ru/x.jpg"], 5, ""])
@pytest.mark.parametrize("method", ["photos.saveOwnerPhoto", "photos.saveMessagesPhoto", "docs.save", "users.get"])
def test_no_call_may_point_the_bot_at_an_address_outside_vk_storage(caller, url, method):
    assert isinstance(ask(method, {"from_url": url}, caller), Refuse)
