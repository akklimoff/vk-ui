from bot.access import AccessLists
from bot.runtime import RuntimeSettings
from web.im.modes import bot_mode, chat_controls

CHAT, USER = 2000000001, 22


def test_private_dialog_modes():
    assert bot_mode(USER, AccessLists(), RuntimeSettings()).label == "по тегу"
    assert bot_mode(USER, AccessLists(auto_reply_users=frozenset({USER})), RuntimeSettings()).label == "авто"
    assert bot_mode(USER, AccessLists(blocked_users=frozenset({USER})), RuntimeSettings()).label == "блок"


def test_chat_modes_by_priority():
    lists = AccessLists(auto_reply_peers=frozenset({CHAT}), onboarding_peers=frozenset({CHAT}))
    assert bot_mode(CHAT, lists, RuntimeSettings()).label == "знакомство"
    assert bot_mode(CHAT, AccessLists(auto_reply_peers=frozenset({CHAT})), RuntimeSettings()).label == "авто"
    assert bot_mode(CHAT, lists, RuntimeSettings(paused_peers=frozenset({CHAT}))).label == "пауза"
    assert bot_mode(CHAT, lists, RuntimeSettings(paused=True)).label == "пауза"
    assert bot_mode(CHAT, AccessLists(allowed_peers=frozenset({7})), RuntimeSettings()).label == "вне белого списка"
    assert bot_mode(-100, AccessLists(), RuntimeSettings()).label == "молчит"


def test_personas_come_from_peer_override_or_active():
    rt = RuntimeSettings(active_persona="valentina", peer_personas=((CHAT, ("rina", "monika")),))
    assert bot_mode(CHAT, AccessLists(), rt).personas == ("rina", "monika")
    assert bot_mode(USER, AccessLists(), rt).personas == ("valentina",)


def test_chat_controls_reflect_lists():
    lists = AccessLists(auto_reply_peers=frozenset({CHAT}), peer_prompts={CHAT: "тут все свои"},
                        peer_blocked_users={CHAT: frozenset({11})})
    c = chat_controls(CHAT, lists, RuntimeSettings(paused_peers=frozenset({CHAT})))
    assert not c.private and c.auto and not c.onboarding and c.paused and c.prompt == "тут все свои"
    assert c.blocked_members == frozenset({11})
    u = chat_controls(USER, AccessLists(user_prompts={USER: "подруга"}), RuntimeSettings())
    assert u.private and u.prompt == "подруга" and not u.auto
