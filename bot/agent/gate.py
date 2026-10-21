import re
from dataclasses import dataclass
from typing import Iterable

from bot.limits import mention_of
from common.commands import addressed_to_bots

CHAT, SAVED = "chat", "saved"
OWNER, TRUSTED = "owner", "trusted"
GROUP_CHAT_PEER_BASE = 2_000_000_000

NO_SENDER = "no_sender"
COMMUNITY_SENDER = "community_sender"
ADDRESSED_TO_BOTS = "addressed_to_bots"
NO_TAG = "no_tag"
PAUSED = "paused"
PRIVATE_DIALOG = "private_dialog"
CHAT_NOT_TRUSTED = "chat_not_trusted"
USER_NOT_TRUSTED = "user_not_trusted"
REASONS = (NO_SENDER, COMMUNITY_SENDER, ADDRESSED_TO_BOTS, NO_TAG, PAUSED, PRIVATE_DIALOG, CHAT_NOT_TRUSTED,
           USER_NOT_TRUSTED)


@dataclass(frozen=True)
class Caller:
    place: str
    role: str


MENTION = re.compile(r"\[(?:id|club|public)\d+\|[^\]]*\]")


def name_pattern(name: str) -> re.Pattern:
    return re.compile(rf"(?<!\w){re.escape(name)}(?!\w)")


def called_by_name(text: str | None, name: str) -> bool:
    """Имя персоны отдельным словом и ровно в её написании: «Валентина», но не «валентина» и не «Валентину»."""
    # тег другого человека с тем же именем — обращение к нему, а не к агенту
    return bool(name) and name_pattern(name).search(MENTION.sub(" ", text or "")) is not None


def without_names(text: str, names: Iterable[str]) -> str:
    for name in filter(None, names):
        text = name_pattern(name).sub(" ", text)
    return re.sub(r"\s+", " ", text).strip().strip(",:").strip()


def addressed(text: str | None, me_id: int, names: Iterable[str] = ()) -> bool:
    return mention_of(me_id) in (text or "") or any(called_by_name(text, name) for name in names)


def _decide(text: str | None, peer_id: int, from_id: int | None, me_id: int,
            agent_users: frozenset[int], agent_peers: frozenset[int],
            paused: bool, paused_peers: frozenset[int], names: Iterable[str], reply_to_me: bool) -> Caller | str:
    if from_id is None:
        return NO_SENDER
    if from_id <= 0:
        return COMMUNITY_SENDER
    if addressed_to_bots(text):
        return ADDRESSED_TO_BOTS
    # в «Избранном» все сообщения — владельца, и ответ на любое из них позвал бы агента
    replied = reply_to_me and peer_id >= GROUP_CHAT_PEER_BASE
    if not replied and not addressed(text, me_id, names):
        return NO_TAG
    if paused or peer_id in paused_peers:
        return PAUSED
    if peer_id == me_id and from_id == me_id:
        return Caller(SAVED, OWNER)
    if peer_id < GROUP_CHAT_PEER_BASE:
        return PRIVATE_DIALOG
    if peer_id not in agent_peers:
        return CHAT_NOT_TRUSTED
    if from_id == me_id:
        return Caller(CHAT, OWNER)
    if from_id in agent_users:
        return Caller(CHAT, TRUSTED)
    return USER_NOT_TRUSTED


def admit(text: str | None, peer_id: int, from_id: int | None, me_id: int,
          agent_users: frozenset[int], agent_peers: frozenset[int],
          paused: bool = False, paused_peers: frozenset[int] = frozenset(),
          names: Iterable[str] = (), reply_to_me: bool = False) -> Caller | None:
    """Кто и откуда просит агента; None — событие не для него и дальше идти не должно."""
    decision = _decide(text, peer_id, from_id, me_id, agent_users, agent_peers, paused, paused_peers, names,
                       reply_to_me)
    return decision if isinstance(decision, Caller) else None


def rejection(text: str | None, peer_id: int, from_id: int | None, me_id: int,
              agent_users: frozenset[int], agent_peers: frozenset[int],
              paused: bool = False, paused_peers: frozenset[int] = frozenset(),
              names: Iterable[str] = (), reply_to_me: bool = False) -> str | None:
    """Почему событие не для агента; None — оно принято."""
    decision = _decide(text, peer_id, from_id, me_id, agent_users, agent_peers, paused, paused_peers, names,
                       reply_to_me)
    return None if isinstance(decision, Caller) else decision
