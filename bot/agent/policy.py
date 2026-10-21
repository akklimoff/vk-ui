from dataclasses import dataclass

from bot.agent.gate import CHAT, GROUP_CHAT_PEER_BASE, Caller
from bot.agent.methods import (METHOD_NAME, OUTWARD, READ, UNLISTED, WRITE_HERE, Method, action_title, denied,
                               find_method, reads_by_name)
from bot.agent.pictures import is_photo_url
from bot.reply import deliverable
from bot.wire import wire_json, wire_value
from common.redact import sanitize_reply

# vk_api подставляет свой токен и версию, только если их нет в параметрах: переданные моделью подменили бы их
FORBIDDEN_PARAMS = frozenset({"access_token", "v"})
TEXT_PARAM = "message"
FALSY = frozenset({"", "0", "false", "none", "null"})
UPLOAD_PARAM = "from_url"
FOREIGN_PICTURE = "from_url — только адрес картинки из ВКонтакте: url фото из вложения, альбома или профиля"
ADDRESSING = frozenset({"peer_id", "peer_ids", "user_id", "user_ids", "chat_id", "domain"})


@dataclass(frozen=True)
class Allow:
    method: str
    params: dict
    kind: str


@dataclass(frozen=True)
class Confirm:
    method: str
    params: dict
    kind: str
    title: str


@dataclass(frozen=True)
class Refuse:
    reason: str


def truthy(value) -> bool:
    return str(value).strip().lower() not in FALSY


def same_peer(value, peer_id: int) -> bool:
    return str(value).strip() == str(peer_id)


def addressed_here(row: Method, params: dict, peer_id: int) -> dict:
    """В беседе вызов без адреса относится к ней самой; названный адрес остаётся как есть."""
    if row.peer_param and not ADDRESSING & set(params):
        return {**params, row.peer_param: peer_id}
    if row.chat_param and row.chat_param not in params:
        return {**params, row.chat_param: peer_id - GROUP_CHAT_PEER_BASE}
    return params


def kind_of(row: Method | None, method: str, params: dict, here: int) -> str:
    if row is None:
        return READ if reads_by_name(method) else UNLISTED
    if row.kind != WRITE_HERE or not row.peer_param:
        return row.kind
    # «сюда» должно быть доказано: единственный адресат — место просьбы; другая переписка или второй адресат
    # (user_id, domain, chat_id) — уже «наружу», и запачканный запрос в «Избранном» спросит «да»
    given = params.get(row.peer_param)
    alone = not (ADDRESSING & set(params)) - {row.peer_param}
    here_only = given is not None and same_peer(given, here) and alone
    return row.kind if here_only else row.elsewhere or OUTWARD


def wired(row: Method | None, params: dict) -> dict:
    # проверки, чистка текста, вопрос «да» и журнал должны видеть ровно то, что уйдёт в VK:
    # текст списком или объектом иначе прошёл бы мимо чистки и собрался бы в строку уже после неё
    as_json = row.json_params if row else frozenset()
    return {name: wire_json(value) if name in as_json else wire_value(value) for name, value in params.items()}


def escalated(row: Method | None, params: dict, kind: str) -> tuple[dict, str]:
    if row is None:
        return params, kind
    for name, higher in row.escalate.items():
        if name in params and truthy(params[name]):
            return params, higher
    # выключенный флаг не отправляем: «false» строкой VK мог бы прочитать как включённый
    return {name: value for name, value in params.items() if name not in row.escalate}, kind


def cleaned(params: dict, secrets, me_id: int) -> dict:
    result = {}
    for name, value in params.items():
        if isinstance(value, str):
            value = sanitize_reply(value, secrets)
            if name == TEXT_PARAM:
                value = "".join(deliverable([value], secrets, me_id))
        result[name] = value
    return result


def needs_yes(place: str, kind: str, tainted: bool) -> bool:
    # в беседе «да» не спрашивается ни у кого (решение владельца, 2026-10-06); в «Избранном» вопрос остаётся
    if place == CHAT or kind in (READ, WRITE_HERE):
        return False
    return kind != OUTWARD or tainted


def judge(method, params: dict, caller: Caller, peer_id: int, me_id: int, tainted: bool,
          secrets=()) -> Allow | Confirm | Refuse:
    if not isinstance(method, str) or not METHOD_NAME.fullmatch(method):
        return Refuse("нет такого метода")
    if denied(method):
        return Refuse("это запрещено")
    if FORBIDDEN_PARAMS & {str(name).strip().lower() for name in params}:
        return Refuse("параметры access_token и v передавать нельзя")
    # по этому адресу бот сам скачает файл: чужой адрес увёл бы его во внутреннюю сеть
    if UPLOAD_PARAM in params and not is_photo_url(params[UPLOAD_PARAM]):
        return Refuse(FOREIGN_PICTURE)
    row = find_method(method)
    params = wired(row, params)
    if caller.place == CHAT and row is not None:
        params = addressed_here(row, params, peer_id)
    here = peer_id if caller.place == CHAT else me_id
    params, kind = escalated(row, params, kind_of(row, method, params, here))
    name = row.name if row else method
    params = cleaned(params, secrets, me_id)
    if needs_yes(caller.place, kind, tainted):
        return Confirm(name, params, kind, action_title(name))
    return Allow(name, params, kind)
