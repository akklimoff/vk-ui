import os
import re
from dataclasses import dataclass

from common.hotfile import WatchedFile

SLUG_RE = re.compile(r"^[a-z0-9_-]{1,40}$")


@dataclass(frozen=True)
class Persona:
    slug: str
    name: str
    prompt: str


def parse_persona(slug: str, text: str) -> Persona:
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("# "):
        return Persona(slug, lines[0][2:].strip(), "\n".join(lines[1:]).strip())
    return Persona(slug, slug, text.strip())


def render_persona(name: str, prompt: str) -> str:
    return f"# {name.strip()}\n\n{prompt.strip()}\n"


def persona_path(personas_dir: str, slug: str) -> str:
    if not SLUG_RE.match(slug):
        raise ValueError(f"Недопустимый slug персоны: {slug!r}")
    return os.path.join(personas_dir, f"{slug}.md")


def list_personas(personas_dir: str) -> list[Persona]:
    try:
        names = sorted(os.listdir(personas_dir))
    except OSError:
        return []
    personas = []
    for name in names:
        slug, ext = os.path.splitext(name)
        if ext == ".md" and SLUG_RE.match(slug):
            with open(os.path.join(personas_dir, name), encoding="utf-8") as f:
                personas.append(parse_persona(slug, f.read()))
    return personas


def load_persona(personas_dir: str, slug: str) -> Persona | None:
    try:
        with open(persona_path(personas_dir, slug), encoding="utf-8") as f:
            return parse_persona(slug, f.read())
    except (OSError, ValueError):
        return None


class PersonaFile:
    def __init__(self, personas_dir: str, slug: str, fallback_prompt: str):
        path = persona_path(personas_dir, slug) if SLUG_RE.match(slug) else os.path.join(personas_dir, "_.md")
        self._file = WatchedFile(
            path,
            parse=lambda text: parse_persona(slug, text).prompt,
            default=fallback_prompt,
            log_label=f"Персона {slug}",
        )

    def current(self) -> str:
        return self._file.current()
