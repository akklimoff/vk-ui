import json
import os
import threading
from dataclasses import dataclass
from typing import Callable

from ai.catalog import find_model
from ai.personas import persona_path, render_persona
from ai.contract import ReplyRequest
from bot.access import AccessFile, scoped_prompts
from bot.agent.loop import Limits
from bot.config import parse_ids
from bot.context import to_lines
from bot.reply import deliverable
from bot.status import read_json, write_json_atomic

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
}


def ceilings(settings) -> list[tuple[str, str, str]]:
    """Потолки агента для справки: (название, значение, переменная в .env; пусто — зашито в код)."""
    limits = Limits()
    return [
        ("шагов модели на просьбу", str(settings.agent_max_steps), "AGENT_MAX_STEPS"),
        ("секунд на просьбу", str(settings.agent_time_budget_seconds), "AGENT_TIME_BUDGET_SECONDS"),
        ("символов одного результата VK", str(settings.agent_result_char_limit), "AGENT_RESULT_CHAR_LIMIT"),
        ("секунд ожидания «да»", str(settings.agent_confirm_ttl_seconds), "AGENT_CONFIRM_TTL_SECONDS"),
        ("вызовов VK на просьбу", str(limits.max_calls), ""),
        ("из них пишущих", str(limits.max_writes), ""),
        ("пауза между просьбами одного человека, с", str(settings.user_cooldown_seconds), "USER_COOLDOWN_SECONDS"),
        ("просьб на чат в час", str(settings.chat_limit_per_hour), "CHAT_LIMIT_PER_HOUR"),
        ("просьб всего в минуту", str(settings.global_limit_per_minute), "GLOBAL_LIMIT_PER_MINUTE"),
    ]


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


CONFIG_WRITES = threading.Lock()


def update_config(path: str, change: Callable[[dict], dict]) -> dict:
    """Чтение, правка и запись файла настроек одним куском. Роуты выполняются в пуле потоков: без блокировки
    две правки подряд прочли бы один и тот же файл, и вторая запись стёрла бы первую."""
    with CONFIG_WRITES:
        data = change(read_config_for_update(path))
        write_json_atomic(path, data)
    return data


def save_runtime_patch(path: str, **fields) -> None:
    update_config(path, lambda data: {**data, **fields})


def save_persona(personas_dir: str, slug: str, name: str, prompt: str) -> None:
    path = persona_path(personas_dir, slug)
    os.makedirs(personas_dir, exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(render_persona(name, prompt))
    os.replace(tmp, path)


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
