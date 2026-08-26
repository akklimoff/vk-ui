import os
from dataclasses import dataclass

from bot.access import join_lines
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


def status_view(state_dir: str, now: float) -> StatusView:
    d = read_json(f"{state_dir}/status.json", {})

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
        started_at=d.get("started_at"),
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
