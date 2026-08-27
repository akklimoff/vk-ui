import os
from dataclasses import dataclass

from bot.access import AccessFile, join_lines, parse_access, scoped_prompts
from bot.context import build_context
from bot.llm import PERSONA_LAYER, PRIVATE_LAYER, SYSTEM_LAYER, USER_LAYER, compose_system_message
from bot.personas import load_persona, persona_path, render_persona
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
    started_at: float | None
    interviews: list[tuple[int, int, int]]


def status_view(state_dir: str, now: float) -> StatusView:
    d = read_json(f"{state_dir}/status.json", {})
    interviews = [(int(peer), int(user), int(iv.get("asked", 0)))
                  for peer, users in read_json(f"{state_dir}/onboarding.json", {}).items()
                  for user, iv in users.items() if not iv.get("done")]

    def ago(ts):
        return None if ts is None else round(now - ts, 1)

    last_event = d.get("last_event_at")
    return StatusView(
        connected=last_event is not None and now - last_event < CONNECTED_WITHIN,
        me_id=d.get("me_id"), me_name=d.get("me_name", ""),
        provider=d.get("provider", ""), model=d.get("model", ""),
        active_persona=d.get("active_persona", ""), paused=bool(d.get("paused")),
        errors_last_hour=int(d.get("errors_last_hour", 0)),
        last_event_ago=ago(last_event), last_reply_ago=ago(d.get("last_reply_at")),
        started_at=d.get("started_at"), interviews=interviews,
    )



def load_runtime_dict(path: str) -> dict:
    return read_json(path, {})


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
    return values


GROUP_CHAT_PEER_BASE = 2_000_000_000


def sandbox_reply(settings, llm, vk, *, persona_slug: str, conversation: str, peer_id: int | None,
                  count: int, asker: str, temperature: float) -> tuple[str, str]:
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
                      temperature=temperature, auto_chat=auto_chat)
    return conversation, reply
