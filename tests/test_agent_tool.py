import pytest

from bot.agent.gate import CHAT, OWNER, SAVED, TRUSTED, Caller
from bot.agent.methods import METHODS
from bot.agent.tool import TOOL_NAME, describe, parse_call


def test_trusted_person_is_offered_the_same_methods_as_the_owner():
    spec = describe(Caller(CHAT, TRUSTED))
    assert spec.name == TOOL_NAME == "vk_api"
    assert "messages.getInviteLink(peer_id, reset)" in spec.description and "messages.pin(" in spec.description
    assert "wall.post(" in spec.description and "messages.delete(" in spec.description
    assert spec == describe(Caller(CHAT, OWNER))
    assert spec.parameters["required"] == ["method"]


def test_both_places_are_offered_any_method_and_the_same_table():
    in_chat = describe(Caller(CHAT, OWNER)).description
    in_saved = describe(Caller(SAVED, OWNER)).description
    for text in (in_chat, in_saved):
        assert "любой метод VK API, кроме запрещённых" in text
        assert "wall.post(" in text and "friends.get(" in text and "likes.add(" in text
        assert "messages.searchConversations(" in text
    assert in_chat.splitlines()[4:] == in_saved.splitlines()[4:]


def test_valid_arguments_give_method_and_params():
    assert parse_call('{"method": "users.get", "params": {"user_ids": "1"}}') == ("users.get", {"user_ids": "1"})
    assert parse_call('{"method": "messages.unpin"}') == ("messages.unpin", {})
    assert parse_call('{"method": "messages.unpin", "params": null}') == ("messages.unpin", {})
    assert parse_call('{"method": "users.get", "params": "{\\"user_ids\\": \\"1\\"}"}') == ("users.get", {"user_ids": "1"})


@pytest.mark.parametrize("arguments", ["", "не json", "[]", '"строка"', '{"params": {}}', '{"method": 5}',
                                       '{"method": "users.get", "params": [1]}',
                                       '{"method": "users.get", "params": "не json"}',
                                       '{"method": "users.get", "params": "[1]"}'])
def test_broken_arguments_give_an_error_text_for_the_model(arguments):
    assert isinstance(parse_call(arguments), str)


def test_every_row_shows_its_parameters_and_its_address():
    lines = describe(Caller(CHAT, TRUSTED)).description.splitlines()
    for method in METHODS:
        line = next(text for text in lines if text.startswith(f"- {method.name}("))
        shown = set(line.partition("(")[2].partition(")")[0].split(", ")) - {""}
        assert shown == method.params | ({method.peer_param, method.chat_param} - {""}), line
        assert " — " in line, line


def test_a_chat_caller_is_told_that_a_call_without_an_address_means_this_chat():
    in_chat = describe(Caller(CHAT, TRUSTED)).description
    assert "подставится эта беседа" in in_chat and "личный диалог" in in_chat and "другой беседы" in in_chat
    assert "только методы из списка" not in in_chat and "недоступн" not in in_chat
    in_saved = describe(Caller(SAVED, OWNER)).description
    assert "подставится эта беседа" not in in_saved and "называй всегда сама" in in_saved
