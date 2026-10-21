import httpx
import pytest

from ai.claude import CACHE_POINT, UNSEEN_IMAGES, ClaudeApi, ClaudeError, parse_step, wire_messages, wire_system
from ai.contract import ToolCall, Turn


class Http:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.sent = []

    def post(self, url, json, headers):
        self.sent.append((url, json, headers))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        status, body = answer
        return httpx.Response(status, json=body)


OK = (200, {"content": [{"type": "text", "text": "ок"}], "stop_reason": "end_turn"})


def api(*answers, pauses=None):
    http = Http(*answers)
    sleep = (lambda seconds: None) if pauses is None else pauses.append
    return ClaudeApi("sk-ant", "https://api.anthropic.com/v1/", 1, http=http, sleep=sleep), http


def test_each_system_part_is_a_cache_point_and_empty_parts_are_dropped():
    assert wire_system(("правила", "", "\n\nличность")) == [
        {"type": "text", "text": "правила", "cache_control": CACHE_POINT},
        {"type": "text", "text": "\n\nличность", "cache_control": CACHE_POINT}]


def test_tool_results_and_their_pictures_form_one_user_message_ending_in_a_cache_point():
    call = ToolCall("t1", "vk_api", '{"method": "users.get"}')
    messages = wire_messages((
        Turn("user", "кто это"),
        Turn("assistant", "", (call, ToolCall("t2", "vk_api", "не json"))),
        Turn("tool", "{}", (), "t1"),
        Turn("tool", "[]", (), "t2"),
        Turn("user", "картинки", images=("data:image/jpeg;base64,AAA", "https://не-data-url")),
    ))
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert messages[0]["content"] == [{"type": "text", "text": "кто это"}]
    assert messages[1]["content"] == [
        {"type": "tool_use", "id": "t1", "name": "vk_api", "input": {"method": "users.get"}},
        {"type": "tool_use", "id": "t2", "name": "vk_api", "input": {}}]
    assert messages[2]["content"] == [
        {"type": "tool_result", "tool_use_id": "t1", "content": "{}"},
        {"type": "tool_result", "tool_use_id": "t2", "content": "[]"},
        {"type": "text", "text": "картинки"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "AAA"},
         "cache_control": CACHE_POINT}]


def test_a_model_that_does_not_see_is_told_about_pictures_and_empty_turns_are_skipped():
    turn = Turn("user", "что тут", images=("data:image/png;base64,BBB",))
    assert wire_messages((turn, Turn("assistant", "")), vision=False) == [
        {"role": "user", "content": [{"type": "text", "text": "что тут" + UNSEEN_IMAGES, "cache_control": CACHE_POINT}]}]
    assert wire_messages(()) == []


def test_answer_gives_text_calls_and_tokens_with_the_cached_share():
    body = {"content": [{"type": "thinking", "thinking": "…"}, {"type": "text", "text": " сейчас "},
                        {"type": "tool_use", "id": "t1", "name": "vk_api", "input": {"method": "users.get", "q": "Аня"}}],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 4, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 9000,
                      "output_tokens": 30}}
    step = parse_step(body, "claude-sonnet-5-5")
    assert step.text == "сейчас" and step.finish_reason == "tool_calls" and not step.abnormal
    assert step.tool_calls == (ToolCall("t1", "vk_api", '{"method": "users.get", "q": "Аня"}'),)
    assert (step.prompt_tokens, step.cached_tokens, step.completion_tokens) == (9104, 9000, 30)


@pytest.mark.parametrize("stop, finish, truncated, abnormal", [
    ("end_turn", "stop", False, False), ("max_tokens", "length", True, False),
    ("refusal", "refusal", False, True), ("pause_turn", "pause_turn", False, True), (None, "", False, False)])
def test_stop_reasons_map_onto_the_contract(stop, finish, truncated, abnormal):
    step = parse_step({"content": [], "stop_reason": stop}, "m")
    assert (step.finish_reason, step.truncated, step.abnormal) == (finish, truncated, abnormal)


def test_request_carries_the_key_version_and_only_the_asked_options():
    claude, http = api(OK, OK)
    claude.step("claude-sonnet-5-5", ("правила",), (Turn("user", "привет"),), (), max_tokens=50)
    url, body, headers = http.sent[0]
    assert url == "https://api.anthropic.com/v1/messages"
    assert headers == {"x-api-key": "sk-ant", "anthropic-version": "2023-06-01"}
    assert set(body) == {"model", "max_tokens", "system", "messages"}
    claude.step("m", ("правила",), (Turn("user", "привет"),), (), max_tokens=50, effort="none", temperature=0.4)
    assert "output_config" not in http.sent[1][1] and http.sent[1][1]["temperature"] == 0.4


def test_a_passing_failure_is_retried_once_and_a_lasting_one_is_reported():
    claude, http = api((529, {"error": {"message": "Overloaded"}}), OK)
    assert claude.step("m", (), (Turn("user", "привет"),), (), max_tokens=5).text == "ок"
    assert len(http.sent) == 2

    claude, http = api(httpx.ConnectError("нет сети"), httpx.ConnectError("нет сети"))
    with pytest.raises(ClaudeError, match="недоступен"):
        claude.step("m", (), (Turn("user", "привет"),), (), max_tokens=5)

    claude, http = api((400, {"error": {"message": "temperature is deprecated"}}))
    with pytest.raises(ClaudeError, match="400: temperature is deprecated"):
        claude.step("m", (), (Turn("user", "привет"),), (), max_tokens=5)
    assert len(http.sent) == 1


def test_retry_waits_as_long_as_the_provider_asks_but_not_forever():
    class Limited(Http):
        def post(self, url, json, headers):
            response = super().post(url, json, headers)
            if response.status_code == 429:
                response.headers["retry-after"] = self.wait
            return response

    for asked, waited in (("3", 3.0), ("600", 10.0), ("soon", 1.0)):
        http, pauses = Limited((429, {"error": {"message": "rate limit"}}), OK), []
        http.wait = asked
        claude = ClaudeApi("sk-ant", "https://api.anthropic.com/v1", 1, http=http, sleep=pauses.append)
        assert claude.step("m", (), (Turn("user", "привет"),), (), max_tokens=5).text == "ок"
        assert pauses == [waited]

    pauses = []
    claude, _ = api(httpx.ConnectError("нет сети"), OK, pauses=pauses)
    claude.step("m", (), (Turn("user", "привет"),), (), max_tokens=5)
    assert pauses == [1.0]


def test_thinking_is_sent_only_when_asked():
    claude, http = api(OK, OK)
    claude.step("m", (), (Turn("user", "привет"),), (), max_tokens=5, thinking="between_tools")
    claude.step("m", (), (Turn("user", "привет"),), (), max_tokens=5)
    assert http.sent[0][1]["thinking"] == {"type": "between_tools"} and "thinking" not in http.sent[1][1]


def test_thinking_blocks_of_the_answer_are_not_taken_for_text():
    step = parse_step({"content": [{"type": "thinking", "thinking": "прикину", "signature": "s"},
                                   {"type": "text", "text": "ок"}], "stop_reason": "end_turn"}, "m")
    assert step.text == "ок" and step.tool_calls == ()


@pytest.mark.parametrize("body", [{"content": [{"type": "tool_use", "name": "vk_api"}]}, {"content": "текст"}, []])
def test_an_answer_of_unknown_shape_is_a_provider_error(body):
    claude, _ = api((200, body))
    with pytest.raises(ClaudeError, match="непонятного вида"):
        claude.step("m", (), (Turn("user", "привет"),), (), max_tokens=5)


def test_a_successful_answer_that_is_not_json_is_a_provider_error():
    class Html(Http):
        def post(self, url, json, headers):
            return httpx.Response(200, text="<html>шлюз</html>")

    claude = ClaudeApi("sk-ant", "https://api.anthropic.com/v1", 1, http=Html())
    with pytest.raises(ClaudeError, match="непонятного вида"):
        claude.step("m", (), (Turn("user", "привет"),), (), max_tokens=5)
