import pytest
from fastapi.testclient import TestClient

from tests.web.conftest import AUTH
from web.app import create_app


class FakeLlm:
    def __init__(self, settings):
        self.calls = []

    def reply(self, conversation, asker, **kw):
        self.calls.append((conversation, asker, kw))
        return "ответ из песочницы"


class FakeVk:
    me_id = 1

    def __init__(self, token):
        pass

    def history(self, peer_id, count):
        return [{"from_id": 5, "text": "привет"}]

    def resolve_name(self, uid):
        return "Вася"

    def resolve_screen_names(self, names):
        return frozenset()


@pytest.fixture
def client(settings):
    open(f"{settings.personas_dir}/v.md", "w").write("# В\nперсона В")
    return TestClient(create_app(settings, vk_factory=FakeVk, llm_factory=FakeLlm), follow_redirects=False)


def test_sandbox_from_text_does_not_touch_vk(client):
    r = client.post("/sandbox", data={"persona": "v", "conversation": "Вася: [id1|Валя] привет",
                                      "peer_id": "", "count": "40", "asker": "Вася",
                                      "temperature": "0.8"}, auth=AUTH)
    assert r.status_code == 200 and "ответ из песочницы" in r.text
    conv, asker, kw = client.app.state.llm.calls[-1]
    assert conv.startswith("Вася:") and kw["persona_prompt"] == "персона В" and kw["temperature"] == 0.8
    assert client.app.state.vk is None


def test_sandbox_from_peer_uses_history(client):
    r = client.post("/sandbox", data={"persona": "v", "conversation": "", "peer_id": "2000000001",
                                      "count": "10", "asker": "Вася", "temperature": "0.5"}, auth=AUTH)
    assert r.status_code == 200
    conv, _, kw = client.app.state.llm.calls[-1]
    assert "Вася: привет" in conv and kw["is_private"] is False
