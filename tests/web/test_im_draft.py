from ai.context import Line
from bot.access import AccessLists
from bot.runtime import RuntimeSettings
from tests.web.im_fixtures import HISTORY, ME, PEER_CHAT
from tests.web.fakes import FakeAi
from web.im.draft import draft_reply


class Vk:
    me_id = ME

    def history(self, peer_id, count):
        return HISTORY["items"]

    def resolve_name(self, uid):
        return {11: "Вася Пупкин", 22: "Аня Иванова"}.get(uid, "Кто-то")


def test_draft_uses_chat_persona_layers_and_last_speaker(settings):
    ai = FakeAi(parts=("ну и ладно",))
    lists = AccessLists(auto_reply_peers=frozenset({PEER_CHAT}), peer_prompts={PEER_CHAT: "тут все свои"}, chat_prompt="беседа")
    rt = RuntimeSettings(active_persona="valentina", peer_personas=((PEER_CHAT, ("rina",)),), temperature=0.5)
    text = draft_reply(settings, ai, Vk(), lists, rt, PEER_CHAT)
    assert text == "ну и ладно"
    req = ai.requests[-1]
    assert req.asker == "Вася Пупкин" and Line("", "ну все тогда", True) in req.lines
    assert req.persona == "rina" and req.user_prompt == "тут все свои" and req.scope_prompt == "беседа"
    assert req.auto_chat and not req.is_private and req.temperature == 0.5

def test_draft_joins_split_parts_and_survives_chat_without_other_speakers(settings):
    class OnlyMe(Vk):
        def history(self, peer_id, count):
            return [m for m in HISTORY["items"] if m["from_id"] == ME]

        def resolve_name(self, uid):
            assert uid != PEER_CHAT, "id беседы не пользователь"
            return super().resolve_name(uid)

    ai = FakeAi(parts=("раз", "два"))
    text = draft_reply(settings, ai, OnlyMe(), AccessLists(), RuntimeSettings(), PEER_CHAT)
    assert text == "раз\nдва"
    assert ai.requests[-1].asker == "Собеседник" and not ai.requests[-1].auto_chat
