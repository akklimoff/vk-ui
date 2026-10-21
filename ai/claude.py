import json
import re
import time

import httpx

from ai.contract import AgentStep, ToolCall

API_VERSION = "2023-06-01"
# точка кэша: всё от начала запроса до этого блока провайдер запоминает и при повторе считает в разы дешевле
CACHE_POINT = {"type": "ephemeral"}
FINISH = {"end_turn": "stop", "stop_sequence": "stop", "tool_use": "tool_calls", "max_tokens": "length"}
RETRIED = frozenset({408, 409, 429, 500, 502, 503, 504, 529})
EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})
MAX_TEMPERATURE = 1.0
RETRY_PAUSE = 1.0
MAX_RETRY_PAUSE = 10.0
DATA_URL = re.compile(r"data:([\w.+/-]+);base64,(.+)", re.DOTALL)
UNSEEN_IMAGES = "\n\n(к этому сообщению приложены картинки, но ты их не видишь)"


class ClaudeError(RuntimeError):
    pass


def wire_tool(tool) -> dict:
    return {"name": tool.name, "description": tool.description, "input_schema": tool.parameters}


def wire_system(parts) -> list[dict]:
    """Каждая часть системного сообщения — своя точка кэша: правила общие для всех бесед, личность меняется."""
    return [{"type": "text", "text": text, "cache_control": CACHE_POINT} for text in parts if text.strip()]


def wire_picture(url: str) -> dict | None:
    found = DATA_URL.fullmatch(url)
    if found is None:
        return None
    return {"type": "image", "source": {"type": "base64", "media_type": found[1], "data": found[2]}}


def tool_input(arguments: str) -> dict:
    try:
        parsed = json.loads(arguments) if arguments else {}
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def wire_blocks(turn, vision: bool) -> tuple[str, list[dict]]:
    if turn.role == "tool":
        return "user", [{"type": "tool_result", "tool_use_id": turn.tool_call_id, "content": turn.content}]
    text = turn.content
    pictures = [block for block in map(wire_picture, turn.images) if block] if vision else []
    if turn.images and not vision:
        text += UNSEEN_IMAGES
    blocks = [{"type": "text", "text": text}] if text.strip() else []
    calls = [{"type": "tool_use", "id": call.id, "name": call.name, "input": tool_input(call.arguments)}
             for call in turn.tool_calls]
    return turn.role, [*blocks, *pictures, *calls]


def wire_messages(turns, vision: bool = True) -> list[dict]:
    """Ходы в виде Messages API: соседние ходы одной роли склеены (результаты вызовов и картинки к ним — одно
    сообщение user), последний блок — точка кэша, чтобы следующий шаг просьбы не платил за историю заново."""
    messages: list[dict] = []
    for turn in turns:
        role, blocks = wire_blocks(turn, vision)
        if not blocks:
            continue
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"] += blocks
        else:
            messages.append({"role": role, "content": blocks})
    if messages:
        last = messages[-1]["content"]
        last[-1] = {**last[-1], "cache_control": CACHE_POINT}
    return messages


def parse_step(body: dict, model_id: str) -> AgentStep:
    blocks = body.get("content") or ()
    text = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
    calls = tuple(ToolCall(block["id"], block["name"], json.dumps(block.get("input") or {}, ensure_ascii=False))
                  for block in blocks if block.get("type") == "tool_use")
    usage = body.get("usage") or {}
    cached = usage.get("cache_read_input_tokens") or 0
    prompt = (usage.get("input_tokens") or 0) + (usage.get("cache_creation_input_tokens") or 0) + cached
    stop = str(body.get("stop_reason") or "")
    finish = FINISH.get(stop, stop)
    return AgentStep(text.strip(), calls, model_id, prompt, usage.get("output_tokens") or 0,
                     finish == "length", finish, cached_tokens=cached)


def retry_pause(response) -> float:
    try:
        asked = float(response.headers.get("retry-after", ""))
    except ValueError:
        return RETRY_PAUSE
    return min(max(asked, 0.0), MAX_RETRY_PAUSE)


def error_text(response) -> str:
    try:
        return str(response.json()["error"]["message"])
    except (ValueError, KeyError, TypeError):
        return response.text[:300]


class ClaudeApi:
    """Родной Messages API Anthropic: в отличие от OpenAI-совместимого входа он кэширует начало запроса."""

    def __init__(self, api_key: str, base_url: str, timeout: float, workspace_id: str = "", http=None,
                 sleep=time.sleep):
        headers = {"x-api-key": api_key, "anthropic-version": API_VERSION}
        if workspace_id:
            # identity-linked ключи Anthropic требуют указать воркспейс в каждом запросе
            headers["anthropic-workspace-id"] = workspace_id
        self._http = http if http is not None else httpx.Client(timeout=timeout)
        self._headers = headers
        self._sleep = sleep
        self._url = f"{base_url.rstrip('/')}/messages"

    def step(self, model_id: str, system, turns, tools, *, max_tokens: int, effort: str = "",
             temperature: float | None = None, vision: bool = True, thinking: str = "") -> AgentStep:
        body = {"model": model_id, "max_tokens": max_tokens, "system": wire_system(system),
                "messages": wire_messages(turns, vision)}
        if tools:
            body["tools"] = [wire_tool(tool) for tool in tools]
            body["tool_choice"] = {"type": "auto"}
        if effort in EFFORTS:
            body["output_config"] = {"effort": effort}
        if temperature is not None:
            body["temperature"] = min(temperature, MAX_TEMPERATURE)
        if thinking:
            body["thinking"] = {"type": thinking}
        try:
            return parse_step(self._post(body), model_id)
        except (KeyError, TypeError, AttributeError, ValueError):
            raise ClaudeError("Anthropic прислал ответ непонятного вида") from None

    def _post(self, body: dict, retries: int = 1) -> dict:
        try:
            response = self._http.post(self._url, json=body, headers=self._headers)
        except httpx.TransportError as e:
            if retries:
                self._sleep(RETRY_PAUSE)
                return self._post(body, retries - 1)
            raise ClaudeError(f"Anthropic недоступен: {e}") from None
        if response.status_code in RETRIED and retries:
            # повтор сразу же упирается в тот же лимит или перегрузку
            self._sleep(retry_pause(response))
            return self._post(body, retries - 1)
        if response.status_code != 200:
            raise ClaudeError(f"Anthropic ответил {response.status_code}: {error_text(response)}")
        return response.json()
