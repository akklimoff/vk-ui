import json
import os

from fastapi.testclient import TestClient

from ai.contract import AgentStep, ToolCall
from tests.web.conftest import AUTH
from tests.web.fakes import FakeAi
from web.app import create_app

HX = {"HX-Request": "true"}
CHAT = 2000000001
ASK = {"text": "как дела", "peer": "saved", "role": "owner", "persona": "v", "temperature": "0.8", "model": ""}


class FakeVk:
    me_id = 1

    def __init__(self, token):
        self.calls = []

    def call(self, method, params):
        self.calls.append((method, params))
        if method == "messages.getHistory":
            return {"items": [{"id": 5, "text": "чужое сообщение из истории"}]}
        return {}

    def resolve_name(self, uid):
        return "Вася"

    def resolve_screen_names(self, names):
        return frozenset()


def says(text="", *calls):
    return AgentStep(text, tuple(calls), "grok-4.6", 10, 5)


def call(method, params=None, id="c1"):
    return ToolCall(id, "vk_api", json.dumps({"method": method, "params": params or {}}, ensure_ascii=False))


def scripted(*steps):
    class StepAi(FakeAi):
        def __init__(self, settings):
            super().__init__(settings)
            self.steps = list(steps)

        def step(self, req):
            self.requests.append(req)
            step = self.steps.pop(0)
            if isinstance(step, Exception):
                raise step
            return step

    return StepAi


def client_for(settings, *steps, vk=FakeVk):
    with open(f"{settings.personas_dir}/v.md", "w", encoding="utf-8") as f:
        f.write("# В\nперсона В")
    return TestClient(create_app(settings, vk_factory=vk, ai_factory=scripted(*steps)), follow_redirects=False)


def trust_chat(settings, **extra):
    with open(settings.access_file, "w", encoding="utf-8") as f:
        json.dump({"agent_peers": [CHAT], **extra}, f, ensure_ascii=False)


def test_plain_request_in_saved_messages_shows_the_answer(settings):
    client = client_for(settings, says("нормально"))
    r = client.post("/sandbox", data=ASK, auth=AUTH)
    assert r.status_code == 200 and "нормально" in r.text and "ответила" in r.text and "Вызовов не было" in r.text
    req = client.app.state.ai.requests[0]
    assert (req.persona, req.temperature, req.model) == ("v", 0.8, "")
    first = req.turns[0].content
    assert first.endswith("ПРОСЬБА:\nкак дела") and "Избранное" in first and "владелец аккаунта" in first
    assert client.app.state.vk.calls == []


def test_write_is_not_executed_and_the_run_leaves_no_trace(settings):
    trust_chat(settings)
    client = client_for(settings, says("", call("messages.getHistory", {"count": 5})),
                        says("", call("messages.send", {"message": "всем привет"}, id="c2")), says("написала"))
    r = client.post("/sandbox", data={**ASK, "text": "напиши всем привет", "peer": str(CHAT)}, auth=AUTH)
    assert r.status_code == 200
    assert [method for method, _ in client.app.state.vk.calls] == ["messages.getHistory"]
    assert "messages.send" in r.text and "всем привет" in r.text and "пробный прогон" in r.text
    assert "чужое сообщение из истории" not in r.text
    assert not os.path.exists(f"{settings.state_dir}/actions.jsonl")
    assert not os.path.exists(f"{settings.state_dir}/pending.json")
    told = client.app.state.ai.requests[2].turns[-1]
    assert told.role == "tool" and "dry_run" in told.content


def test_trusted_role_gets_only_the_rights_of_a_trusted_person(settings):
    trust_chat(settings)
    client = client_for(settings, says("", call("wall.post", {"message": "пост"})), says("так не могу"))
    r = client.post("/sandbox", data={**ASK, "peer": str(CHAT), "role": "trusted"}, auth=AUTH)
    assert "wall.post" in r.text and "отказ" in r.text and client.app.state.vk.calls == []
    assert "доверенный человек" in client.app.state.ai.requests[0].turns[0].content
    assert "wall.post" not in client.app.state.ai.requests[0].tools[0].description


def test_destructive_call_of_the_owner_stops_at_the_question(settings):
    trust_chat(settings)
    client = client_for(settings, says("", call("messages.delete", {"cmids": "5"})))
    r = client.post("/sandbox", data={**ASK, "peer": str(CHAT)}, auth=AUTH)
    assert "ждёт «да»" in r.text and "Удалить сообщения?" in r.text
    assert client.app.state.vk.calls == [] and not os.path.exists(f"{settings.state_dir}/pending.json")


def test_role_is_ignored_in_saved_messages(settings):
    client = client_for(settings, says("ок"))
    client.post("/sandbox", data={**ASK, "role": "trusted"}, auth=AUTH)
    assert "владелец аккаунта" in client.app.state.ai.requests[0].turns[0].content


def test_only_a_trusted_chat_can_be_tried(settings):
    client = client_for(settings, says("ок"))
    for peer in ("2000000009", "22", "мусор"):
        r = client.post("/sandbox", data={**ASK, "peer": peer}, auth=AUTH, headers=HX)
        assert r.status_code == 422 and "не слушает" in r.text
    assert client.app.state.ai is None or client.app.state.ai.requests == []


def test_chat_note_and_the_chosen_model_reach_the_model(settings):
    trust_chat(settings, peer_prompts={str(CHAT): "тут все свои"})
    client = client_for(settings, says("ок"))
    r = client.post("/sandbox", data={**ASK, "peer": str(CHAT), "model": "claude-opus-5"}, auth=AUTH)
    req = client.app.state.ai.requests[0]
    assert (req.scope_prompt, req.model) == ("тут все свои", "claude-opus-5")
    assert 'value="claude-opus-5" selected' in r.text and f'value="{CHAT}" selected' in r.text


def test_hx_returns_only_the_result(settings):
    client = client_for(settings, says("нормально"))
    r = client.post("/sandbox", data=ASK, auth=AUTH, headers=HX)
    assert r.status_code == 200 and "<html" not in r.text and "<form" not in r.text
    assert 'id="sandbox-result"' in r.text and "нормально" in r.text


def test_empty_request_and_bad_temperature_are_form_errors(settings):
    client = client_for(settings, says("ок"))
    for form in ({**ASK, "text": "  "}, {**ASK, "temperature": "hot"}):
        r = client.post("/sandbox", data=form, auth=AUTH, headers=HX)
        assert r.status_code == 422 and 'class="error"' in r.text
        assert client.post("/sandbox", data=form, auth=AUTH).status_code == 400
    assert client.app.state.ai is None or client.app.state.ai.requests == []


def test_ai_failure_is_shown_with_its_reason_and_without_secrets(settings):
    client = client_for(settings, RuntimeError("timeout, key xai-KEY, token vk"))
    r = client.post("/sandbox", data=ASK, auth=AUTH, headers=HX)
    assert r.status_code == 200 and "сбой" in r.text and "timeout" in r.text
    assert "xai-KEY" not in r.text and "token [скрыто]" in r.text


def test_answer_is_shown_as_it_would_be_sent(settings):
    client = client_for(settings, says("[id1|Валя] тут, токен vk"))
    r = client.post("/sandbox", data=ASK, auth=AUTH, headers=HX)
    assert "Валя тут, токен [скрыто]" in r.text and "[id1|" not in r.text


def test_page_offers_trusted_chats_and_says_nothing_is_sent(settings):
    trust_chat(settings)
    page = client_for(settings).get("/sandbox", auth=AUTH).text
    assert f'value="{CHAT}"' in page and 'value="saved"' in page and "ничего не отправ" in page
    assert 'name="conversation"' not in page and 'name="count"' not in page


def unreachable_ai(settings):
    from ai.client import AiClient

    return AiClient("http://127.0.0.1:9", 0.5)


def test_sandbox_reports_unreachable_ai_service(settings):
    client = TestClient(create_app(settings, vk_factory=FakeVk, ai_factory=unreachable_ai), follow_redirects=False)
    r = client.post("/sandbox", data={**ASK, "persona": ""}, auth=AUTH, headers=HX)
    assert r.status_code == 200 and "ИИ-сервис недоступен" in r.text


def test_settings_page_survives_unreachable_ai_service(settings):
    client = TestClient(create_app(settings, vk_factory=FakeVk, ai_factory=unreachable_ai), follow_redirects=False)
    r = client.get("/settings", auth=AUTH)
    assert r.status_code == 200 and "ИИ-сервис недоступен" in r.text


def test_prompts_page_survives_unreachable_ai_service(settings):
    client = TestClient(create_app(settings, vk_factory=FakeVk, ai_factory=unreachable_ai), follow_redirects=False)
    r = client.get("/prompts", auth=AUTH)
    assert r.status_code == 200 and "ИИ-сервис недоступен" in r.text


def test_saving_settings_with_ai_down_keeps_the_chosen_model(settings):
    with open(settings.runtime_file, "w", encoding="utf-8") as f:
        json.dump({"active_model": "claude-opus-5"}, f)
    client = TestClient(create_app(settings, vk_factory=FakeVk, ai_factory=unreachable_ai), follow_redirects=False)
    r = client.post("/settings", data={"temperature": "0.5", "active_model": "", "paused_peers": ""}, auth=AUTH)
    assert r.status_code == 303
    with open(settings.runtime_file, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["active_model"] == "claude-opus-5" and saved["temperature"] == 0.5
