import os
from dataclasses import dataclass

from bot.personas import persona_path, render_persona
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
