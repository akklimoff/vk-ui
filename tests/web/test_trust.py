import json
import threading

import pytest

from web import trust
from web.services import BrokenConfig, save_runtime_patch, update_config
from web.trust import TrustError, TrustLists

CHAT, OTHER_CHAT = 2000000001, 2000000002


def no_nicks(names):
    return frozenset()


def write(path, data):
    with open(path, "w", encoding="utf-8") as f:
        f.write(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False))


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_lists_are_read_from_the_three_agent_keys():
    lists = trust.read_lists({"agent_users": [5, "@Masha", "id7", "5"], "agent_peers": [CHAT, str(OTHER_CHAT)],
                              "peer_prompts": {str(CHAT): ["свои", "люди"], str(OTHER_CHAT): "  "},
                              "blocked_users": "мусор старого пути"})
    assert lists == TrustLists((5, "@masha", 7), (CHAT, OTHER_CHAT), {CHAT: "свои\nлюди"})
    assert trust.read_lists({}) == TrustLists()


@pytest.mark.parametrize("stored,key", [
    ({"agent_users": "5"}, "agent_users"),
    ({"agent_users": [5, None]}, "agent_users"),
    ({"agent_users": [True]}, "agent_users"),
    ({"agent_users": ["два ника"]}, "agent_users"),
    ({"agent_users": ["-5"]}, "agent_users"),
    ({"agent_peers": {"2000000001": 1}}, "agent_peers"),
    ({"agent_peers": ["свои"]}, "agent_peers"),
    ({"agent_peers": [22]}, "agent_peers"),
    ({"agent_peers": ["²"]}, "agent_peers"),
    pytest.param({"agent_peers": ["9" * 5000]}, "agent_peers", id="too-long-for-int"),
    ({"peer_prompts": ["заметка"]}, "peer_prompts"),
    ({"peer_prompts": "заметка"}, "peer_prompts"),
    ({"peer_prompts": {"2000000001": {"text": "заметка"}}}, "peer_prompts"),
    ({"peer_prompts": {"2000000001": 5}}, "peer_prompts"),
])
def test_foreign_shape_is_an_error_that_names_the_key(stored, key):
    with pytest.raises(TrustError, match=key):
        trust.read_lists(stored)


FOREIGN_NOTES = {"697243383": "заметка старого мессенджера о личном диалоге", "²": ["не", "строка"], "свои": {"x": 1},
                 "0": 5}


def test_note_keys_that_are_not_chats_are_carried_and_never_become_chats():
    lists = trust.read_lists({"agent_peers": [CHAT], "peer_prompts": {**FOREIGN_NOTES, str(CHAT): "свои"}})
    assert lists.peers == (CHAT,) and lists.notes == {CHAT: "свои"}
    assert lists.other_notes == FOREIGN_NOTES


def test_saving_keeps_foreign_note_keys_value_for_value(tmp_path):
    path = str(tmp_path / "access.json")
    write(path, {"agent_users": [5], "agent_peers": [CHAT], "peer_prompts": {**FOREIGN_NOTES, str(CHAT): "свои"}})
    after = trust.save(path, lambda lists: trust.set_note(trust.untrust_peer(lists, CHAT), OTHER_CHAT, "новые"))
    assert after.peers == () and after.notes == {CHAT: "свои", OTHER_CHAT: "новые"}
    assert json.loads(read_text(path))["peer_prompts"] == {**FOREIGN_NOTES, str(CHAT): "свои", str(OTHER_CHAT): "новые"}
    trust.save(path, lambda lists: trust.set_note(trust.set_note(lists, CHAT, ""), OTHER_CHAT, ""))
    assert json.loads(read_text(path))["peer_prompts"] == FOREIGN_NOTES


def test_foreign_note_keys_are_not_shown_as_chats():
    lists = trust.read_lists({"peer_prompts": FOREIGN_NOTES})
    assert trust.trust_view(lists, lambda: None).peers == ()


def test_changes_are_pure_and_idempotent():
    lists = TrustLists((5, "@masha"), (CHAT,), {CHAT: "свои"})
    assert trust.trust_user(lists, 5) == lists
    assert trust.trust_user(lists, 9).users == (5, "@masha", 9)
    assert trust.untrust_user(lists, "5").users == ("@masha",)
    assert trust.untrust_user(lists, "@Masha").users == (5,)
    assert trust.untrust_user(lists, "77") == lists
    assert trust.trust_peer(lists, CHAT) == lists
    assert trust.trust_peer(lists, OTHER_CHAT).peers == (CHAT, OTHER_CHAT)
    assert trust.untrust_peer(lists, CHAT).peers == ()
    assert trust.untrust_peer(lists, CHAT).notes == {CHAT: "свои"}
    assert trust.set_note(lists, OTHER_CHAT, " первая\r\nвторая ").notes == {CHAT: "свои", OTHER_CHAT: "первая\nвторая"}
    assert trust.set_note(lists, CHAT, "  ").notes == {}
    assert lists == TrustLists((5, "@masha"), (CHAT,), {CHAT: "свои"})


def test_only_chats_can_be_trusted_or_annotated():
    for change in (lambda l: trust.trust_peer(l, 22), lambda l: trust.set_note(l, 22, "x"),
                   lambda l: trust.trust_peer(l, -5), lambda l: trust.trust_user(l, 0)):
        with pytest.raises(TrustError):
            change(TrustLists())


@pytest.mark.parametrize("raw,expected", [("5", 5), (" id7 ", 7), ("@id7", 7), ("https://vk.com/id7", 7),
                                          ("@masha", 77), ("vk.com/masha/", 77), ("https://m.vk.com/Masha", 77)])
def test_user_ref_takes_ids_nicks_and_links(raw, expected):
    assert trust.user_ref(raw, lambda names: frozenset({77}) if names == frozenset({"masha"}) else frozenset()) == expected


@pytest.mark.parametrize("raw", ["", "  ", "5 6", "@masha @sasha", "@nobody", "0"])
def test_user_ref_refuses_what_is_not_one_known_person(raw):
    with pytest.raises(TrustError):
        trust.user_ref(raw, no_nicks)


def test_user_ref_reports_a_failed_lookup_as_a_form_error():
    def down(names):
        raise RuntimeError("vk1.secret в тексте ошибки")

    with pytest.raises(TrustError) as error:
        trust.user_ref("@masha", down)
    assert "vk1.secret" not in str(error.value)


@pytest.mark.parametrize("raw,expected", [(str(CHAT), CHAT), ("1", CHAT), ("c2", OTHER_CHAT), (" 2000000002 ", OTHER_CHAT)])
def test_peer_ref_takes_peer_ids_and_chat_numbers(raw, expected):
    assert trust.peer_ref(raw) == expected


@pytest.mark.parametrize("raw", ["", "свои", "-1", "0", "2000000000", "1.5", "²", "c²", "٣",
                                 pytest.param("9" * 5000, id="too-long-for-int")])
def test_peer_ref_refuses_everything_else(raw):
    with pytest.raises(TrustError):
        trust.peer_ref(raw)


def test_save_changes_only_the_agent_keys(tmp_path):
    path = str(tmp_path / "access.json")
    write(path, {"blocked_users": [1], "agent_users": ["@masha"], "peer_prompts": {str(CHAT): ["свои", "люди"]}})
    saved = trust.save(path, lambda lists: trust.trust_peer(trust.trust_user(lists, 5), CHAT))
    assert saved == TrustLists(("@masha", 5), (CHAT,), {CHAT: "свои\nлюди"})
    assert json.loads(read_text(path)) == {"blocked_users": [1], "agent_users": ["@masha", 5], "agent_peers": [CHAT],
                                           "peer_prompts": {str(CHAT): "свои\nлюди"}}
    assert trust.load(path) == saved


def test_save_into_a_missing_file_creates_it(tmp_path):
    path = str(tmp_path / "config" / "access.json")
    trust.save(path, lambda lists: trust.trust_peer(lists, CHAT))
    assert json.loads(read_text(path)) == {"agent_users": [], "agent_peers": [CHAT], "peer_prompts": {}}


@pytest.mark.parametrize("content", [
    '{"agent_users": [5],}',
    '["agent_users"]',
    '{"agent_users": [5], "peer_prompts": ["заметка"]}',
    '{"agent_peers": "2000000001"}',
    '{"agent_users": [{"id": 5}]}',
])
def test_save_over_a_file_of_a_foreign_shape_leaves_it_untouched(tmp_path, content):
    path = str(tmp_path / "access.json")
    write(path, content)
    with pytest.raises(ValueError):
        trust.save(path, lambda lists: trust.trust_peer(lists, CHAT))
    assert read_text(path) == content


def test_unreadable_file_is_still_reported_by_name(tmp_path):
    path = str(tmp_path / "access.json")
    write(path, "{не json")
    with pytest.raises(BrokenConfig, match="access.json"):
        trust.load(path)


def test_failed_change_writes_nothing(tmp_path):
    path = str(tmp_path / "access.json")
    write(path, {"agent_peers": [CHAT]})
    before = read_text(path)
    with pytest.raises(TrustError):
        trust.save(path, lambda lists: trust.trust_peer(lists, 22))
    assert read_text(path) == before


def test_two_saves_at_once_do_not_lose_each_other(tmp_path):
    path = str(tmp_path / "access.json")
    write(path, {"agent_peers": [CHAT]})
    inside, go_on = threading.Event(), threading.Event()

    def slow_untrust(lists):
        inside.set()
        go_on.wait(5)
        return trust.untrust_peer(lists, CHAT)

    first = threading.Thread(target=trust.save, args=(path, slow_untrust))
    second = threading.Thread(target=trust.save, args=(path, lambda lists: trust.trust_user(lists, 5)))
    first.start()
    assert inside.wait(5)
    second.start()
    second.join(0.3)
    # вторая запись ждёт первую: прочти она файл сейчас, её запись вернула бы беседу в доверенные
    assert second.is_alive()
    go_on.set()
    first.join(5)
    second.join(5)
    assert trust.load(path) == TrustLists((5,), (), {})


def test_every_config_file_is_written_under_the_same_lock(tmp_path):
    path = str(tmp_path / "runtime.json")
    write(path, {"paused": False, "active_persona": "rina"})
    inside, go_on = threading.Event(), threading.Event()

    def slow(stored):
        inside.set()
        go_on.wait(5)
        return {**stored, "temperature": 0.5}

    first = threading.Thread(target=update_config, args=(path, slow))
    second = threading.Thread(target=save_runtime_patch, args=(path,), kwargs={"paused": True})
    first.start()
    assert inside.wait(5)
    second.start()
    second.join(0.3)
    assert second.is_alive()
    go_on.set()
    first.join(5)
    second.join(5)
    assert json.loads(read_text(path)) == {"paused": True, "active_persona": "rina", "temperature": 0.5}


def test_failed_change_releases_the_lock_and_writes_nothing(tmp_path):
    path = str(tmp_path / "runtime.json")
    write(path, {"paused": False})

    def broken(stored):
        raise ValueError("не та форма")

    with pytest.raises(ValueError):
        update_config(path, broken)
    assert update_config(path, lambda stored: {**stored, "paused": True}) == {"paused": True}
    assert json.loads(read_text(path)) == {"paused": True}


def vasya_is_11(names):
    return frozenset({11}) if names == frozenset({"vasya"}) else frozenset()


def test_person_is_untrusted_in_every_spelling():
    lists = TrustLists((11, "@vasya", "@masha", 5))
    assert trust.untrust_user_id(lists, 11, vasya_is_11).users == ("@masha", 5)
    assert trust.untrust_user_id(lists, 99, vasya_is_11) == lists


def test_removing_a_row_removes_the_other_spellings_of_the_same_person():
    lists = TrustLists((11, "@vasya", "@masha", 5))
    assert trust.untrust_ref(lists, "11", vasya_is_11).users == ("@masha", 5)
    assert trust.untrust_ref(lists, " @Vasya ", vasya_is_11).users == ("@masha", 5)
    assert trust.untrust_ref(lists, "@masha", vasya_is_11).users == (11, "@vasya", 5)
    assert trust.untrust_ref(lists, "77", vasya_is_11) == lists
    assert trust.untrust_ref(lists, "@nobody", vasya_is_11) == lists


def test_untrusting_fails_loudly_when_a_nick_cannot_be_checked():
    def down(names):
        raise RuntimeError("vk1.secret в тексте ошибки")

    with pytest.raises(TrustError) as error:
        trust.untrust_user_id(TrustLists((11, "@vasya")), 11, down)
    assert "vk1.secret" not in str(error.value)
    with pytest.raises(TrustError):
        trust.untrust_ref(TrustLists((11, "@vasya")), "@vasya", down)
    assert trust.untrust_user_id(TrustLists((11, 5)), 11, down).users == (5,)
    assert trust.untrust_ref(TrustLists((11, 5)), "11", down).users == (5,)


class NoSuchUser(Exception):
    code = 113


def only_vasya_exists(names):
    if names == frozenset({"vasya"}):
        return frozenset({11})
    raise NoSuchUser("Invalid user id, vk1.secret в тексте ошибки")


def test_dead_nick_does_not_block_revoking_trust():
    lists = TrustLists((11, "@ghost", "@vasya", 5))
    assert trust.untrust_user_id(lists, 5, only_vasya_exists).users == (11, "@ghost", "@vasya")
    assert trust.untrust_user_id(lists, 11, only_vasya_exists).users == ("@ghost", 5)
    assert trust.untrust_ref(lists, "5", only_vasya_exists).users == (11, "@ghost", "@vasya")
    assert trust.untrust_ref(lists, "@vasya", only_vasya_exists).users == ("@ghost", 5)
    assert trust.untrust_ref(lists, "@ghost", only_vasya_exists).users == (11, "@vasya", 5)


def test_user_ref_calls_an_unknown_nick_not_found():
    with pytest.raises(TrustError, match="не найден") as error:
        trust.user_ref("@ghost", only_vasya_exists)
    assert "vk1.secret" not in str(error.value)


def test_other_vk_errors_still_stop_the_revocation():
    class Flood(Exception):
        code = 6

    def flooded(names):
        raise Flood("Too many requests")

    with pytest.raises(TrustError):
        trust.untrust_user_id(TrustLists((11, "@vasya")), 11, flooded)
    with pytest.raises(TrustError, match="Не удалось проверить"):
        trust.user_ref("@vasya", flooded)


PEOPLE = {"5": {"id": 5, "first_name": "Маша", "last_name": "Иванова", "screen_name": "masha_i"},
          "vasya": {"id": 11, "first_name": "Вася", "last_name": "Пупкин", "screen_name": "Vasya"}}


class NamesVk:
    def __init__(self, token="vk", nicks_fail=False):
        self.asked = []
        self.nicks_fail = nicks_fail

    def call(self, method, params):
        self.asked.append((method, params))
        if method == "users.get":
            refs = params["user_ids"].split(",")
            if self.nicks_fail and not refs[0].isdigit():
                raise RuntimeError("Invalid user id")
            return [PEOPLE[ref] for ref in refs if ref in PEOPLE]
        return {"items": [{"peer": {"id": CHAT}, "chat_settings": {"title": "лампочки", "state": "in"}},
                          {"peer": {"id": OTHER_CHAT}, "chat_settings": {"title": "старая", "state": "kicked"}}]}


def test_view_names_people_and_chats_and_flags_the_ones_the_account_left():
    vk = NamesVk()
    lists = TrustLists((5, 9, "@vasya", "@ghost"), (CHAT, OTHER_CHAT, CHAT + 6),
                       {CHAT: "свои", CHAT + 8: "заметка без доверия"})
    view = trust.trust_view(lists, lambda: vk)
    assert [(u.ref, u.user_id, u.name, u.missing) for u in view.users] == [
        ("5", 5, "Маша Иванова", False), ("9", 9, "", False),
        ("@vasya", 11, "Вася Пупкин", False), ("@ghost", None, "", True)]
    assert [(p.peer_id, p.title, p.trusted, p.left, p.note) for p in view.peers] == [
        (CHAT, "лампочки", True, False, "свои"),
        (OTHER_CHAT, "старая", True, True, ""),
        (CHAT + 6, "", True, True, ""),
        (CHAT + 8, "", False, True, "заметка без доверия"),
    ]
    assert view.vk_error == ""
    assert vk.asked == [("users.get", {"user_ids": "5,9", "fields": "screen_name"}),
                        ("messages.getConversationsById", {"peer_ids": f"{CHAT},{OTHER_CHAT},{CHAT + 6},{CHAT + 8}"}),
                        ("users.get", {"user_ids": "vasya,ghost", "fields": "screen_name"})]


def test_failed_nick_lookup_keeps_names_and_titles_and_calls_nobody_missing():
    view = trust.trust_view(TrustLists((5, "@vasya"), (CHAT,), {}), lambda: NamesVk(nicks_fail=True))
    assert [(u.ref, u.user_id, u.name, u.missing) for u in view.users] == [("5", 5, "Маша Иванова", False),
                                                                            ("@vasya", None, "", False)]
    assert [(p.title, p.left) for p in view.peers] == [("лампочки", False)]
    assert view.vk_error


def test_view_without_vk_still_lists_everything():
    def down():
        raise RuntimeError("нет связи")

    view = trust.trust_view(TrustLists((5, "@vasya"), (CHAT,), {}), down)
    assert [(u.user_id, u.name, u.missing) for u in view.users] == [(5, "", False), (None, "", False)]
    assert [(p.peer_id, p.title, p.left) for p in view.peers] == [(CHAT, "", False)]
    assert view.vk_error


def test_empty_lists_do_not_touch_vk():
    def never():
        raise AssertionError("VK не нужен")

    assert trust.trust_view(TrustLists(), never) == trust.TrustView((), (), "")


def test_candidate_chat_is_offered_first_with_its_title_and_is_not_trusted():
    view = trust.trust_view(TrustLists((), (OTHER_CHAT,), {}), lambda: NamesVk(), candidate=CHAT)
    assert [(p.peer_id, p.title, p.trusted, p.candidate) for p in view.peers] == [
        (CHAT, "лампочки", False, True), (OTHER_CHAT, "старая", True, False)]
    unknown = trust.trust_view(TrustLists(), lambda: NamesVk(), candidate=CHAT + 6)
    assert [(p.peer_id, p.title, p.left, p.candidate) for p in unknown.peers] == [(CHAT + 6, "", True, True)]


@pytest.mark.parametrize("candidate", [None, 22, -5, 0, 2000000000, OTHER_CHAT])
def test_what_is_not_an_untrusted_chat_is_not_offered(candidate):
    view = trust.trust_view(TrustLists((), (OTHER_CHAT,), {}), lambda: NamesVk(), candidate=candidate)
    assert [(p.peer_id, p.candidate) for p in view.peers] == [(OTHER_CHAT, False)]
