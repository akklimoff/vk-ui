import pytest
from fastapi.testclient import TestClient

from ai.config import AiSettings
from ai.service import AiService
from bot.config import Settings
from web.app import create_app

AUTH = ("admin", "pw")


@pytest.fixture
def settings(tmp_path):
    (tmp_path / "config" / "personas").mkdir(parents=True)
    return Settings(
        vk_token="vk", web_password="pw",
        access_file=str(tmp_path / "config" / "access.json"),
        runtime_file=str(tmp_path / "config" / "runtime.json"),
        moderation_file=str(tmp_path / "config" / "moderation.json"),
        personas_dir=str(tmp_path / "config" / "personas"),
        state_dir=str(tmp_path / "state"),
        _env_file=None,
    )


@pytest.fixture
def ai_settings(settings):
    return AiSettings(llm_api_key="k", anthropic_api_key="sk-ant-k", personas_dir=settings.personas_dir,
                      _env_file=None)


@pytest.fixture
def client(settings, ai_settings):
    return TestClient(create_app(settings, ai_factory=lambda s: AiService(ai_settings)), follow_redirects=False)
