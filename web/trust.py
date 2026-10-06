import re
from dataclasses import dataclass, field, replace
from typing import Callable

from bot.access import NICK, NO_SUCH_USER_CODE, WHOLE_NUMBER, join_lines
from bot.config import parse_user_refs
from web.services import read_config_for_update, update_config

GROUP_CHAT_PEER_BASE = 2_000_000_000
VK_URL = re.compile(r"^(?:https?://)?(?:m\.)?vk\.(?:com|ru)/", re.IGNORECASE)
VK_SILENT = "VK не ответил: имена и названия не показаны"
NICKS_SILENT = "VK не ответил про ники: на кого они указывают, не показано"


class TrustError(ValueError):
    """Списки доверия в access.json или ввод в форме не той формы."""


@dataclass(frozen=True)
class TrustLists:
    users: tuple[int | str, ...] = ()
    peers: tuple[int, ...] = ()
    notes: dict[int, str] = field(default_factory=dict)


def is_chat(peer_id: int) -> bool:
    return peer_id > GROUP_CHAT_PEER_BASE


def user_entry(item) -> int | str:
    if isinstance(item, bool) or not isinstance(item, (int, str)):
        raise TrustError("agent_users: каждая запись должна быть id или @ником")
    ids, names = parse_user_refs(str(item))
    if len(ids) + len(names) != 1:
        raise TrustError(f"agent_users: непонятная запись «{item}»")
    if ids:
        return next(iter(ids))
    name = next(iter(names))
    if not NICK.fullmatch(name):
        raise TrustError(f"agent_users: непонятная запись «{item}»")
    return f"@{name}"


def peer_entry(item, key: str) -> int:
    text = str(item).strip()
    if (isinstance(item, bool) or not isinstance(item, (int, str)) or not WHOLE_NUMBER.fullmatch(text)
            or not is_chat(int(text))):
        raise TrustError(f"{key}: «{item}» — не номер беседы")
    return int(text)


def note_entry(peer_id: int, value) -> str:
    if isinstance(value, str) or (isinstance(value, list) and all(isinstance(line, str) for line in value)):
        return join_lines(value)
    raise TrustError(f"peer_prompts: заметка беседы {peer_id} должна быть текстом")


def read_lists(stored: dict) -> TrustLists:
    users = stored.get("agent_users")
    peers = stored.get("agent_peers")
    notes = stored.get("peer_prompts")
    if users is not None and not isinstance(users, list):
        raise TrustError("agent_users должен быть списком")
    if peers is not None and not isinstance(peers, list):
        raise TrustError("agent_peers должен быть списком")
    if notes is not None and not isinstance(notes, dict):
        raise TrustError("peer_prompts должен быть объектом «беседа: заметка»")
    texts = {}
    for ref, value in (notes or {}).items():
        peer_id = peer_entry(ref, "peer_prompts")
        text = note_entry(peer_id, value)
        if text:
            texts[peer_id] = text
    return TrustLists(tuple(dict.fromkeys(user_entry(item) for item in users or [])),
                      tuple(dict.fromkeys(peer_entry(item, "agent_peers") for item in peers or [])),
                      texts)


def dump_lists(stored: dict, lists: TrustLists) -> dict:
    return {**stored, "agent_users": list(lists.users), "agent_peers": list(lists.peers),
            "peer_prompts": {str(peer_id): text for peer_id, text in lists.notes.items()}}


def load(path: str) -> TrustLists:
    return read_lists(read_config_for_update(path))


def save(path: str, change: Callable[[TrustLists], TrustLists]) -> TrustLists:
    """Единственная запись списков доверия: файл читается строго, и при любой ошибке остаётся прежним."""
    return read_lists(update_config(path, lambda stored: dump_lists(stored, change(read_lists(stored)))))


def trust_user(lists: TrustLists, user_id: int) -> TrustLists:
    if user_id <= 0:
        raise TrustError("Доверять можно только человеку")
    return lists if user_id in lists.users else replace(lists, users=(*lists.users, user_id))


def untrust_user(lists: TrustLists, ref: str) -> TrustLists:
    key = ref.strip().lower()
    return replace(lists, users=tuple(entry for entry in lists.users if str(entry) != key))


def nick_ids(name: str, resolve, advice: str) -> frozenset[int]:
    """Ника нет — пустой ответ, а не сбой: иначе одна мёртвая строка в файле не давала бы снять доверие ни с кого."""
    try:
        return resolve(frozenset({name}))
    except Exception as error:
        if getattr(error, "code", None) == NO_SUCH_USER_CODE:
            return frozenset()
        # текст ошибки VK может содержать адрес запроса с токеном, поэтому в ответ он не идёт
        raise TrustError(f"Не удалось проверить ник «{name}» в VK, {advice}") from None


def nick_owner(entry: str, resolve) -> int | None:
    found = nick_ids(entry.lstrip("@"), resolve, "попробуйте ещё раз")
    return next(iter(found)) if len(found) == 1 else None


def untrust_user_id(lists: TrustLists, user_id: int, resolve) -> TrustLists:
    """Убрать человека во всех написаниях: и по id, и ником, вписанным в файл руками, — иначе он остался бы доверенным."""
    return replace(lists, users=tuple(
        entry for entry in lists.users
        if entry != user_id and not (isinstance(entry, str) and nick_owner(entry, resolve) == user_id)))


def untrust_ref(lists: TrustLists, ref: str, resolve) -> TrustLists:
    """Убрать строку списка и все остальные написания того же человека."""
    key = ref.strip().lower()
    entry = next((entry for entry in lists.users if str(entry) == key), None)
    if entry is None:
        return lists
    user_id = entry if isinstance(entry, int) else nick_owner(entry, resolve)
    rest = untrust_user(lists, key)
    return rest if user_id is None else untrust_user_id(rest, user_id, resolve)


def a_chat(peer_id: int) -> int:
    if not is_chat(peer_id):
        raise TrustError("Агент работает только в беседах: личным диалогам доверие не выдаётся")
    return peer_id


def trust_peer(lists: TrustLists, peer_id: int) -> TrustLists:
    a_chat(peer_id)
    return lists if peer_id in lists.peers else replace(lists, peers=(*lists.peers, peer_id))


def untrust_peer(lists: TrustLists, peer_id: int) -> TrustLists:
    return replace(lists, peers=tuple(peer for peer in lists.peers if peer != peer_id))


def set_note(lists: TrustLists, peer_id: int, text: str) -> TrustLists:
    a_chat(peer_id)
    # браузер отправляет переводы строк textarea как CRLF
    text = text.replace("\r\n", "\n").strip()
    notes = {peer: note for peer, note in lists.notes.items() if peer != peer_id}
    if text:
        notes[peer_id] = text
    return replace(lists, notes=notes)


def user_ref(raw: str, resolve) -> int:
    ids, names = parse_user_refs(VK_URL.sub("", raw.strip()).strip("/"))
    if len(ids) + len(names) != 1:
        raise TrustError("Нужен один человек: id, @ник или ссылка на страницу")
    if ids:
        user_id = next(iter(ids))
    else:
        name = next(iter(names))
        found = nick_ids(name, resolve, "попробуйте ещё раз или укажите id")
        if len(found) != 1:
            raise TrustError(f"Человек с ником «{name}» не найден")
        user_id = next(iter(found))
    if user_id <= 0:
        raise TrustError("Нужен id человека")
    return user_id


def peer_ref(raw: str) -> int:
    text = raw.strip().lower().removeprefix("c")
    if not WHOLE_NUMBER.fullmatch(text) or int(text) in (0, GROUP_CHAT_PEER_BASE):
        raise TrustError("Нужна беседа: её peer_id (2000000007) или номер (7)")
    number = int(text)
    return number if number > GROUP_CHAT_PEER_BASE else number + GROUP_CHAT_PEER_BASE


@dataclass(frozen=True)
class UserRow:
    ref: str
    user_id: int | None
    name: str
    missing: bool = False


@dataclass(frozen=True)
class PeerRow:
    peer_id: int
    title: str
    trusted: bool
    left: bool
    note: str
    candidate: bool = False


@dataclass(frozen=True)
class TrustView:
    users: tuple[UserRow, ...]
    peers: tuple[PeerRow, ...]
    vk_error: str = ""


def people(vk, refs) -> list[dict]:
    if not refs:
        return []
    return vk.call("users.get", {"user_ids": ",".join(str(ref) for ref in refs), "fields": "screen_name"})


def full_name(user: dict) -> str:
    return f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()


def chat_states(vk, peer_ids) -> dict[int, tuple[str, bool]]:
    if not peer_ids:
        return {}
    found = vk.call("messages.getConversationsById", {"peer_ids": ",".join(str(peer) for peer in peer_ids)})
    states = {}
    for item in found.get("items") or []:
        chat = item.get("chat_settings") or {}
        states[int(item["peer"]["id"])] = (str(chat.get("title", "")), chat.get("state", "in") != "in")
    return states


def trust_view(lists: TrustLists, vk_factory, candidate: int | None = None) -> TrustView:
    user_ids = [entry for entry in lists.users if isinstance(entry, int)]
    nicks = [entry.lstrip("@") for entry in lists.users if isinstance(entry, str)]
    offered = [candidate] if candidate is not None and is_chat(candidate) and candidate not in lists.peers else []
    peer_ids = list(dict.fromkeys((*offered, *lists.peers, *lists.notes)))
    by_id, by_nick, states, error, asked, nicks_asked = {}, {}, {}, "", False, False
    if lists.users or peer_ids:
        try:
            vk = vk_factory()
            by_id = {int(user["id"]): user for user in people(vk, user_ids)}
            states = chat_states(vk, peer_ids)
            asked = True
        except Exception:
            error = VK_SILENT
    if asked and nicks:
        # ники спрашиваются отдельно: запрос с несуществующим ником не должен оставить страницу без имён и названий
        try:
            by_nick = {str(user.get("screen_name", "")).lower(): user for user in people(vk, nicks)}
            nicks_asked = True
        except Exception:
            error = NICKS_SILENT
    users = []
    for entry in lists.users:
        if isinstance(entry, int):
            users.append(UserRow(str(entry), entry, full_name(by_id.get(entry, {}))))
        else:
            found = by_nick.get(entry.lstrip("@"))
            users.append(UserRow(entry, int(found["id"]) if found else None, full_name(found or {}),
                                 missing=nicks_asked and not found))
    peers = []
    for peer in peer_ids:
        # беседы нет в ответе VK — аккаунт в ней не состоит; без ответа VK судить об этом нельзя
        title, left = states.get(peer, ("", asked))
        peers.append(PeerRow(peer, title, peer in lists.peers, left, lists.notes.get(peer, ""), peer in offered))
    return TrustView(tuple(users), tuple(peers), error)
