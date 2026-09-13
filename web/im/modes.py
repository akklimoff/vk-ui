from dataclasses import dataclass

from bot.access import AccessLists
from bot.runtime import RuntimeSettings
from web.im.views import is_chat


@dataclass(frozen=True)
class BotMode:
    label: str
    kind: str
    personas: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class ChatControls:
    peer_id: int
    private: bool
    auto: bool
    onboarding: bool
    blocked: bool
    paused: bool
    personas: tuple[str, ...]
    prompt: str
    blocked_members: frozenset[int]


def personas_for(rt: RuntimeSettings, peer_id: int) -> tuple[str, ...]:
    override = dict(rt.peer_personas).get(peer_id)
    if override:
        return tuple(override)
    return (rt.active_persona,) if rt.active_persona else ()


def bot_mode(peer_id: int, lists: AccessLists, rt: RuntimeSettings) -> BotMode:
    personas = personas_for(rt, peer_id)
    if peer_id < 0:
        return BotMode("молчит", "muted", personas, "сообщества бот игнорирует всегда")
    if rt.paused:
        return BotMode("пауза", "muted", personas, "бот на паузе целиком")
    if peer_id in rt.paused_peers:
        return BotMode("пауза", "muted", personas, "чат на паузе (paused_peers)")
    if peer_id in lists.blocked_peers:
        return BotMode("блок", "bad", personas, "чат в blocked_peers")
    if not is_chat(peer_id) and peer_id in lists.blocked_users:
        return BotMode("блок", "bad", personas, "собеседник в blocked_users")
    if lists.allowed_peers and peer_id not in lists.allowed_peers:
        return BotMode("вне белого списка", "bad", personas, "allowed_peers задан, чата в нём нет")
    if not is_chat(peer_id):
        if peer_id in lists.auto_reply_users:
            return BotMode("авто", "ok", personas, "отвечает на каждое сообщение (auto_reply_users)")
        return BotMode("по тегу", "warn", personas, "отвечает только на упоминание")
    if peer_id in lists.onboarding_peers:
        return BotMode("знакомство", "ok", personas, "знакомится с новичками (onboarding_peers)")
    if peer_id in lists.auto_reply_peers:
        return BotMode("авто", "ok", personas, "отвечает всем без тега (auto_reply_peers)")
    return BotMode("по тегу", "warn", personas, "отвечает только на упоминание")


def chat_controls(peer_id: int, lists: AccessLists, rt: RuntimeSettings) -> ChatControls:
    private = not is_chat(peer_id)
    return ChatControls(
        peer_id=peer_id, private=private,
        auto=peer_id in (lists.auto_reply_users if private else lists.auto_reply_peers),
        onboarding=not private and peer_id in lists.onboarding_peers,
        blocked=peer_id in (lists.blocked_users if private else lists.blocked_peers),
        paused=peer_id in rt.paused_peers,
        personas=tuple(dict(rt.peer_personas).get(peer_id, ())),
        prompt=(lists.user_prompts if private else lists.peer_prompts).get(peer_id, ""),
        blocked_members=lists.peer_blocked_users.get(peer_id, frozenset()),
    )
