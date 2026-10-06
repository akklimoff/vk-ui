from dataclasses import dataclass

from ai.personas import load_persona
from bot.runtime import parse_runtime, runtime_defaults
from web import trust
from web.services import load_runtime_dict


@dataclass(frozen=True)
class PromptView:
    persona_slug: str
    persona_name: str
    peer_id: int | None
    note: str
    message: str
    layers: list[tuple[str, str]]


def trusted(settings) -> trust.TrustLists:
    try:
        return trust.load(settings.access_file)
    except ValueError:
        return trust.TrustLists()


def prompt_peers(settings) -> list[int]:
    lists = trusted(settings)
    return sorted({*lists.peers, *lists.notes})


def persona_slug(settings, peer_id: int | None) -> str:
    try:
        rt = parse_runtime(load_runtime_dict(settings.runtime_file), runtime_defaults(settings))
    except (AttributeError, TypeError, ValueError):
        return ""
    # у беседы может быть несколько персон, бот берёт случайную; для предпросмотра хватит первой
    slugs = dict(rt.peer_personas).get(peer_id) if peer_id is not None else None
    return slugs[0] if slugs else rt.active_persona


def prompt_view(settings, ai, peer_id: int | None) -> PromptView:
    note = trusted(settings).notes.get(peer_id, "") if peer_id is not None else ""
    slug = persona_slug(settings, peer_id)
    persona = load_persona(settings.personas_dir, slug) if slug else None
    preview = ai.agent_preview(slug, note)
    return PromptView(slug, persona.name if persona else "по умолчанию", peer_id, note, preview.message,
                      list(preview.layers))
