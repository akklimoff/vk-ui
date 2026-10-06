import pytest

from bot.access import AccessLists
from bot.agent import gate
from bot.limits import mention_of
from bot.runtime import RuntimeSettings
from web.im.modes import bot_mode, chat_controls, personas_for

ME, MASHA, DM, CHAT, OTHER_CHAT = 1, 7, 22, 2000000001, 2000000002
TRUSTING = AccessLists(agent_users=frozenset({MASHA}), agent_peers=frozenset({CHAT}), peer_prompts={CHAT: "свои"})


def test_trusted_chat_and_saved_messages_listen():
    assert (bot_mode(CHAT, TRUSTING, RuntimeSettings(), ME).label, bot_mode(CHAT, TRUSTING, RuntimeSettings(), ME).kind) == ("слушает", "ok")
    saved = bot_mode(ME, AccessLists(), RuntimeSettings(), ME)
    assert (saved.label, saved.kind) == ("слушает", "ok") and "Избранное" in saved.reason


def test_everything_else_is_silent_and_says_why():
    untrusted = bot_mode(OTHER_CHAT, TRUSTING, RuntimeSettings(), ME)
    assert (untrusted.label, untrusted.kind) == ("не слушает", "warn") and "не в доверенных" in untrusted.reason
    private = bot_mode(DM, TRUSTING, RuntimeSettings(), ME)
    assert (private.label, private.kind) == ("не слушает", "muted") and "личный диалог" in private.reason
    assert bot_mode(-5, TRUSTING, RuntimeSettings(), ME).label == "не слушает"
    assert bot_mode(CHAT, TRUSTING, RuntimeSettings(paused=True), ME).label == "пауза"
    assert bot_mode(CHAT, TRUSTING, RuntimeSettings(paused_peers=frozenset({CHAT})), ME).label == "пауза"
    assert bot_mode(ME, TRUSTING, RuntimeSettings(paused=True), ME).label == "пауза"


@pytest.mark.parametrize("peer_id", [ME, DM, CHAT, OTHER_CHAT, -5])
@pytest.mark.parametrize("rt", [RuntimeSettings(), RuntimeSettings(paused=True),
                                RuntimeSettings(paused_peers=frozenset({CHAT, ME}))])
@pytest.mark.parametrize("lists", [AccessLists(), TRUSTING])
def test_badge_never_disagrees_with_the_gate(peer_id, rt, lists):
    heard = gate.admit(f"{mention_of(ME)} привет", peer_id, ME, ME, lists.agent_users, lists.agent_peers,
                       rt.paused, rt.paused_peers) is not None
    assert (bot_mode(peer_id, lists, rt, ME).kind == "ok") == heard


def test_personas_come_from_peer_override_or_active():
    rt = RuntimeSettings(active_persona="valentina", peer_personas=((CHAT, ("rina", "monika")),))
    assert personas_for(rt, CHAT) == ("rina", "monika") and personas_for(rt, OTHER_CHAT) == ("valentina",)
    assert bot_mode(CHAT, TRUSTING, rt, ME).personas == ("rina", "monika")


def test_chat_controls_reflect_the_lists_the_bot_reads():
    rt = RuntimeSettings(paused_peers=frozenset({CHAT}), peer_personas=((CHAT, ("rina",)),))
    c = chat_controls(CHAT, TRUSTING, rt, ME)
    assert (c.chat, c.saved, c.listens, c.paused, c.personas, c.note) == (True, False, True, True, ("rina",), "свои")
    assert c.trusted_members == frozenset({MASHA})
    other = chat_controls(OTHER_CHAT, TRUSTING, rt, ME)
    assert (other.listens, other.paused, other.note) == (False, False, "")
    assert (chat_controls(ME, TRUSTING, rt, ME).saved, chat_controls(ME, TRUSTING, rt, ME).chat) == (True, False)
    assert (chat_controls(DM, TRUSTING, rt, ME).saved, chat_controls(DM, TRUSTING, rt, ME).chat) == (False, False)
