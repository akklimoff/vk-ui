import os

from bot.agent import gate
from bot.agent.rejections import KNOWN_REASONS, QUEUE_FULL, RATE_LIMITED
from bot.status import write_json_atomic
from web import state
from web.trust import TrustLists

CHAT, OTHER_CHAT, MASHA, STRANGER = 2000000001, 2000000002, 7, 9


def rejections(state_dir, *rows):
    write_json_atomic(f"{state_dir}/rejections.json", {"rejections": [
        {"ts": ts, "peer_id": peer, "from_id": user, "reason": reason, "count": 1} for ts, peer, user, reason in rows]})


def test_pending_lists_what_is_still_waited_for(settings):
    write_json_atomic(f"{settings.state_dir}/pending.json", {"pending": [
        {"peer_id": CHAT, "user_id": 1, "method": "wall.post", "title": "Опубликовать пост",
         "params": {"message": "пост", "owner_id": -5}, "asked_at": 900.0, "expires_at": 1200.0},
        {"peer_id": CHAT, "user_id": 2, "method": "messages.delete", "title": "Удалить сообщения", "params": {},
         "asked_at": 600.0, "expires_at": 900.0},
        {"peer_id": "беседа", "expires_at": 5000.0}, "строка", None,
    ]})
    waiting, = state.pending_now(settings.state_dir, now=1000.0)
    assert (waiting.peer_id, waiting.user_id, waiting.title, waiting.seconds_left) == (CHAT, 1, "Опубликовать пост", 200.0)
    assert waiting.params == (("message", "пост"), ("owner_id", "-5"))


def test_pending_rows_that_never_expire_or_have_no_real_ids_are_skipped(settings):
    os.makedirs(settings.state_dir, exist_ok=True)
    with open(f"{settings.state_dir}/pending.json", "w", encoding="utf-8") as f:
        f.write('{"pending": [{"peer_id": 2000000001, "user_id": 1, "expires_at": Infinity},'
                ' {"peer_id": 2000000001, "user_id": 1, "expires_at": NaN},'
                ' {"peer_id": Infinity, "user_id": 1, "expires_at": 1200.0},'
                ' {"peer_id": 2000000001, "user_id": 2, "expires_at": 1200.0}]}')
    waiting, = state.pending_now(settings.state_dir, now=1000.0)
    assert waiting.user_id == 2


def test_rejection_rows_with_ids_that_are_not_finite_are_skipped(settings):
    os.makedirs(settings.state_dir, exist_ok=True)
    with open(f"{settings.state_dir}/rejections.json", "w", encoding="utf-8") as f:
        f.write('{"rejections": [{"ts": 2.0, "peer_id": Infinity, "from_id": 9, "reason": "no_tag"},'
                ' {"ts": Infinity, "peer_id": 2000000001, "from_id": 9, "reason": "no_tag"},'
                ' {"ts": 1.0, "peer_id": 2000000001, "from_id": 9, "reason": "%s"}]}' % gate.NO_TAG)
    assert [row.ts for row in state.recent_rejections(settings.state_dir, TrustLists(), {})] == [1.0]


def test_person_trusted_by_nick_no_longer_has_a_not_trusted_row(settings):
    rejections(settings.state_dir, (2.0, CHAT, MASHA, gate.USER_NOT_TRUSTED), (1.0, CHAT, STRANGER, gate.USER_NOT_TRUSTED))
    by_nick = TrustLists(users=("@masha",), peers=(CHAT,))
    assert len(state.recent_rejections(settings.state_dir, by_nick, {})) == 2
    left = state.recent_rejections(settings.state_dir, by_nick, {}, trusted_ids=frozenset({MASHA}))
    assert [row.from_id for row in left] == [STRANGER]


def test_missing_or_garbage_pending_file_means_nothing_waits(settings):
    assert state.pending_now(settings.state_dir, now=1.0) == ()
    os.makedirs(settings.state_dir, exist_ok=True)
    for content in ("{не json", "[1, 2]", '{"pending": "строка"}', ""):
        with open(f"{settings.state_dir}/pending.json", "w", encoding="utf-8") as f:
            f.write(content)
        assert state.pending_now(settings.state_dir, now=1.0) == ()


def test_rejections_are_named_and_only_untrusted_chats_can_be_trusted(settings):
    rejections(settings.state_dir, (3.0, CHAT, STRANGER, gate.CHAT_NOT_TRUSTED), (2.0, OTHER_CHAT, STRANGER, gate.USER_NOT_TRUSTED),
               (1.0, 22, STRANGER, gate.PRIVATE_DIALOG))
    rows = state.recent_rejections(settings.state_dir, TrustLists(peers=(OTHER_CHAT,)), {})
    assert [(r.peer_id, r.reason, r.trustable) for r in rows] == [
        (CHAT, "беседа не в доверенных", True),
        (OTHER_CHAT, "человек не в доверенных", False),
        (22, "личный диалог: агент работает только в беседах", False),
    ]


def test_requests_dropped_after_the_gate_are_explained_and_never_trustable(settings):
    rejections(settings.state_dir, (2.0, CHAT, MASHA, RATE_LIMITED), (1.0, CHAT, MASHA, QUEUE_FULL))
    rows = state.recent_rejections(settings.state_dir, TrustLists(), {})
    assert [(r.reason, r.trustable) for r in rows] == [("слишком часто: сработал лимит частоты", False),
                                                       ("очередь просьб была полна", False)]


def test_every_reason_the_bot_can_write_has_a_label():
    assert set(state.REASONS) == set(KNOWN_REASONS)


def test_rejections_that_no_longer_hold_are_hidden(settings):
    rejections(settings.state_dir, (3.0, CHAT, STRANGER, gate.CHAT_NOT_TRUSTED), (2.0, CHAT, MASHA, gate.USER_NOT_TRUSTED),
               (1.0, OTHER_CHAT, MASHA, gate.PAUSED))
    now_trusted = TrustLists(users=(MASHA, "@sasha"), peers=(CHAT,))
    assert state.recent_rejections(settings.state_dir, now_trusted, {"paused": False, "paused_peers": []}) == ()
    paused = state.recent_rejections(settings.state_dir, now_trusted, {"paused_peers": [OTHER_CHAT]})
    assert [r.reason for r in paused] == ["пауза"]
    assert len(state.recent_rejections(settings.state_dir, now_trusted, {"paused": True})) == 1
    assert state.recent_rejections(settings.state_dir, now_trusted, {"paused_peers": "мусор"}) == ()


def test_only_the_newest_rejections_are_shown(settings):
    rejections(settings.state_dir, *[(float(i), CHAT + i, STRANGER, gate.CHAT_NOT_TRUSTED) for i in range(1, 15)])
    rows = state.recent_rejections(settings.state_dir, TrustLists(), {}, limit=3)
    assert [r.peer_id for r in rows] == [CHAT + 14, CHAT + 13, CHAT + 12]


def test_missing_rejections_file_is_an_empty_list(settings):
    assert state.recent_rejections(settings.state_dir, TrustLists(), {}) == ()
