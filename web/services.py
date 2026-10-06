import json
import os
from dataclasses import dataclass

from ai.catalog import find_model
from ai.personas import load_persona, persona_path, render_persona
from ai.contract import ReplyRequest
from bot.access import AccessFile, join_lines, legacy_lists, parse_access, scoped_prompts
from bot.config import parse_ids
from bot.context import to_lines
from bot.reply import deliverable
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


def _object_or_empty(path: str) -> dict:
    data = read_json(path, {})
    return data if isinstance(data, dict) else {}


def load_runtime_dict(path: str) -> dict:
    return _object_or_empty(path)


class BrokenConfig(ValueError):
    """Файл настроек есть, но не разбирается: писать поверх него нельзя."""


def read_config_for_update(path: str) -> dict:
    """Чтение перед записью: нет файла — пустые настройки, а испорченный файл не должен сойти за пустой."""
    name = os.path.basename(path)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise BrokenConfig(f"{name} не читается ({e}). Исправьте файл вручную: сохранение отменено, "
                           f"чтобы не затереть его содержимое") from e
    if not isinstance(data, dict):
        raise BrokenConfig(f"{name} должен быть JSON-объектом. Исправьте файл вручную: сохранение отменено, "
                           f"чтобы не затереть его содержимое")
    return data


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


def model_groups(models) -> list[tuple[str, list]]:
    """Модели для выпадающего списка, сгруппированные по провайдеру."""
    groups: dict[str, list] = {}
    for model in models:
        groups.setdefault(model.provider_label, []).append(model)
    return list(groups.items())


def model_label(model_id: str) -> str:
    found = find_model(model_id)
    return found.label if found else model_id


def save_runtime_patch(path: str, **fields) -> None:
    data = read_config_for_update(path)
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
    return _object_or_empty(path)


def prompt_view(settings, ai, user_key: str | None) -> PromptView:
    slug = load_runtime_dict(settings.runtime_file).get("active_persona", "")
    persona = load_persona(settings.personas_dir, slug) if slug else None
    raw = access_raw(settings.access_file)
    user_prompt = join_lines((raw.get("user_prompts") or {}).get(user_key)) if user_key else ""
    private_prompt = join_lines(raw.get("private_prompt")) if user_key else ""
    preview = ai.system_preview(slug, scope_prompt=private_prompt, user_prompt=user_prompt)
    return PromptView(persona_slug=slug, persona_name=persona.name if persona else "по умолчанию",
                      user_key=user_key, message=preview.message, layers=list(preview.layers))


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


NOTE_FIELDS = ("user_prompts", "peer_prompts")


def _fits_one_line(field: str, key: str, note) -> bool:
    if not isinstance(note, str):
        return False
    try:
        return _keyed_prompts(field, f"{key}: {note}") == {key: note}
    except ValueError:
        return False


def _one_line_notes(raw: dict, field: str) -> dict:
    return {k: v for k, v in (raw.get(field) or {}).items() if _fits_one_line(field, k, v)}


def unlisted_notes(raw: dict, field: str) -> dict:
    """Заметки, которые строка «ключ: текст» исказила бы (многострочные, с пробелами по краям):
    форма доступа их не показывает и сохраняет как есть."""
    return {k: v for k, v in (raw.get(field) or {}).items() if not _fits_one_line(field, k, v)}


def unlisted_note_keys(path: str) -> dict[str, list[str]]:
    raw = access_raw(path)
    return {field: list(unlisted_notes(raw, field)) for field in NOTE_FIELDS}


def parse_access_form(form: dict, stored: dict | None = None) -> dict:
    """`stored` — нынешний access.json: из него берутся заметки, которых в форме нет."""
    data = {field: _lines(form.get(field, "")) for field in ACCESS_LIST_FIELDS}
    data["private_prompt"] = _lines(form.get("private_prompt", ""))
    data["chat_prompt"] = _lines(form.get("chat_prompt", ""))
    for field in NOTE_FIELDS:
        data[field] = {**unlisted_notes(stored or {}, field), **_keyed_prompts(field, form.get(field, ""))}
    data["peer_blocked_users"] = {k: v.replace(",", " ").split()
                                  for k, v in _keyed_prompts("peer_blocked_users",
                                                             form.get("peer_blocked_users", "")).items()}
    try:
        # разбор бота прощает ошибки в старых ключах, а форма должна их назвать
        legacy_lists(data, lambda names: frozenset())
        parse_access(data, resolve_screen_names=lambda names: frozenset())
    except Exception as e:
        raise ValueError(f"Некорректные значения: {e}") from e
    return data


def access_form_values(path: str) -> dict:
    raw = access_raw(path)
    values = {field: "\n".join(str(x) for x in raw.get(field) or []) for field in ACCESS_LIST_FIELDS}
    values["private_prompt"] = join_lines(raw.get("private_prompt"))
    values["chat_prompt"] = join_lines(raw.get("chat_prompt"))
    for field in NOTE_FIELDS:
        values[field] = "\n".join(f"{k}: {v}" for k, v in _one_line_notes(raw, field).items())
    values["peer_blocked_users"] = "\n".join(f"{k}: {' '.join(str(x) for x in v or [])}"
                                              for k, v in (raw.get("peer_blocked_users") or {}).items())
    return values


GROUP_CHAT_PEER_BASE = 2_000_000_000


def peer_label(peer_id: int) -> str:
    return f"беседа {peer_id - GROUP_CHAT_PEER_BASE}" if peer_id >= GROUP_CHAT_PEER_BASE else f"id{peer_id}"


def peer_link(peer_id: int) -> str:
    sel = f"c{peer_id - GROUP_CHAT_PEER_BASE}" if peer_id >= GROUP_CHAT_PEER_BASE else str(peer_id)
    return f"https://vk.com/im?sel={sel}"


def sandbox_reply(settings, ai, vk, *, persona_slug: str, conversation: str, peer_id: int | None,
                  count: int, asker: str, temperature: float, model: str = "") -> tuple[str, str]:
    request = ReplyRequest((), asker, persona=persona_slug, temperature=temperature, model=model,
                           transcript=conversation)
    if peer_id is not None:
        is_private = peer_id < GROUP_CHAT_PEER_BASE
        lists = AccessFile(settings.access_file, vk.resolve_screen_names).current()
        general_prompt, specific_prompt = scoped_prompts(lists, peer_id, is_private)
        request = ReplyRequest(
            to_lines(vk.history(peer_id, count), vk.resolve_name, vk.me_id), asker, is_private=is_private,
            auto_chat=peer_id in lists.auto_reply_peers or peer_id in lists.onboarding_peers,
            persona=persona_slug, scope_prompt=general_prompt, user_prompt=specific_prompt,
            temperature=temperature, model=model,
        )
    result = ai.reply(request)
    parts = deliverable(result.parts, [settings.vk_token], vk.me_id if vk is not None else None)
    return result.conversation, "\n".join(parts)
