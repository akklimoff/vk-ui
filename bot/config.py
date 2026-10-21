import re

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    vk_token: str
    llm_temperature: float = 0.8
    # адрес ИИ-сервиса; пусто — ИИ работает в том же процессе
    ai_url: str = ""
    ai_timeout_seconds: float = 200
    user_cooldown_seconds: float = 2
    chat_limit_per_hour: int = 60
    global_limit_per_minute: int = 30
    agent_max_steps: int = 16
    agent_time_budget_seconds: float = 240
    agent_result_char_limit: int = 12000
    agent_confirm_ttl_seconds: float = 300
    log_message_text: bool = False
    access_file: str = "config/access.json"
    runtime_file: str = "config/runtime.json"
    personas_dir: str = "config/personas"
    state_dir: str = "state"
    web_password: str = ""
    # образ web задаёт 0.0.0.0, чтобы до панели дошёл Caddy; локальный запуск не выставляет Basic Auth по HTTP в сеть
    web_host: str = "127.0.0.1"
    web_timezone: str = "Europe/Moscow"


def parse_ids(raw: str) -> frozenset[int]:
    return frozenset(int(part) for part in raw.replace(",", " ").split())


# str.isdigit и \d пропускают «²» и «٣», а int() на «²» и на числе длиннее 4300 цифр бросает ValueError
USER_ID = re.compile(r"(?:id)?([0-9]{1,18})")


def parse_user_refs(raw: str) -> tuple[frozenset[int], frozenset[str]]:
    ids: set[int] = set()
    screen_names: set[str] = set()
    for token in raw.replace(",", " ").split():
        ref = token.lstrip("@")
        number = USER_ID.fullmatch(ref)
        if number:
            ids.add(int(number.group(1)))
        elif ref:
            screen_names.add(ref.lower())
    return frozenset(ids), frozenset(screen_names)
