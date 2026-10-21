import json

from ai.contract import ToolSpec
from bot.agent.gate import CHAT, Caller
from bot.agent.methods import METHODS, Method

TOOL_NAME = "vk_api"
PARAMETERS = {
    "type": "object",
    "properties": {
        "method": {"type": "string", "description": "имя метода VK API, например messages.getHistory"},
        "params": {"type": "object", "description": "параметры метода"},
    },
    "required": ["method"],
}
HEADER = "Вызвать метод VK API от имени аккаунта."
SCOPE = ("Доступен любой метод VK API, кроме запрещённых: вся страница целиком — все диалоги и беседы, друзья, "
         "стена, фото, лайки, комментарии, сообщества, профиль. Ниже частые методы; остальные вызывай по именам "
         "из документации VK API, с её же параметрами.")
IDS = ("Адреса: peer_id человека — его id, сообщества — id с минусом, беседы — 2000000000 + chat_id. id человека "
       "бери из списка участников, по нику (utils.resolveScreenName) или поиском по имени (users.search, "
       "friends.search); другую беседу по названию ищи через messages.searchConversations.")
CHAT_SCOPE = ("Ты в беседе: если в вызове не назван peer_id (или chat_id), подставится эта беседа; с peer_id человека "
              "— личный диалог аккаунта с ним, с peer_id другой беседы — она.")
SAVED_SCOPE = "Ты в «Избранном»: peer_id и chat_id называй всегда сама."
BAD_JSON = "аргументы должны быть JSON-объектом с полями method и params"
BAD_METHOD = "нужно строковое поле method"
BAD_PARAMS = "params должен быть объектом"


def signature(method: Method) -> str:
    address = {method.peer_param, method.chat_param} - {""}
    line = f"- {method.name}({', '.join(sorted(method.params | address))})"
    hint = method.note or method.title
    return f"{line} — {hint}" if hint else line


def describe(caller: Caller) -> ToolSpec:
    place = CHAT_SCOPE if caller.place == CHAT else SAVED_SCOPE
    lines = [HEADER, SCOPE, IDS, place, *(signature(method) for method in METHODS)]
    return ToolSpec(TOOL_NAME, "\n".join(lines), PARAMETERS)


def parse_call(arguments: str) -> tuple[str, dict] | str:
    try:
        data = json.loads(arguments or "")
    except ValueError:
        return BAD_JSON
    if not isinstance(data, dict):
        return BAD_JSON
    if not isinstance(data.get("method"), str):
        return BAD_METHOD
    params = data.get("params")
    if isinstance(params, str):
        try:
            params = json.loads(params)
        except ValueError:
            return BAD_PARAMS
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return BAD_PARAMS
    return data["method"], params
