import os
from dataclasses import dataclass

from bot.access import AccessFile, join_lines, parse_access, scoped_prompts
from bot.config import parse_ids
from bot.context import build_context
from ai.llm import (PERSONA_LAYER, PRIVATE_LAYER, PROVIDERS, SYSTEM_LAYER, USER_LAYER,
                     available_models, compose_system_message, find_model, resolve_provider)
from ai.personas import load_persona, persona_path, render_persona
from bot.status import read_json, write_json_atomic

CONNECTED_WITHIN = 90.0


@dataclass(frozen=True)
class StatusView:
    connected: bool
    me_id: int | None
    me_name: str
    provider: str
    model: str
    active_persona: str
    paused: bool
    errors_last_hour: int
    last_event_ago: float | None
    last_reply_ago: float | None
    uptime: float | None
    interviews: list[tuple[int, int, int]]


def status_view(state_dir: str, now: float, runtime: dict | None = None) -> StatusView:
    """`runtime` — желаемое состояние из runtime.json; status.json отстаёт от него на flush бота."""
    d = read_json(f"{state_dir}/status.json", {})
    desired = d if runtime is None else runtime
    interviews = [(int(peer), int(user), int(iv.get("asked", 0)))
                  for peer, users in read_json(f"{state_dir}/onboarding.json", {}).items()
                  for user, iv in users.items() if not iv.get("done")]

    def ago(ts):
        return None if ts is None else round(now - ts, 1)

    last_event = d.get("last_event_at")
    chosen = find_model(desired.get("active_model", ""))
    return StatusView(
        connected=last_event is not None and now - last_event < CONNECTED_WITHIN,
        me_id=d.get("me_id"), me_name=d.get("me_name", ""),
        provider=chosen.provider if chosen else d.get("provider", ""),
        model=chosen.label if chosen else d.get("model", ""),
        active_persona=desired.get("active_persona", ""), paused=bool(desired.get("paused")),
        errors_last_hour=int(d.get("errors_last_hour", 0)),
        last_event_ago=ago(last_event), last_reply_ago=ago(d.get("last_reply_at")),
        uptime=ago(d.get("started_at")), interviews=interviews,
    )


def load_runtime_dict(path: str) -> dict:
    return read_json(path, {})


RUNTIME_FORM_FIELDS = {
    "temperature": ("Температура", float),
    "reply_delay_min": ("Задержка ответа от", float),
    "reply_delay_max": ("Задержка ответа до", float),
    "context_messages": ("Сообщений контекста", int),
    "dm_debounce_seconds": ("Пауза перед ответом в личке", float),
}


def runtime_form_values(rt) -> dict[str, str]:
    values = {field: str(getattr(rt, field)) for field in RUNTIME_FORM_FIELDS}
    values["paused_peers"] = ", ".join(str(p) for p in sorted(rt.paused_peers))
    values["active_model"] = rt.active_model
    return values


def parse_runtime_form(form: dict, allowed_models=()) -> dict:
    data = {}
    for field, (title, cast) in RUNTIME_FORM_FIELDS.items():
        raw = (form.get(field) or "").strip()
        try:
            data[field] = cast(raw)
        except ValueError:
            raise ValueError(f"{title}: нужно число, а не «{raw}»") from None
    model = (form.get("active_model") or "").strip()
    if model and model not in allowed_models:
        raise ValueError(f"Модель: «{model}» недоступна, проверьте ключ провайдера в .env")
    data["active_model"] = model
    try:
        data["paused_peers"] = sorted(parse_ids(form.get("paused_peers", "")))
    except ValueError:
        raise ValueError("Чаты на паузе: peer_id через запятую") from None
    return data


def model_groups(settings) -> list[tuple[str, list]]:
    """Модели для выпадающего списка, сгруппированные по провайдеру."""
    groups: dict[str, list] = {}
    for model in available_models(settings):
        groups.setdefault(model.provider, []).append(model)
    return [(PROVIDERS[name].label or name, models) for name, models in groups.items()]


def model_label(model_id: str) -> str:
    found = find_model(model_id)
    return found.label if found else model_id


def default_model_label(settings) -> str:
    try:
        return resolve_provider(settings.llm_provider, settings.llm_base_url, settings.llm_model).model
    except ValueError:
        return settings.llm_model or settings.llm_provider


def save_runtime_patch(path: str, **fields) -> None:
    data = load_runtime_dict(path)
    data.update(fields)
    write_json_atomic(path, data)


def save_persona(personas_dir: str, slug: str, name: str, prompt: str) -> None:
    path = persona_path(personas_dir, slug)
    os.makedirs(personas_dir, exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(render_persona(name, prompt))
    os.replace(tmp, path)


@dataclass(frozen=True)
class PromptView:
    persona_slug: str
    persona_name: str
    user_key: str | None
    message: str
    layers: list[tuple[str, str]]


def access_raw(path: str) -> dict:
    return read_json(path, {})


def prompt_view(settings, user_key: str | None) -> PromptView:
    slug = load_runtime_dict(settings.runtime_file).get("active_persona", "")
    persona = load_persona(settings.personas_dir, slug) if slug else None
    persona_name = persona.name if persona else "по умолчанию"
    persona_prompt = persona.prompt if persona else settings.persona_prompt
    raw = access_raw(settings.access_file)
    user_prompt = join_lines((raw.get("user_prompts") or {}).get(user_key)) if user_key else ""
    private_prompt = join_lines(raw.get("private_prompt")) if user_key else ""
    layers = [(SYSTEM_LAYER, settings.system_prompt), (USER_LAYER, user_prompt),
              (PRIVATE_LAYER, private_prompt), (PERSONA_LAYER, persona_prompt)]
    return PromptView(
        persona_slug=slug, persona_name=persona_name, user_key=user_key,
        message=compose_system_message(settings.system_prompt, user_prompt, private_prompt, persona_prompt),
        layers=[(t, x.strip()) for t, x in layers if x.strip()],
    )


ACCESS_LIST_FIELDS = ("blocked_users", "blocked_peers", "allowed_peers", "auto_reply_users",
                      "auto_reply_peers", "onboarding_peers")


def _lines(text: str) -> list[str]:
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


def _keyed_prompts(field: str, text: str) -> dict:
    prompts = {}
    for line in _lines(text):
        key, sep, value = line.partition(":")
        if not sep or not key.strip():
            raise ValueError(f"Строка {field} без «ключ: текст»: {line!r}")
        prompts[key.strip()] = value.strip()
    return prompts


def parse_access_form(form: dict) -> dict:
    data = {field: _lines(form.get(field, "")) for field in ACCESS_LIST_FIELDS}
    data["private_prompt"] = _lines(form.get("private_prompt", ""))
    data["user_prompts"] = _keyed_prompts("user_prompts", form.get("user_prompts", ""))
    data["chat_prompt"] = _lines(form.get("chat_prompt", ""))
    data["peer_prompts"] = _keyed_prompts("peer_prompts", form.get("peer_prompts", ""))
    data["peer_blocked_users"] = {k: v.replace(",", " ").split()
                                  for k, v in _keyed_prompts("peer_blocked_users",
                                                             form.get("peer_blocked_users", "")).items()}
    try:
        parse_access(data, resolve_screen_names=lambda names: frozenset())
    except Exception as e:
        raise ValueError(f"Некорректные значения: {e}") from e
    return data


def access_form_values(path: str) -> dict:
    raw = access_raw(path)
    values = {field: "\n".join(str(x) for x in raw.get(field) or []) for field in ACCESS_LIST_FIELDS}
    values["private_prompt"] = join_lines(raw.get("private_prompt"))
    values["user_prompts"] = "\n".join(f"{k}: {join_lines(v)}" for k, v in (raw.get("user_prompts") or {}).items())
    values["chat_prompt"] = join_lines(raw.get("chat_prompt"))
    values["peer_prompts"] = "\n".join(f"{k}: {join_lines(v)}" for k, v in (raw.get("peer_prompts") or {}).items())
    values["peer_blocked_users"] = "\n".join(f"{k}: {' '.join(str(x) for x in v or [])}"
                                              for k, v in (raw.get("peer_blocked_users") or {}).items())
    return values


GROUP_CHAT_PEER_BASE = 2_000_000_000


def peer_label(peer_id: int) -> str:
    return f"беседа {peer_id - GROUP_CHAT_PEER_BASE}" if peer_id >= GROUP_CHAT_PEER_BASE else f"id{peer_id}"


def peer_link(peer_id: int) -> str:
    sel = f"c{peer_id - GROUP_CHAT_PEER_BASE}" if peer_id >= GROUP_CHAT_PEER_BASE else str(peer_id)
    return f"https://vk.com/im?sel={sel}"


def sandbox_reply(settings, llm, vk, *, persona_slug: str, conversation: str, peer_id: int | None,
                  count: int, asker: str, temperature: float, model: str = "") -> tuple[str, str]:
    persona = load_persona(settings.personas_dir, persona_slug) if persona_slug else None
    persona_prompt = persona.prompt if persona else settings.persona_prompt
    is_private, auto_chat, general_prompt, specific_prompt = False, False, "", ""
    if peer_id is not None:
        history = vk.history(peer_id, count)
        conversation = build_context(history, vk.resolve_name, settings.message_char_limit,
                                     settings.context_char_budget, vk.me_id)
        is_private = peer_id < GROUP_CHAT_PEER_BASE
        lists = AccessFile(settings.access_file, vk.resolve_screen_names).current()
        general_prompt, specific_prompt = scoped_prompts(lists, peer_id, is_private)
        auto_chat = peer_id in lists.auto_reply_peers or peer_id in lists.onboarding_peers
    reply = llm.reply(conversation, asker, is_private=is_private, private_prompt=general_prompt,
                      user_prompt=specific_prompt, persona_prompt=persona_prompt,
                      temperature=temperature, auto_chat=auto_chat, model=model)
    return conversation, reply
