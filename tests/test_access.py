import json
import os
from dataclasses import fields

import pytest

import bot.access
import common.hotfile
from bot.access import AccessFile, AccessLists, parse_access

RESOLVE = {"kamyrc": 555, "aktan": 777}
CHAT = 2000000007


def fake_resolver(names):
    return frozenset(RESOLVE[name] for name in names if name in RESOLVE)


def test_agent_lists_take_nicks_ids_and_peers():
    lists = parse_access({"agent_users": ["@kamyrc", 5, "@id99"], "agent_peers": [CHAT, "2000000008"],
                          "peer_prompts": {str(CHAT): "тут все друзья", "2000000008": ""}}, fake_resolver)
    assert lists.agent_users == frozenset({5, 99, 555})
    assert lists.agent_peers == frozenset({CHAT, 2000000008})
    assert lists.peer_prompts == {CHAT: "тут все друзья"}


def test_unknown_nicks_are_dropped():
    assert parse_access({"agent_users": ["@nonexistent", 5]}, fake_resolver).agent_users == frozenset({5})


def test_agent_lists_are_empty_without_keys():
    assert parse_access({}, fake_resolver) == AccessLists()


def test_lists_hold_only_what_the_agent_reads():
    assert [f.name for f in fields(AccessLists)] == ["agent_users", "agent_peers", "peer_prompts"]
    for name in ("legacy_lists", "blocked_for", "private_prompts", "scoped_prompts"):
        assert not hasattr(bot.access, name), name


def test_keys_of_the_old_modes_are_ignored_whatever_they_hold():
    lists = parse_access(
        {"peer_blocked_users": {"не число": [1]}, "user_prompts": ["список вместо объекта"], "blocked_peers": ["x"],
         "auto_reply_users": "мусор", "agent_users": [5], "agent_peers": [CHAT], "peer_prompts": {str(CHAT): "свои"}},
        fake_resolver,
    )
    assert lists == AccessLists(frozenset({5}), frozenset({CHAT}), {CHAT: "свои"})


def test_bad_agent_entries_are_skipped_one_by_one():
    lists = parse_access(
        {"agent_users": [5, None, True, {"id": 6}, "@kamyrc"], "agent_peers": [CHAT, "беседа", None, 1.5],
         "peer_prompts": {str(CHAT): ["свои", "люди"], "мусор": "x"}},
        fake_resolver,
    )
    assert lists.agent_users == frozenset({5, 555})
    assert lists.agent_peers == frozenset({CHAT})
    assert lists.peer_prompts == {CHAT: "свои\nлюди"}


def test_agent_keys_of_a_wrong_type_mean_empty_lists():
    lists = parse_access({"agent_users": "5", "agent_peers": {str(CHAT): 1}, "peer_prompts": ["заметка"]},
                         fake_resolver)
    assert lists == AccessLists()


def test_access_that_is_not_an_object_is_an_error():
    with pytest.raises(ValueError):
        parse_access(["agent_users"], fake_resolver)


def test_missing_file_means_empty_lists(tmp_path):
    assert AccessFile(str(tmp_path / "access.json"), fake_resolver).current() == AccessLists()


def test_file_reloads_on_change(tmp_path):
    path = tmp_path / "access.json"
    path.write_text(json.dumps({"agent_users": [2]}))
    access = AccessFile(str(path), fake_resolver)
    assert access.current().agent_users == frozenset({2})

    path.write_text(json.dumps({"agent_users": [3]}))
    os.utime(path, (0, os.stat(path).st_mtime + 1))
    assert access.current().agent_users == frozenset({3})


def test_broken_file_keeps_previous_lists(tmp_path):
    path = tmp_path / "access.json"
    path.write_text(json.dumps({"agent_users": [2]}))
    access = AccessFile(str(path), fake_resolver)
    access.current()

    path.write_text("не json")
    os.utime(path, (0, os.stat(path).st_mtime + 1))
    assert access.current().agent_users == frozenset({2})


def test_deleted_file_empties_lists(tmp_path):
    path = tmp_path / "access.json"
    path.write_text(json.dumps({"agent_users": [2]}))
    access = AccessFile(str(path), fake_resolver)
    access.current()

    path.unlink()
    assert access.current() == AccessLists()


class VkAnswer(Exception):
    def __init__(self, code):
        super().__init__(f"VK {code}")
        self.code = code


def resolver_with_a_dead_nick(names):
    if "gone" in names:
        raise VkAnswer(113)
    return fake_resolver(names)


def rewrite(path, data):
    path.write_text(json.dumps(data))
    os.utime(path, (0, os.stat(path).st_mtime + 1))


def test_dead_nick_does_not_keep_the_removed_peer_and_people_trusted(tmp_path):
    path = tmp_path / "access.json"
    path.write_text(json.dumps({"agent_users": [5, "@gone"], "agent_peers": [CHAT]}))
    access = AccessFile(str(path), resolver_with_a_dead_nick)
    assert access.current() == AccessLists(frozenset({5}), frozenset({CHAT}))

    rewrite(path, {"agent_users": ["@gone"], "agent_peers": []})
    assert access.current() == AccessLists()


def test_dead_nick_leaves_the_other_nicks_resolved():
    lists = parse_access({"agent_users": ["@gone", "@kamyrc", 5]}, resolver_with_a_dead_nick)
    assert lists.agent_users == frozenset({5, 555})


def test_dead_nick_is_reported_and_not_asked_again_until_the_file_changes(tmp_path, caplog, monkeypatch):
    monkeypatch.setattr(common.hotfile, "RETRY_SECONDS", 0)
    asked = []

    def resolver(names):
        asked.append(set(names))
        return resolver_with_a_dead_nick(names)

    path = tmp_path / "access.json"
    path.write_text(json.dumps({"agent_users": ["@gone"]}))
    access = AccessFile(str(path), resolver)
    with caplog.at_level("WARNING", logger="vk-bot"):
        access.current()
        access.current()
    assert asked == [{"gone"}]
    assert any("gone" in record.getMessage() for record in caplog.records)


def test_nick_vk_resolves_to_nobody_grants_nobody():
    assert parse_access({"agent_users": ["@nonexistent"]}, fake_resolver).agent_users == frozenset()


class Outage:
    def __init__(self):
        self.down = False

    def __call__(self, names):
        if self.down:
            raise RuntimeError("VK недоступен")
        return fake_resolver(names)


def test_revocation_applies_while_vk_is_unreachable(tmp_path):
    vk = Outage()
    path = tmp_path / "access.json"
    path.write_text(json.dumps({"agent_users": [5, "@kamyrc", "@aktan"], "agent_peers": [CHAT, 2000000008],
                                "peer_prompts": {str(CHAT): "свои"}}))
    access = AccessFile(str(path), vk)
    assert access.current().agent_users == frozenset({5, 555, 777})

    vk.down = True
    rewrite(path, {"agent_users": ["@kamyrc"], "agent_peers": [2000000008]})
    assert access.current() == AccessLists(frozenset({555}), frozenset({2000000008}))


def test_nick_added_while_vk_is_unreachable_grants_nobody_until_vk_answers(tmp_path, monkeypatch):
    monkeypatch.setattr(common.hotfile, "RETRY_SECONDS", 0)
    vk = Outage()
    vk.down = True
    path = tmp_path / "access.json"
    path.write_text(json.dumps({"agent_users": [5, "@kamyrc"]}))
    access = AccessFile(str(path), vk)
    assert access.current().agent_users == frozenset({5})

    vk.down = False
    assert access.current().agent_users == frozenset({5, 555})


def test_unanswered_nicks_are_not_asked_again_before_the_pause_ends(tmp_path):
    vk = Outage()
    vk.down = True
    path = tmp_path / "access.json"
    path.write_text(json.dumps({"agent_users": ["@kamyrc"]}))
    access = AccessFile(str(path), vk)
    access.current()

    vk.down = False
    assert access.current().agent_users == frozenset()


def test_nick_removed_from_the_file_is_forgotten_even_if_it_returns_during_an_outage(tmp_path):
    vk = Outage()
    path = tmp_path / "access.json"
    path.write_text(json.dumps({"agent_users": ["@kamyrc"]}))
    access = AccessFile(str(path), vk)
    access.current()

    rewrite(path, {"agent_users": []})
    access.current()
    vk.down = True
    rewrite(path, {"agent_users": ["@kamyrc"]})
    assert access.current().agent_users == frozenset()


@pytest.mark.parametrize("ref", ["²", "٣", "2000000007²", "9" * 5000],
                         ids=["superscript", "arabic-indic", "superscript-tail", "too-long"])
def test_entries_int_cannot_read_are_skipped_one_by_one(ref):
    lists = parse_access({"agent_users": [5, ref, f"id{ref}"], "agent_peers": [CHAT, ref],
                          "peer_prompts": {str(CHAT): "свои", ref: "чужие"}}, fake_resolver)
    assert lists == AccessLists(frozenset({5}), frozenset({CHAT}), {CHAT: "свои"})


def test_names_that_cannot_be_nicks_are_not_sent_to_vk():
    asked = []

    def resolver(names):
        asked.append(set(names))
        return fake_resolver(names)

    parse_access({"agent_users": ["@²", "@kamyrc", "ник с пробелом?"]}, resolver)
    assert {"kamyrc"} in asked
    assert all(name.isascii() and "?" not in name for names in asked for name in names)
