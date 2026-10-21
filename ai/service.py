from dataclasses import replace

from ai.contract import AgentRequest, AgentStep, ModelInfo, SystemPreview
from ai.leak import LeakGuard, outgoing
from ai.llm import (PROVIDERS, LlmClient, active_model_id, agent_layers, available_models, compose_agent_message,
                    secrets_of)
from ai.personas import PersonaFile
from common.redact import sanitize_reply


def withheld(step: AgentStep) -> AgentStep:
    """Шаг, пересказавший инструкции, отдаётся без текста и аргументов: дальше ИИ-сервиса они не уходят."""
    calls = tuple(replace(call, arguments="{}") for call in step.tool_calls)
    return replace(step, text="", tool_calls=calls, leaked=True)


class AiService:
    """Вход в ИИ-часть: ходы агента и описание инструмента на входе, шаг модели на выходе.
    Про VK не знает: разметку тегов и VK-токен чистит вызывающая сторона."""

    def __init__(self, settings, llm=None):
        self._settings = settings
        self._llm = llm if llm is not None else LlmClient(settings)
        self._personas: dict[str, PersonaFile] = {}

    def step(self, req: AgentRequest) -> AgentStep:
        persona = self.persona_prompt(req.persona)
        step = self._llm.step(req.turns, req.tools, peer_note=req.scope_prompt, persona_prompt=persona,
                              temperature=req.temperature, model=req.model)
        step = replace(step, text=self.scrub(step.text))
        rules = (compose_agent_message(self._settings.agent_prompt, req.scope_prompt, ""),
                 *(tool.description for tool in req.tools))
        guard = LeakGuard(rules, req.scope_prompt, persona)
        if any(guard.catches(text) for text in outgoing(step)):
            return withheld(step)
        return step

    def persona_prompt(self, slug: str) -> str:
        if not slug:
            return self._settings.persona_prompt
        if slug not in self._personas:
            self._personas[slug] = PersonaFile(self._settings.personas_dir, slug, self._settings.persona_prompt)
        return self._personas[slug].current()

    def agent_preview(self, persona: str, peer_note: str = "") -> SystemPreview:
        args = (self._settings.agent_prompt, peer_note, self.persona_prompt(persona))
        layers = tuple((title, text.strip()) for title, text in agent_layers(*args) if text.strip())
        return SystemPreview(compose_agent_message(*args), layers)

    def models(self) -> list[ModelInfo]:
        return [ModelInfo(m.id, m.label, m.provider, PROVIDERS[m.provider].label or m.provider)
                for m in available_models(self._settings)]

    def model_id(self, model: str = "") -> str:
        return active_model_id(self._settings, model)

    def scrub(self, text: str) -> str:
        return sanitize_reply(text, secrets_of(self._settings))
