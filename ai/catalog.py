from dataclasses import dataclass


@dataclass(frozen=True)
class Provider:
    base_url: str
    model: str
    key_field: str = "llm_api_key"
    label: str = ""


@dataclass(frozen=True)
class Model:
    id: str
    label: str
    provider: str
    # Claude 5 отвечает 400 «temperature is deprecated for this model»
    sampling: bool = True
    vision: bool = True
    # Haiku 4.5 отвечает 400 «This model does not support the effort parameter»
    effort: bool = True
    # Sonnet 4.6 уровня xhigh не знает
    xhigh: bool = True
    # думает, даже когда об этом не просили: размышление расходует тот же max_tokens, что и ответ
    thinks: bool = False
    # значение thinking.type, которым у модели выключается размышление; пусто — выключить нельзя
    quiet: str = ""


PROVIDERS = {
    "grok": Provider("https://api.x.ai/v1", "grok-4.3", "xai_api_key", "Grok"),
    "openai": Provider("https://api.openai.com/v1", "gpt-5-mini", "openai_api_key", "OpenAI"),
    "deepseek": Provider("https://api.deepseek.com/v1", "deepseek-chat", "deepseek_api_key", "DeepSeek"),
    "kimi": Provider("https://api.moonshot.ai/v1", "kimi-k2-turbo-preview", "moonshot_api_key", "Kimi"),
    "claude": Provider("https://api.anthropic.com/v1", "claude-sonnet-5-5", "anthropic_api_key", "Claude"),
}

MODELS = (
    Model("grok-4.6", "Grok 4.6", "grok"),
    Model("grok-4.5", "Grok 4.5", "grok"),
    Model("grok-4.3", "Grok 4.3", "grok"),
    Model("claude-opus-5-5", "Claude Opus 5.5", "claude", sampling=False, thinks=True),
    # без размышления Opus 5 порой пишет вызов инструмента текстом, и тот не исполняется — не выключаем
    Model("claude-opus-5", "Claude Opus 5", "claude", sampling=False, thinks=True),
    Model("claude-sonnet-5-5", "Claude Sonnet 5.5", "claude", sampling=False, thinks=True, quiet="between_tools"),
    Model("claude-sonnet-5", "Claude Sonnet 5", "claude", sampling=False, thinks=True, quiet="disabled"),
    Model("claude-fable-5-1", "Claude Fable 5.1", "claude", sampling=False, thinks=True),
    Model("claude-haiku-5-5", "Claude Haiku 5.5", "claude", sampling=False, thinks=True, quiet="disabled"),
    Model("claude-sonnet-4-6", "Claude Sonnet 4.6", "claude", xhigh=False),
    Model("claude-haiku-4-5-20251001", "Claude Haiku 4.5", "claude", effort=False),
)


def find_model(model_id: str) -> Model | None:
    return next((m for m in MODELS if m.id == model_id), None)


def unknown_model(model_id: str, provider: str) -> Model:
    """О модели не из каталога известно только имя. Картинки ей не шлём, чтобы не получить отказ на весь шаг;
    новые Claude отвергают temperature и думают по умолчанию — считаем такой и незнакомую."""
    claude = model_id.startswith("claude-")
    return Model(model_id, model_id, provider, vision=False, sampling=not claude, thinks=claude)
