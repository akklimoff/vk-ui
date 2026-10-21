import re
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class SystemPreview:
    message: str
    layers: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ModelInfo:
    id: str
    label: str
    provider: str
    provider_label: str


def dump(obj) -> dict:
    return asdict(obj)


def load_preview(raw: dict) -> SystemPreview:
    return SystemPreview(raw["message"], tuple((title, text) for title, text in raw["layers"]))


def load_model(raw: dict) -> ModelInfo:
    return ModelInfo(**raw)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class Turn:
    role: str
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str = ""
    # картинки к ходу пользователя: data-URL, чтобы провайдеру не пришлось ходить за ними самому
    images: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentRequest:
    turns: tuple[Turn, ...]
    tools: tuple[ToolSpec, ...] = ()
    persona: str = ""
    scope_prompt: str = ""
    model: str = ""
    temperature: float | None = None


# остатки разметки вызова, которые модель иногда пишет прямо в текст ответа: теги разных диалектов,
# в том числе с префиксами вида «ns:», и служебные токены вида <|…|>
TOOL_MARKUP = re.compile(
    r"</?(?:[a-z][\w.-]*:)*"
    r"(?:invoke|parameter|arguments|function(?:[_-](?:calls?|results?))?|tool[_-](?:calls?|use|results?))(?![\w-])"
    r"|<\|[\w-]+\|>|\[TOOL_CALLS\]",
    re.IGNORECASE)


NORMAL_FINISH = frozenset({"", "stop", "tool_calls", "function_call", "length"})


@dataclass(frozen=True)
class AgentStep:
    text: str
    tool_calls: tuple[ToolCall, ...] = ()
    model_id: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    # ответ упёрся в лимит токенов: текст или аргументы последнего вызова оборваны
    truncated: bool = False
    finish_reason: str = ""
    # шаг дословно повторял инструкции модели: его текст и аргументы вызовов изъяты, исполнять нечего
    leaked: bool = False
    # сколько из prompt_tokens провайдер взял из кэша
    cached_tokens: int = 0

    @property
    def abnormal(self) -> bool:
        """Провайдер оборвал ответ сам (фильтр, сбой): ни текст, ни вызовы такого шага использовать нельзя."""
        return self.finish_reason not in NORMAL_FINISH

    @property
    def malformed(self) -> bool:
        """Вызов инструмента пришёл текстом, а не полем tool_calls: такой текст — не ответ, показывать его нельзя."""
        return not self.tool_calls and TOOL_MARKUP.search(self.text) is not None


def load_calls(raw) -> tuple[ToolCall, ...]:
    return tuple(ToolCall(c["id"], c["name"], c.get("arguments", "")) for c in raw or ())


def load_agent_request(raw: dict) -> AgentRequest:
    turns = tuple(Turn(t["role"], t.get("content", ""), load_calls(t.get("tool_calls")), t.get("tool_call_id", ""),
                       tuple(t.get("images") or ()))
                  for t in raw.get("turns", ()))
    tools = tuple(ToolSpec(t["name"], t.get("description", ""), t.get("parameters", {}))
                  for t in raw.get("tools", ()))
    return AgentRequest(turns, tools, raw.get("persona", ""), raw.get("scope_prompt", ""),
                        raw.get("model", ""), raw.get("temperature"))


def load_step(raw: dict) -> AgentStep:
    return AgentStep(raw["text"], load_calls(raw.get("tool_calls")), raw.get("model_id", ""),
                     raw.get("prompt_tokens", 0), raw.get("completion_tokens", 0), bool(raw.get("truncated", False)),
                     str(raw.get("finish_reason") or ""), bool(raw.get("leaked", False)),
                     raw.get("cached_tokens", 0))
