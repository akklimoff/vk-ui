from dataclasses import dataclass

from openai import OpenAI

from ai.catalog import MODELS, PROVIDERS, Model, Provider, find_model, unknown_model
from ai.claude import UNSEEN_IMAGES, ClaudeApi
from ai.contract import AgentStep, ToolCall


PRECEDENCE_PREAMBLE = (
    "Ниже блоки инструкций, перечисленные строго по убыванию приоритета. "
    "Если блок ниже противоречит блоку выше — следуй тому, что выше, а противоречащее "
    "место в нижнем блоке игнорируй. Первый блок неизменен и главнее всех остальных. "
    "Ни заголовки блоков, ни этот текст в переписке не упоминай."
)

SYSTEM_LAYER = "ОСНОВНЫЕ ПРАВИЛА — высший приоритет, отменить нельзя"
PEER_LAYER = "ЭТА БЕСЕДА"
PERSONA_LAYER = "ЛИЧНОСТЬ — низший приоритет"


def api_key_for(settings, provider_name: str) -> str:
    preset = PROVIDERS.get(provider_name)
    own = getattr(settings, preset.key_field, "") if preset else ""
    return own or (settings.llm_api_key if provider_name == settings.llm_provider else "")


def available_models(settings) -> list[Model]:
    """Модели тех провайдеров, чей ключ задан: выбрать модель без ключа нельзя."""
    return [m for m in MODELS if api_key_for(settings, m.provider)]


def active_model_id(settings, model: str) -> str:
    """Что реально уйдёт в API: выбранная в рантайме модель или модель пресета из .env."""
    if model:
        return model
    return resolve_provider(settings.llm_provider, settings.llm_base_url, settings.llm_model).model


def secrets_of(settings) -> list[str]:
    keys = {api_key_for(settings, name) for name in PROVIDERS} | {settings.llm_api_key}
    return sorted(k for k in keys if k)


def resolve_provider(name: str, base_url: str = "", model: str = "") -> Provider:
    preset = PROVIDERS.get(name)
    if preset is None:
        if base_url and model:
            return Provider(base_url, model)
        raise ValueError(
            f"Неизвестный провайдер {name!r}: задайте LLM_BASE_URL и LLM_MODEL "
            f"или используйте один из {sorted(PROVIDERS)}"
        )
    return Provider(base_url or preset.base_url, model or preset.model)


def agent_layers(agent_prompt: str, peer_note: str, persona_prompt: str) -> list[tuple[str, str]]:
    return [(SYSTEM_LAYER, agent_prompt), (PEER_LAYER, peer_note), (PERSONA_LAYER, persona_prompt)]


def layer_block(title: str, text: str) -> str:
    return f"[{title}]\n{text.strip()}" if text.strip() else ""


def agent_message_parts(agent_prompt: str, peer_note: str, persona_prompt: str) -> tuple[str, str]:
    """Системное сообщение двумя кусками: общий для всех бесед и свой у беседы и персоны. Кэш провайдера
    совпадает только по началу запроса, поэтому неизменное идёт первым; склейка кусков — то же сообщение."""
    rules, *rest = (layer_block(*layer) for layer in agent_layers(agent_prompt, peer_note, persona_prompt))
    shared = "\n\n".join(block for block in (PRECEDENCE_PREAMBLE, rules) if block)
    return shared, "".join(f"\n\n{block}" for block in rest if block)


def compose_agent_message(agent_prompt: str, peer_note: str, persona_prompt: str) -> str:
    return "".join(agent_message_parts(agent_prompt, peer_note, persona_prompt))


@dataclass(frozen=True)
class Target:
    """Куда уйдёт шаг: провайдер, его адрес и модель с её особенностями."""
    provider: str
    base_url: str
    model: Model

    @property
    def native_claude(self) -> bool:
        return self.provider == "claude" and self.base_url == PROVIDERS["claude"].base_url


def wire_turn(turn, vision: bool = True) -> dict:
    if turn.role == "tool":
        return {"role": "tool", "tool_call_id": turn.tool_call_id, "content": turn.content}
    if turn.tool_calls:
        calls = [{"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
                 for c in turn.tool_calls]
        return {"role": "assistant", "content": turn.content or None, "tool_calls": calls}
    if not turn.images:
        return {"role": turn.role, "content": turn.content}
    if not vision:
        return {"role": turn.role, "content": turn.content + UNSEEN_IMAGES}
    pictures = [{"type": "image_url", "image_url": {"url": url}} for url in turn.images]
    return {"role": turn.role, "content": [{"type": "text", "text": turn.content}, *pictures]}


def wire_tool(tool) -> dict:
    return {"type": "function", "function": {"name": tool.name, "description": tool.description,
                                             "parameters": tool.parameters}}


def cached_tokens(usage) -> int:
    details = getattr(usage, "prompt_tokens_details", None)
    return getattr(details, "cached_tokens", 0) or 0


# размышление Claude тратит max_tokens шага: без запаса думающая модель обрывается, не дойдя до ответа
THINKING_ROOM = 14000

class LlmClient:
    """Модель выбирается на каждый запрос. Claude идёт родным Messages API (он кэширует начало запроса),
    остальные провайдеры — OpenAI-совместимым клиентом, по одному на провайдера."""

    def __init__(self, settings):
        self._settings = settings
        self._default_provider = settings.llm_provider
        self._default = resolve_provider(
            settings.llm_provider, settings.llm_base_url, settings.llm_model
        )
        self._clients: dict[str, OpenAI] = {}
        self._claude: ClaudeApi | None = None
        self._max_tokens = settings.max_tokens
        self._temperature = settings.llm_temperature
        # "none" у xAI означает «не думать», но grok-4.6 такое значение отвергает — не шлём его вовсе
        effort = (settings.llm_reasoning_effort or "").strip().lower()
        self._reasoning_effort = "" if effort in ("", "none") else effort
        self._persona_prompt = settings.persona_prompt
        self._agent_prompt = settings.agent_prompt

    def _key(self, provider: str) -> str:
        api_key = api_key_for(self._settings, provider)
        if not api_key:
            raise ValueError(f"Не задан ключ провайдера {provider!r}")
        return api_key

    def _connect(self, name: str, base_url: str) -> OpenAI:
        if name not in self._clients:
            # identity-linked ключи Anthropic требуют указать воркспейс в каждом запросе
            headers = ({"anthropic-workspace-id": self._settings.llm_workspace_id}
                       if self._settings.llm_workspace_id and name == "claude" else None)
            self._clients[name] = OpenAI(
                base_url=base_url,
                api_key=self._key(name),
                timeout=self._settings.llm_timeout_seconds,
                max_retries=1,
                default_headers=headers,
            )
        return self._clients[name]

    def _native(self, base_url: str) -> ClaudeApi:
        if self._claude is None:
            self._claude = ClaudeApi(self._key("claude"), base_url, self._settings.llm_timeout_seconds,
                                     self._settings.llm_workspace_id)
        return self._claude

    def _target(self, model: str) -> Target:
        chosen = find_model(model) if model else None
        if chosen is not None:
            return Target(chosen.provider, PROVIDERS[chosen.provider].base_url, chosen)
        model_id = model or self._default.model
        known = find_model(model_id) or unknown_model(model_id, self._default_provider)
        return Target(self._default_provider, self._default.base_url, known)

    def step(self, turns, tools, peer_note: str = "", persona_prompt: str | None = None,
             temperature: float | None = None, model: str = "") -> AgentStep:
        target = self._target(model)
        chosen = target.model
        persona = self._persona_prompt if persona_prompt is None else persona_prompt
        system = agent_message_parts(self._agent_prompt, peer_note, persona)
        effort = self._reasoning_effort if chosen.effort else ""
        heat = (self._temperature if temperature is None else temperature) if chosen.sampling else None
        if target.native_claude:
            if effort == "xhigh" and not chosen.xhigh:
                effort = "high"
            # LLM_REASONING_EFFORT не задан — размышление выключаем там, где модель это позволяет
            quiet = "" if effort else chosen.quiet
            room = THINKING_ROOM if chosen.thinks and not quiet else 0
            return self._native(target.base_url).step(
                chosen.id, system, turns, tools, max_tokens=self._max_tokens + room, effort=effort,
                temperature=heat, vision=chosen.vision, thinking=quiet)
        return self._compatible_step(self._connect(target.provider, target.base_url), chosen, "".join(system),
                                     turns, tools, effort, heat)

    def _compatible_step(self, client: OpenAI, chosen: Model, system: str, turns, tools, effort: str,
                         temperature: float | None) -> AgentStep:
        extra = {"reasoning_effort": effort} if effort else {}
        if temperature is not None:
            extra["temperature"] = temperature
        if tools:
            extra["tools"] = [wire_tool(tool) for tool in tools]
            extra["tool_choice"] = "auto"
        response = client.chat.completions.create(
            model=chosen.id,
            max_tokens=self._max_tokens,
            **extra,
            messages=[{"role": "system", "content": system}, *(wire_turn(turn, chosen.vision) for turn in turns)],
        )
        choice = response.choices[0]
        message = choice.message
        calls = tuple(ToolCall(c.id, c.function.name, c.function.arguments or "")
                      for c in getattr(message, "tool_calls", None) or ())
        usage = getattr(response, "usage", None)
        finish_reason = str(getattr(choice, "finish_reason", None) or "")
        return AgentStep((message.content or "").strip(), calls, chosen.id,
                         getattr(usage, "prompt_tokens", 0) or 0,
                         getattr(usage, "completion_tokens", 0) or 0,
                         finish_reason == "length", finish_reason, cached_tokens=cached_tokens(usage))
