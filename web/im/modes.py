from dataclasses import dataclass

from bot.access import AccessLists
from bot.agent import gate
from bot.limits import mention_of
from bot.runtime import RuntimeSettings
from web.im.views import is_chat

LISTENS_SAVED = "«Избранное»: здесь агент слышит владельца, и ему доступен весь аккаунт"
LISTENS_CHAT = "доверенная беседа: агент откликается на тег владельца и доверенных людей"
SILENT = {
    gate.PAUSED: ("пауза", "muted", "пауза: на тег агент не откликнется"),
    gate.PRIVATE_DIALOG: ("не слушает", "muted", "личный диалог: агент работает только в беседах и в «Избранном»"),
    gate.CHAT_NOT_TRUSTED: ("не слушает", "warn", "беседа не в доверенных: на тег агент не откликнется"),
}


@dataclass(frozen=True)
class BotMode:
    label: str
    kind: str
    personas: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class ChatControls:
    peer_id: int
    chat: bool
    saved: bool
    listens: bool
    paused: bool
    personas: tuple[str, ...]
    note: str
    trusted_members: frozenset[int]


def personas_for(rt: RuntimeSettings, peer_id: int) -> tuple[str, ...]:
    override = dict(rt.peer_personas).get(peer_id)
    if override:
        return tuple(override)
    return (rt.active_persona,) if rt.active_persona else ()


def bot_mode(peer_id: int, lists: AccessLists, rt: RuntimeSettings, me_id: int) -> BotMode:
    personas = personas_for(rt, peer_id)
    # «услышит ли агент владельца, если тот тегнет себя здесь» — вопрос к тому же фильтру, что стоит в боте:
    # своих правил у админки нет, поэтому бейдж не может с ним разойтись
    silent = gate.rejection(mention_of(me_id), peer_id, me_id, me_id, lists.agent_users, lists.agent_peers,
                            rt.paused, rt.paused_peers)
    if silent is None:
        return BotMode("слушает", "ok", personas, LISTENS_SAVED if peer_id == me_id else LISTENS_CHAT)
    label, kind, reason = SILENT.get(silent, ("не слушает", "muted", silent))
    return BotMode(label, kind, personas, reason)


def chat_controls(peer_id: int, lists: AccessLists, rt: RuntimeSettings, me_id: int) -> ChatControls:
    return ChatControls(
        peer_id=peer_id, chat=is_chat(peer_id), saved=peer_id == me_id,
        listens=peer_id in lists.agent_peers, paused=peer_id in rt.paused_peers,
        personas=tuple(dict(rt.peer_personas).get(peer_id, ())),
        note=lists.peer_prompts.get(peer_id, ""),
        trusted_members=lists.agent_users,
    )
