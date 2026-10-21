import pytest
from fastapi.testclient import TestClient

from tests.web.fakes import FakeVk
from web.app import create_app
from web.config import Settings

AUTH = ("admin", "pw")


@pytest.fixture
def settings():
    return Settings(vk_token="vk", web_password="pw", _env_file=None)


@pytest.fixture
def client(settings):
    return TestClient(create_app(settings, vk_factory=FakeVk), follow_redirects=False)
