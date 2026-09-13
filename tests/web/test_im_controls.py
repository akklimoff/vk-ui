from web.im.controls import (set_keyed_text, set_member, set_paused_peer, set_peer_blocked,
                             set_peer_personas)

resolve = lambda names: frozenset({22}) if "anya" in names else frozenset()


def test_set_member_adds_once_and_removes_every_spelling():
    data = {"auto_reply_users": ["@anya", 22, "@someone"]}
    off = set_member(data, "auto_reply_users", 22, False, resolve)
    assert off["auto_reply_users"] == ["@someone"]
    assert data["auto_reply_users"] == ["@anya", 22, "@someone"]
    on = set_member(off, "auto_reply_users", 22, True, resolve)
    assert on["auto_reply_users"] == ["@someone", 22]
    assert set_member(on, "auto_reply_users", 22, True, resolve)["auto_reply_users"] == ["@someone", 22]


def test_set_member_on_peer_lists_needs_no_resolver():
    assert set_member({}, "auto_reply_peers", 2000000001, True)["auto_reply_peers"] == [2000000001]
    assert set_member({"blocked_peers": [7, 8]}, "blocked_peers", 7, False)["blocked_peers"] == [8]


def test_set_keyed_text_reuses_existing_nick_key_and_drops_empty():
    data = {"user_prompts": {"@anya": "старый", "@other": "x"}}
    upd = set_keyed_text(data, "user_prompts", 22, "новый ", resolve)
    assert upd["user_prompts"] == {"@anya": "новый", "@other": "x"}
    assert set_keyed_text(upd, "user_prompts", 22, "  ", resolve)["user_prompts"] == {"@other": "x"}
    assert set_keyed_text({}, "peer_prompts", 2000000001, "свои")["peer_prompts"] == {"2000000001": "свои"}


def test_set_peer_blocked():
    data = {"peer_blocked_users": {"2000000001": ["@anya", 11]}}
    off = set_peer_blocked(data, 2000000001, 22, False, resolve)
    assert off["peer_blocked_users"] == {"2000000001": [11]}
    assert set_peer_blocked(off, 2000000001, 11, False)["peer_blocked_users"] == {}
    assert set_peer_blocked({}, 5, 9, True)["peer_blocked_users"] == {"5": [9]}


def test_runtime_edits():
    assert set_paused_peer({"paused_peers": [1]}, 2, True)["paused_peers"] == [1, 2]
    assert set_paused_peer({"paused_peers": [1, 2]}, 1, False)["paused_peers"] == [2]
    rt = set_peer_personas({"peer_personas": {"5": "rina"}}, 6, ["rina", "monika"])
    assert rt["peer_personas"] == {"5": "rina", "6": ["rina", "monika"]}
    assert set_peer_personas(rt, 6, [])["peer_personas"] == {"5": "rina"}
    assert set_peer_personas(rt, 6, ["monika"])["peer_personas"]["6"] == "monika"
