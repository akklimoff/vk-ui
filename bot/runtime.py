import json
import random
from dataclasses import asdict, dataclass
from typing import Collection

from common.hotfile import WatchedFile


@dataclass(frozen=True)
class RuntimeSettings:
    active_persona: str = ""
    active_model: str = ""
    peer_personas: tuple[tuple[int, tuple[str, ...]], ...] = ()
    paused: bool = False
    paused_peers: frozenset[int] = frozenset()
    temperature: float = 0.8


def runtime_defaults(settings) -> RuntimeSettings:
    return RuntimeSettings(temperature=settings.llm_temperature)


def parse_peer_personas(raw: dict) -> tuple[tuple[int, tuple[str, ...]], ...]:
    result = []
    for peer, value in raw.items():
        slugs = [value] if isinstance(value, str) else list(value or [])
        slugs = tuple(dict.fromkeys(str(s).strip() for s in slugs if str(s).strip()))
        if slugs:
            result.append((int(peer), slugs))
    return tuple(sorted(result))


def parse_runtime(data: dict, defaults: RuntimeSettings) -> RuntimeSettings:
    def get(key, cast):
        value = data.get(key)
        return getattr(defaults, key) if value is None else cast(value)

    peers = data.get("paused_peers")
    personas = data.get("peer_personas")
    return RuntimeSettings(
        active_persona=get("active_persona", str).strip(),
        active_model=get("active_model", str).strip(),
        peer_personas=defaults.peer_personas if personas is None else parse_peer_personas(personas),
        paused=get("paused", bool),
        paused_peers=defaults.paused_peers if peers is None else frozenset(int(p) for p in peers),
        temperature=get("temperature", float),
    )


def dump_runtime(rt: RuntimeSettings) -> dict:
    data = asdict(rt)
    data["paused_peers"] = sorted(rt.paused_peers)
    data["peer_personas"] = {str(p): slugs[0] if len(slugs) == 1 else list(slugs)
                             for p, slugs in rt.peer_personas}
    return data


def personas_of(rt: RuntimeSettings, peer_id: int) -> tuple[str, ...]:
    return dict(rt.peer_personas).get(peer_id) or ((rt.active_persona,) if rt.active_persona else ())


def persona_for(rt: RuntimeSettings, peer_id: int, pick=random.choice, called: Collection[str] = ()) -> str:
    """Несколько персон на чат — отвечает та, кого позвали по имени, иначе одна из них наугад."""
    slugs = personas_of(rt, peer_id)
    return pick([slug for slug in slugs if slug in called] or slugs) if slugs else ""


class RuntimeFile:
    def __init__(self, path: str, defaults: RuntimeSettings):
        self._file = WatchedFile(
            path,
            parse=lambda text: parse_runtime(json.loads(text), defaults),
            default=defaults,
            log_label="Рантайм-настройки",
        )

    def current(self) -> RuntimeSettings:
        return self._file.current()
