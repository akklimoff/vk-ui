import pytest
from fastapi.testclient import TestClient

from bot.config import Settings
from web.app import create_app

AUTH = ("admin", "pw")


@pytest.fixture
def settings(tmp_path):
    (tmp_path / "config" / "personas").mkdir(parents=True)
    return Settings(
        vk_token="vk", llm_api_key="k", web_password="pw",
        access_file=str(tmp_path / "config" / "access.json"),
        runtime_file=str(tmp_path / "config" / "runtime.json"),
        personas_dir=str(tmp_path / "config" / "personas"),
        state_dir=str(tmp_path / "state"),
        _env_file=None,
    )


@pytest.fixture
def client(settings):
    return TestClient(create_app(settings))
