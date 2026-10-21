from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    vk_token: str
    web_password: str = ""
    # образ задаёт 0.0.0.0, чтобы до панели дошёл Caddy; локальный запуск не выставляет Basic Auth по HTTP в сеть
    web_host: str = "127.0.0.1"
    web_timezone: str = "Europe/Moscow"
