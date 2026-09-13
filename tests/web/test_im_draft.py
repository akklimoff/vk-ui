from bot.access import AccessLists
from bot.runtime import RuntimeSettings
from tests.web.im_fixtures import HISTORY, ME, PEER_CHAT
from web.im.draft import draft_reply


class Llm:
    def __init__(self):
        self.calls = []

    def reply(self, conversation, asker, **kw):
        self.calls.append((conversation, asker, kw))
        return "ну и ладно"


class Vk:
    me_id = ME

    def history(self, peer_id, count):
        return HISTORY["items"]

    def resolve_name(self, uid):
        return {11: "Вася Пупкин", 22: "Аня Иванова"}.get(uid, "Кто-то")


def test_draft_uses_chat_persona_layers_and_last_speaker(settings):
    open(f"{settings.personas_dir}/rina.md", "w").write("# Рина\nты рина")
    llm = Llm()
    lists = AccessLists(auto_reply_peers=frozenset({PEER_CHAT}), peer_prompts={PEER_CHAT: "тут все свои"}, chat_prompt="беседа")
    rt = RuntimeSettings(active_persona="valentina", peer_personas=((PEER_CHAT, ("rina",)),), temperature=0.5)
    text = draft_reply(settings, llm, Vk(), lists, rt, PEER_CHAT)
    assert text == "ну и ладно"
    conversation, asker, kw = llm.calls[-1]
    assert asker == "Вася Пупкин" and "Ты: ну все тогда" in conversation
    assert kw["persona_prompt"] == "ты рина" and kw["user_prompt"] == "тут все свои" and kw["private_prompt"] == "беседа"
    assert kw["auto_chat"] and not kw["is_private"] and kw["temperature"] == 0.5
    assert kw["own_recent"] == ["ну все тогда"]


def test_draft_joins_split_parts_and_survives_chat_without_other_speakers(settings):
    class OnlyMe(Vk):
        def history(self, peer_id, count):
            return [m for m in HISTORY["items"] if m["from_id"] == ME]

        def resolve_name(self, uid):
            assert uid != PEER_CHAT, "id беседы не пользователь"
            return super().resolve_name(uid)

    llm = Llm()
    llm.reply = lambda conversation, asker, **kw: llm.calls.append((conversation, asker, kw)) or "раз ||| два"
    text = draft_reply(settings, llm, OnlyMe(), AccessLists(), RuntimeSettings(), PEER_CHAT)
    assert text == "раз\nдва"
    assert llm.calls[-1][1] == "Собеседник" and not llm.calls[-1][2]["auto_chat"]
