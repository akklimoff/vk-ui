import json

import ai.contract
from ai.contract import (AgentRequest, AgentStep, ModelInfo, SystemPreview, ToolCall, ToolSpec, Turn, dump,
                         load_agent_request, load_model, load_preview, load_step)


def roundtrip(obj):
    return json.loads(json.dumps(dump(obj)))


def test_preview_and_model_survive_json():
    preview = SystemPreview("msg", (("СИСТЕМА", "текст"),))
    model = ModelInfo("claude-opus-5", "Claude Opus 5", "claude", "Claude")
    assert load_preview(roundtrip(preview)) == preview
    assert load_model(roundtrip(model)) == model


def test_agent_request_and_step_survive_json():
    call = ToolCall("c1", "vk_api", '{"method": "users.get"}')
    req = AgentRequest(
        (Turn("user", "дай ссылку"), Turn("assistant", "", (call,)), Turn("tool", '{"ok": 1}', (), "c1")),
        (ToolSpec("vk_api", "вызов VK", {"type": "object"}),),
        persona="rina", scope_prompt="заметка", model="grok-4.6", temperature=0.3,
    )
    step = AgentStep("готово", (call,), "grok-4.6", 10, 5)
    assert load_agent_request(roundtrip(req)) == req
    assert load_step(roundtrip(step)) == step


def test_pictures_of_a_turn_survive_json():
    req = AgentRequest((Turn("user", "что тут", images=("data:image/jpeg;base64,AAA",)), Turn("user", "и ещё")))
    loaded = load_agent_request(roundtrip(req))
    assert loaded == req and loaded.turns[0].images == ("data:image/jpeg;base64,AAA",) and loaded.turns[1].images == ()


def test_agent_request_defaults_and_step_without_calls():
    assert load_agent_request({"turns": [{"role": "user", "content": "привет"}]}) == AgentRequest((Turn("user", "привет"),))
    assert load_step({"text": "ок"}) == AgentStep("ок")
    assert load_step({"text": "начало", "truncated": True}).truncated is True
    assert AgentStep("ок").truncated is False


def test_agent_step_carries_the_finish_reason_over_the_wire():
    step = AgentStep("начало", finish_reason="content_filter")
    assert load_step(dump(step)) == step and step.abnormal
    assert load_step({"text": "ок"}).finish_reason == ""
    for reason in ("", "stop", "tool_calls", "function_call", "length"):
        assert not AgentStep("ок", finish_reason=reason).abnormal


def test_agent_step_carries_the_leak_mark_over_the_wire():
    step = AgentStep("", (ToolCall("c1", "vk_api", "{}"),), leaked=True)
    assert load_step(roundtrip(step)) == step
    assert load_step({"text": "ок"}).leaked is False and AgentStep("ок").leaked is False


def test_contract_carries_only_the_agent():
    for name in ("ReplyRequest", "ReplyResult", "load_request", "load_result", "load_lines"):
        assert not hasattr(ai.contract, name), name
