import pytest

from ai.llm import (
    MODELS,
    PERSONA_LAYER,
    PRECEDENCE_PREAMBLE,
    PROVIDERS,
    SYSTEM_LAYER,
    THINKING_ROOM,
    LlmClient,
    active_model_id,
    api_key_for,
    available_models,
    compose_agent_message,
    find_model,
    resolve_provider,
    secrets_of,
)


class FakeSettings:
    llm_provider = "grok"
    llm_base_url = ""
    llm_model = ""
    llm_workspace_id = ""
    llm_api_key = "xai-kluch"
    xai_api_key = ""
    anthropic_api_key = ""
    openai_api_key = ""
    deepseek_api_key = ""
    moonshot_api_key = ""
    llm_timeout_seconds = 1
    llm_reasoning_effort = ""
    max_tokens = 100
    llm_temperature = 0.8
    persona_prompt = "характер"
    agent_prompt = "правила агента"


def test_grok_is_default_preset():
    provider = resolve_provider("grok")
    assert provider.base_url == "https://api.x.ai/v1"
    assert provider.model == "grok-4.3"


def test_all_presets_resolve():
    for name in PROVIDERS:
        provider = resolve_provider(name)
        assert provider.base_url.startswith("https://")
        assert provider.model


def test_model_override():
    provider = resolve_provider("grok", model="grok-4")
    assert provider.model == "grok-4"
    assert provider.base_url == "https://api.x.ai/v1"


def test_custom_provider_via_overrides():
    provider = resolve_provider("местный", base_url="http://localhost:8000/v1", model="llama")
    assert provider.base_url == "http://localhost:8000/v1"
    assert provider.model == "llama"


def test_unknown_provider_without_overrides_fails():
    with pytest.raises(ValueError, match="Неизвестный провайдер"):
        resolve_provider("неведомый")


def stub_client(llm: LlmClient, completions, provider: str = "grok") -> None:
    """Клиент провайдера создаётся лениво — подменяем его прямо в кэше."""
    llm._clients[provider] = type("Fake", (), {"chat": type("Chat", (), {"completions": completions})()})()


class FakeHttp:
    def __init__(self, seen, body=None):
        self.seen = seen
        self.body = body or {"content": [{"type": "text", "text": "ок"}], "stop_reason": "end_turn"}

    def post(self, url, json, headers):
        self.seen.update(json, url=url, headers=headers)
        return type("R", (), {"status_code": 200, "json": lambda _: self.body})()


def stub_claude(llm: LlmClient, seen, body=None) -> None:
    from ai.claude import ClaudeApi

    llm._claude = ClaudeApi("sk-ant", PROVIDERS["claude"].base_url, 1, http=FakeHttp(seen, body))


def layer_order(message: str) -> list[str]:
    return [line[1:-1] for line in message.splitlines() if line.startswith("[")]


def test_workspace_id_becomes_anthropic_header():
    class WithWorkspace(FakeSettings):
        llm_provider = "claude"
        llm_workspace_id = "wrksp_1"

    class ThroughProxy(WithWorkspace):
        llm_base_url = "https://proxy.example/v1"

    llm = LlmClient(WithWorkspace())
    assert llm._native(llm._target("").base_url)._headers["anthropic-workspace-id"] == "wrksp_1"
    proxied = LlmClient(ThroughProxy())
    assert proxied._connect("claude", proxied._target("").base_url).default_headers["anthropic-workspace-id"] == "wrksp_1"
    plain = LlmClient(FakeSettings())
    assert "anthropic-workspace-id" not in plain._connect("grok", plain._target("").base_url).default_headers


def test_reasoning_effort_none_is_not_sent():
    from ai.llm import LlmClient

    class NoneEffort(FakeSettings):
        llm_reasoning_effort = "none"

    class LowEffort(FakeSettings):
        llm_reasoning_effort = "low"

    assert LlmClient(NoneEffort())._reasoning_effort == ""
    assert LlmClient(LowEffort())._reasoning_effort == "low"


class MultiKeySettings(FakeSettings):
    anthropic_api_key = "sk-ant-kluch"


def test_every_catalog_model_belongs_to_a_known_provider():
    assert MODELS and all(m.provider in PROVIDERS for m in MODELS)
    assert find_model("claude-opus-5").provider == "claude"
    assert find_model("нет такой") is None


def test_only_models_with_a_key_are_offered():
    grok_only = [m.id for m in available_models(FakeSettings())]
    assert grok_only and all(m.startswith("grok") for m in grok_only)
    assert {m.provider for m in available_models(MultiKeySettings())} == {"grok", "claude"}


def test_default_provider_falls_back_to_llm_api_key():
    assert api_key_for(FakeSettings(), "grok") == "xai-kluch"
    assert api_key_for(FakeSettings(), "claude") == ""
    assert api_key_for(MultiKeySettings(), "claude") == "sk-ant-kluch"


def test_secrets_cover_every_configured_key():
    assert secrets_of(MultiKeySettings()) == ["sk-ant-kluch", "xai-kluch"]


def test_chosen_model_picks_its_own_provider_client():
    llm = LlmClient(MultiKeySettings())
    default, claude = llm._target(""), llm._target("claude-opus-5")
    assert (default.provider, default.model.id) == ("grok", "grok-4.3") and not default.native_claude
    assert (claude.provider, claude.model.id) == ("claude", "claude-opus-5") and claude.native_claude
    assert llm._connect(default.provider, default.base_url).api_key == "xai-kluch"
    native = llm._native(claude.base_url)
    assert native._headers["x-api-key"] == "sk-ant-kluch" and native._url == "https://api.anthropic.com/v1/messages"


def test_claude_behind_another_address_stays_on_the_compatible_client():
    class ThroughProxy(FakeSettings):
        llm_provider = "claude"
        llm_base_url = "https://proxy.example/v1"

    assert not LlmClient(ThroughProxy())._target("").native_claude


def test_unknown_model_goes_to_the_default_provider():
    target = LlmClient(MultiKeySettings())._target("grok-4-fast")
    assert (target.model.id, target.model.sampling, target.model.vision) == ("grok-4-fast", True, False)
    assert target.base_url.startswith("https://api.x.ai")


def test_model_without_a_key_is_refused():
    with pytest.raises(ValueError, match="ключ провайдера"):
        LlmClient(FakeSettings()).step((), (), model="claude-opus-5")


def test_sonnet_5_5_is_the_claude_default_and_takes_no_temperature():
    sonnet = find_model("claude-sonnet-5-5")
    assert (sonnet.provider, sonnet.sampling) == ("claude", False)
    assert PROVIDERS["claude"].model == "claude-sonnet-5-5"


def test_active_model_id_reports_what_will_be_called():
    assert active_model_id(FakeSettings(), "claude-opus-5") == "claude-opus-5"
    assert active_model_id(FakeSettings(), "") == "grok-4.3"


def scripted_completions(seen, message):
    class FakeCompletions:
        def create(self, **kw):
            seen.update(kw)
            usage = type("U", (), {"prompt_tokens": 11, "completion_tokens": 7})()
            return type("R", (), {"choices": [type("C", (), {"message": message})()], "usage": usage})()

    return FakeCompletions()


def test_agent_layers_go_system_peer_persona():
    from ai.llm import PEER_LAYER, compose_agent_message

    message = compose_agent_message("правила агента", "заметка беседы", "характер")
    assert layer_order(message) == [SYSTEM_LAYER, PEER_LAYER, PERSONA_LAYER]
    assert message.startswith(PRECEDENCE_PREAMBLE)
    assert layer_order(compose_agent_message("правила агента", "", "характер")) == [SYSTEM_LAYER, PERSONA_LAYER]


def test_step_sends_tools_and_turns_and_parses_tool_calls():
    from ai.contract import ToolCall, ToolSpec, Turn

    client = LlmClient(FakeSettings())
    seen = {}
    function = type("F", (), {"name": "vk_api", "arguments": '{"method": "users.get"}'})()
    message = type("M", (), {"content": None, "tool_calls": [type("T", (), {"id": "c1", "function": function})()]})()
    stub_client(client, scripted_completions(seen, message))
    earlier = ToolCall("c0", "vk_api", "{}")
    turns = (Turn("user", "дай ссылку"), Turn("assistant", "", (earlier,)), Turn("tool", '{"ok": 1}', (), "c0"))

    step = client.step(turns, (ToolSpec("vk_api", "вызов VK", {"type": "object"}),), peer_note="заметка")

    assert step.tool_calls == (ToolCall("c1", "vk_api", '{"method": "users.get"}'),)
    assert step.text == "" and step.model_id == "grok-4.3"
    assert (step.prompt_tokens, step.completion_tokens) == (11, 7)
    assert seen["tool_choice"] == "auto"
    assert seen["tools"] == [{"type": "function", "function": {"name": "vk_api", "description": "вызов VK",
                                                                "parameters": {"type": "object"}}}]
    system, user, assistant, tool = seen["messages"]
    assert system["role"] == "system" and "правила агента" in system["content"] and "заметка" in system["content"]
    assert user == {"role": "user", "content": "дай ссылку"}
    assert assistant == {"role": "assistant", "content": None, "tool_calls": [
        {"id": "c0", "type": "function", "function": {"name": "vk_api", "arguments": "{}"}}]}
    assert tool == {"role": "tool", "tool_call_id": "c0", "content": '{"ok": 1}'}


def test_step_without_tools_or_usage_returns_plain_text():
    from ai.contract import Turn

    client = LlmClient(FakeSettings())
    seen = {}
    message = type("M", (), {"content": "  привет  "})()

    class NoUsage:
        def create(self, **kw):
            seen.update(kw)
            return type("R", (), {"choices": [type("C", (), {"message": message})()]})()

    stub_client(client, NoUsage())
    step = client.step((Turn("user", "привет"),), ())
    assert step.text == "привет" and step.tool_calls == ()
    assert (step.prompt_tokens, step.completion_tokens) == (0, 0)
    assert "tools" not in seen and "tool_choice" not in seen


def test_step_reports_an_answer_cut_by_the_token_limit():
    from ai.contract import Turn

    client = LlmClient(FakeSettings())

    def finished_with(reason):
        class Completions:
            def create(self, **kw):
                choice = type("C", (), {"message": type("M", (), {"content": "начало"})(), "finish_reason": reason})()
                return type("R", (), {"choices": [choice]})()

        return Completions()

    stub_client(client, finished_with("length"))
    assert client.step((Turn("user", "привет"),), ()).truncated is True
    stub_client(client, finished_with("stop"))
    assert client.step((Turn("user", "привет"),), ()).truncated is False


def test_step_omits_temperature_for_models_without_sampling():
    from ai.contract import Turn

    class WithClaude(FakeSettings):
        anthropic_api_key = "sk-ant"

    llm = LlmClient(WithClaude())
    seen = {}
    stub_claude(llm, seen)
    llm.step((Turn("user", "привет"),), (), model="claude-sonnet-5")
    assert "temperature" not in seen and seen["model"] == "claude-sonnet-5"


class ClaudeByDefault(FakeSettings):
    llm_provider = "claude"
    llm_api_key = "sk-ant-kluch"


def traits(settings) -> tuple[str, bool, bool]:
    model = LlmClient(settings)._target("").model
    return model.id, model.sampling, model.vision


def test_preset_default_model_takes_sampling_from_the_catalog():
    assert traits(ClaudeByDefault()) == ("claude-sonnet-5-5", False, True)
    assert traits(FakeSettings()) == ("grok-4.3", True, True)


def test_model_from_env_takes_sampling_from_the_catalog():
    class PinnedHaiku(ClaudeByDefault):
        llm_model = "claude-haiku-4-5-20251001"

    class PinnedUnknown(ClaudeByDefault):
        llm_model = "claude-next"

    assert traits(PinnedHaiku()) == ("claude-haiku-4-5-20251001", True, True)
    assert traits(PinnedUnknown()) == ("claude-next", False, False)


def test_step_on_the_claude_preset_sends_no_temperature():
    from ai.contract import Turn

    llm = LlmClient(ClaudeByDefault())
    seen = {}
    stub_claude(llm, seen)
    llm.step((Turn("user", "привет"),), (), temperature=0.3)
    assert seen["model"] == "claude-sonnet-5-5" and "temperature" not in seen


def test_step_reports_how_the_model_stopped():
    from ai.contract import Turn

    client = LlmClient(FakeSettings())

    def finished_with(reason):
        class Completions:
            def create(self, **kw):
                choice = type("C", (), {"message": type("M", (), {"content": "начало"})(), "finish_reason": reason})()
                return type("R", (), {"choices": [choice]})()

        return Completions()

    stub_client(client, finished_with("content_filter"))
    step = client.step((Turn("user", "привет"),), ())
    assert step.finish_reason == "content_filter" and step.abnormal and not step.truncated
    stub_client(client, finished_with("stop"))
    assert not client.step((Turn("user", "привет"),), ()).abnormal
    stub_client(client, finished_with(None))
    assert client.step((Turn("user", "привет"),), ()).finish_reason == ""


def test_temperature_reaches_only_models_that_take_it():
    from ai.contract import Turn

    llm = LlmClient(MultiKeySettings())
    seen = {}
    answer = type("M", (), {"content": "ок"})()
    stub_claude(llm, seen)
    stub_client(llm, scripted_completions(seen, answer))
    turns = (Turn("user", "привет"),)

    llm.step(turns, (), temperature=0.3, model="claude-sonnet-5")
    assert seen["model"] == "claude-sonnet-5" and "temperature" not in seen
    llm.step(turns, (), temperature=0.3, model="claude-haiku-4-5-20251001")
    assert seen["temperature"] == 0.3
    llm.step(turns, (), temperature=1.7, model="claude-haiku-4-5-20251001")
    assert seen["temperature"] == 1.0
    seen.clear()
    llm.step(turns, (), temperature=0.3, model="grok-4.6")
    assert seen["model"] == "grok-4.6" and seen["temperature"] == 0.3
    llm.step(turns, ())
    assert seen["temperature"] == 0.8


def test_persona_given_for_a_step_replaces_the_default_one():
    from ai.contract import Turn

    llm = LlmClient(FakeSettings())
    seen = {}
    stub_client(llm, scripted_completions(seen, type("M", (), {"content": "ок"})()))
    llm.step((Turn("user", "привет"),), (), persona_prompt="другая личность")
    system = seen["messages"][0]["content"]
    assert "другая личность" in system and "характер" not in system and "правила агента" in system


def test_pictures_of_a_turn_reach_a_model_that_sees_and_are_named_to_one_that_does_not():
    from ai.contract import Turn
    from ai.llm import UNSEEN_IMAGES, wire_turn

    turn = Turn("user", "что тут", images=("data:image/jpeg;base64,AAA", "data:image/png;base64,BBB"))
    assert wire_turn(turn) == {"role": "user", "content": [
        {"type": "text", "text": "что тут"},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAA"}},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,BBB"}}]}
    assert wire_turn(turn, vision=False) == {"role": "user", "content": "что тут" + UNSEEN_IMAGES}
    assert wire_turn(Turn("user", "просто текст")) == {"role": "user", "content": "просто текст"}


def test_step_sends_pictures_only_to_a_model_known_to_see():
    from ai.contract import Turn

    class PinnedUnknown(FakeSettings):
        llm_model = "grok-next"

    turn = Turn("user", "что тут", images=("data:image/jpeg;base64,AAA",))
    message = type("M", (), {"content": "кот", "tool_calls": None})()
    for settings, sees in ((FakeSettings(), True), (PinnedUnknown(), False)):
        client, seen = LlmClient(settings), {}
        stub_client(client, scripted_completions(seen, message))
        client.step((turn,), ())
        assert isinstance(seen["messages"][1]["content"], list) is sees


def test_claude_step_goes_through_the_native_api_in_cacheable_parts():
    from ai.contract import ToolSpec, Turn

    class LowEffort(MultiKeySettings):
        llm_reasoning_effort = "low"

    llm, seen = LlmClient(LowEffort()), {}
    stub_claude(llm, seen)
    step = llm.step((Turn("user", "привет"),), (ToolSpec("vk_api", "вызов", {"type": "object"}),),
                    peer_note="заметка", persona_prompt="личность", model="claude-sonnet-5-5")
    shared, own = seen["system"]
    assert shared["text"].startswith(PRECEDENCE_PREAMBLE) and shared["text"].endswith("правила агента")
    assert "заметка" in own["text"] and own["text"].endswith("личность")
    assert shared["text"] + own["text"] == compose_agent_message("правила агента", "заметка", "личность")
    assert seen["output_config"] == {"effort": "low"} and seen["max_tokens"] == 100 + THINKING_ROOM
    assert seen["tools"] == [{"name": "vk_api", "description": "вызов", "input_schema": {"type": "object"}}]
    assert (step.text, step.model_id) == ("ок", "claude-sonnet-5-5")
    seen.clear()
    llm.step((Turn("user", "привет"),), (), model="claude-haiku-4-5-20251001")
    assert "output_config" not in seen


@pytest.mark.parametrize("model, effort, thinking, max_tokens", [
    ("claude-sonnet-5-5", "", {"type": "between_tools"}, 100),
    ("claude-sonnet-5", "none", {"type": "disabled"}, 100),
    ("claude-haiku-5-5", "", {"type": "disabled"}, 100),
    ("claude-sonnet-5-5", "low", None, 100 + THINKING_ROOM),
    ("claude-opus-5-5", "", None, 100 + THINKING_ROOM),
    ("claude-opus-5", "", None, 100 + THINKING_ROOM),
    ("claude-fable-5-1", "", None, 100 + THINKING_ROOM),
    ("claude-sonnet-4-6", "", None, 100),
    ("claude-haiku-4-5-20251001", "high", None, 100),
])
def test_claude_thinks_only_when_effort_is_asked_and_then_gets_room_for_it(model, effort, thinking, max_tokens):
    from ai.contract import Turn

    class Asked(MultiKeySettings):
        llm_reasoning_effort = effort

    llm, seen = LlmClient(Asked()), {}
    stub_claude(llm, seen)
    llm.step((Turn("user", "привет"),), (), model=model)
    assert seen.get("thinking") == thinking and seen["max_tokens"] == max_tokens


def test_claude_gets_only_the_effort_and_sampling_its_model_accepts():
    from ai.contract import Turn

    class Highest(MultiKeySettings):
        llm_provider = "claude"
        llm_model = "claude-next-9"
        llm_reasoning_effort = "xhigh"

    llm, seen = LlmClient(Highest()), {}
    stub_claude(llm, seen)
    llm.step((Turn("user", "привет"),), (), model="claude-sonnet-4-6")
    assert seen["output_config"] == {"effort": "high"} and seen["temperature"] == 0.8
    seen.clear()
    llm.step((Turn("user", "привет"),), (), model="claude-opus-5-5")
    assert seen["output_config"] == {"effort": "xhigh"} and "temperature" not in seen
    seen.clear()
    llm.step((Turn("user", "привет"),), ())
    assert seen["model"] == "claude-next-9" and "temperature" not in seen
    assert seen["max_tokens"] == 100 + THINKING_ROOM


def test_compatible_step_reports_tokens_read_from_the_cache():
    from ai.contract import Turn

    class Completions:
        def create(self, **kw):
            details = type("D", (), {"cached_tokens": 40})()
            usage = type("U", (), {"prompt_tokens": 50, "completion_tokens": 5, "prompt_tokens_details": details})()
            choice = type("C", (), {"message": type("M", (), {"content": "ок"})(), "finish_reason": "stop"})()
            return type("R", (), {"choices": [choice], "usage": usage})()

    llm = LlmClient(FakeSettings())
    stub_client(llm, Completions())
    step = llm.step((Turn("user", "привет"),), ())
    assert (step.prompt_tokens, step.cached_tokens) == (50, 40)
