import pytest
from fastapi.testclient import TestClient

from ai.context import Line
from tests.web.conftest import AUTH
from tests.web.fakes import FakeAi
from web.app import create_app




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
    return TestClient(create_app(settings, vk_factory=FakeVk, ai_factory=FakeAi), follow_redirects=False)


def test_sandbox_from_text_does_not_touch_vk(client):
    r = client.post("/sandbox", data={"persona": "v", "conversation": "Вася: [id1|Валя] привет",
                                      "peer_id": "", "count": "40", "asker": "Вася",
                                      "temperature": "0.8"}, auth=AUTH)
    assert r.status_code == 200 and "ответ из песочницы" in r.text
    req = client.app.state.ai.requests[-1]
    assert req.transcript.startswith("Вася:") and req.persona == "v" and req.temperature == 0.8
    assert client.app.state.vk is None


def test_sandbox_sends_the_chosen_model(client):
    r = client.post("/sandbox", data={"persona": "v", "conversation": "Вася: привет", "peer_id": "",
                                      "count": "40", "asker": "Вася", "temperature": "0.8",
                                      "model": "claude-opus-5"}, auth=AUTH)
    assert r.status_code == 200 and 'value="claude-opus-5" selected' in r.text
    assert client.app.state.ai.requests[-1].model == "claude-opus-5"


def test_sandbox_from_peer_uses_history(client):
    r = client.post("/sandbox", data={"persona": "v", "conversation": "", "peer_id": "2000000001",
                                      "count": "10", "asker": "Вася", "temperature": "0.5"}, auth=AUTH)
    assert r.status_code == 200
    req = client.app.state.ai.requests[-1]
    assert req.lines == (Line("Вася", "привет"),) and req.is_private is False


HX = {"HX-Request": "true"}


def test_sandbox_hx_returns_result_partial_only(client):
    r = client.post("/sandbox", data={"persona": "v", "conversation": "Вася: привет", "peer_id": "",
                                      "count": "40", "asker": "Вася", "temperature": "0.8"}, auth=AUTH, headers=HX)
    assert r.status_code == 200 and "<html" not in r.text and "<form" not in r.text
    assert 'id="sandbox-result"' in r.text and "ответ из песочницы" in r.text and "Вася: привет" in r.text


def test_sandbox_hx_bad_number_returns_422_error(client):
    r = client.post("/sandbox", data={"persona": "v", "conversation": "x", "peer_id": "",
                                      "count": "many", "asker": "Вася", "temperature": "0.8"}, auth=AUTH, headers=HX)
    assert r.status_code == 422 and 'class="error"' in r.text and client.app.state.ai is None


def test_sandbox_llm_failure_returns_422_with_reason_and_hides_secrets(settings):
    class BrokenAi(FakeAi):
        def reply(self, req):
            raise RuntimeError("timeout, key k")

    client = TestClient(create_app(settings, vk_factory=FakeVk, ai_factory=BrokenAi), follow_redirects=False)
    data = {"persona": "", "conversation": "x", "peer_id": "", "count": "1", "asker": "a", "temperature": "0.5"}
    r = client.post("/sandbox", data=data, auth=AUTH, headers=HX)
    assert r.status_code == 422 and "timeout" in r.text and "key k" not in r.text and "[скрыто]" in r.text
    assert client.post("/sandbox", data=data, auth=AUTH).status_code == 400
