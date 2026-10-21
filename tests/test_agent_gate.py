import pytest

from bot.agent import gate
from bot.agent.gate import CHAT, OWNER, SAVED, TRUSTED, Caller, admit

ME, MASHA, STRANGER = 42, 7, 9
CHAT_PEER, OTHER_PEER = 2_000_000_001, 2_000_000_002
TAG = f"[id{ME}|@aktan]"


def ask(text=f"{TAG} дай ссылку", peer_id=CHAT_PEER, from_id=MASHA, **kw):
    kw.setdefault("agent_users", frozenset({MASHA}))
    kw.setdefault("agent_peers", frozenset({CHAT_PEER}))
    return admit(text, peer_id, from_id, ME, **kw)


def test_trusted_user_in_trusted_chat_is_admitted():
    assert ask() == Caller(CHAT, TRUSTED)


def test_owner_in_trusted_chat_is_admitted_as_owner():
    assert ask(from_id=ME) == Caller(CHAT, OWNER)


def test_owner_in_saved_messages_needs_no_lists():
    assert ask(peer_id=ME, from_id=ME, agent_users=frozenset(), agent_peers=frozenset()) == Caller(SAVED, OWNER)


@pytest.mark.parametrize("kw", [
    {"text": "дай ссылку"},
    {"text": f"[id{MASHA}|@masha] дай ссылку"},
    {"text": None},
    {"text": f"/help {TAG}"},
    {"from_id": STRANGER},
    {"from_id": -5},
    {"from_id": None},
    {"peer_id": OTHER_PEER},
    {"peer_id": MASHA},
    {"paused": True},
    {"paused_peers": frozenset({CHAT_PEER})},
], ids=["нет тега", "чужой тег", "нет текста", "слеш", "недоверенный", "сообщество", "нет автора",
        "недоверенная беседа", "личка доверенного", "пауза", "пауза беседы"])
def test_everything_else_is_dropped(kw):
    assert ask(**kw) is None


def test_owner_outside_trusted_places_is_dropped():
    assert ask(from_id=ME, peer_id=OTHER_PEER) is None
    assert ask(from_id=ME, peer_id=MASHA) is None


def test_private_dialog_listed_as_trusted_chat_is_still_dropped():
    assert ask(peer_id=MASHA, agent_peers=frozenset({MASHA})) is None


def test_pause_silences_the_owner_in_saved_messages_too():
    assert ask(peer_id=ME, from_id=ME, paused=True) is None


def why(text=f"{TAG} дай ссылку", peer_id=CHAT_PEER, from_id=MASHA, **kw):
    kw.setdefault("agent_users", frozenset({MASHA}))
    kw.setdefault("agent_peers", frozenset({CHAT_PEER}))
    return gate.rejection(text, peer_id, from_id, ME, **kw)


REASONS = {
    "нет тега": ({"text": "дай ссылку"}, gate.NO_TAG),
    "чужой тег": ({"text": f"[id{MASHA}|@masha] дай ссылку"}, gate.NO_TAG),
    "нет текста": ({"text": None}, gate.NO_TAG),
    "слеш": ({"text": f"/help {TAG}"}, gate.ADDRESSED_TO_BOTS),
    "недоверенный": ({"from_id": STRANGER}, gate.USER_NOT_TRUSTED),
    "сообщество": ({"from_id": -5}, gate.COMMUNITY_SENDER),
    "нет автора": ({"from_id": None}, gate.NO_SENDER),
    "недоверенная беседа": ({"peer_id": OTHER_PEER}, gate.CHAT_NOT_TRUSTED),
    "владелец в недоверенной беседе": ({"peer_id": OTHER_PEER, "from_id": ME}, gate.CHAT_NOT_TRUSTED),
    "личка доверенного": ({"peer_id": MASHA}, gate.PRIVATE_DIALOG),
    "личка в списке бесед": ({"peer_id": MASHA, "agent_peers": frozenset({MASHA})}, gate.PRIVATE_DIALOG),
    "чужой в избранном": ({"peer_id": ME}, gate.PRIVATE_DIALOG),
    "пауза": ({"paused": True}, gate.PAUSED),
    "пауза беседы": ({"paused_peers": frozenset({CHAT_PEER})}, gate.PAUSED),
}


@pytest.mark.parametrize("kw, reason", REASONS.values(), ids=REASONS.keys())
def test_rejection_names_the_reason(kw, reason):
    assert why(**kw) == reason
    assert ask(**kw) is None


def test_admitted_request_has_no_rejection():
    assert why() is None
    assert why(from_id=ME) is None
    assert why(peer_id=ME, from_id=ME, agent_users=frozenset(), agent_peers=frozenset()) is None


def test_reasons_are_distinct():
    assert len(set(gate.REASONS)) == len(gate.REASONS) == 8


@pytest.mark.parametrize("text, called", [
    ("Валентина, дай ссылку", True), ("дай ссылку Валентина", True), ("Валентина", True), ("(Валентина)", True),
    ("валентина, дай ссылку", False), ("ВАЛЕНТИНА", False), ("Валя", False), ("Валентину", False),
    ("Валентинка", False), ("НеВалентина", False), ("Валентина_2", False), ("", False), (None, False),
])
def test_the_name_calls_only_as_a_separate_word_in_its_exact_spelling(text, called):
    assert gate.called_by_name(text, "Валентина") is called
    assert (ask(text, names=("Моника", "Валентина")) is not None) is called


def test_an_empty_name_calls_nobody_and_a_name_with_signs_is_taken_literally():
    assert not gate.called_by_name("привет всем", "")
    assert gate.called_by_name("эй, А.Б*, глянь", "А.Б*") and not gate.called_by_name("эй, АхБ, глянь", "А.Б*")


def test_the_name_works_in_saved_messages_and_gives_no_rights_to_a_stranger():
    assert ask("Валентина, запиши", peer_id=ME, from_id=ME, names=("Валентина",)) == Caller(SAVED, OWNER)
    assert ask("Валентина, кикни", from_id=STRANGER, names=("Валентина",)) is None
    assert ask("Валентина, кикни", peer_id=OTHER_PEER, names=("Валентина",)) is None
    assert gate.rejection("Валентина, кикни", CHAT_PEER, STRANGER, ME, frozenset({MASHA}), frozenset({CHAT_PEER}),
                          names=("Валентина",)) == gate.USER_NOT_TRUSTED


def test_a_reply_to_the_account_calls_in_a_trusted_chat_only():
    assert ask("а подробнее?", reply_to_me=True) == Caller(CHAT, TRUSTED)
    assert ask("а подробнее?", from_id=ME, reply_to_me=True) == Caller(CHAT, OWNER)
    assert ask("а подробнее?") is None
    assert ask("а подробнее?", from_id=STRANGER, reply_to_me=True) is None
    assert ask("а подробнее?", peer_id=OTHER_PEER, reply_to_me=True) is None
    assert ask("заметка", peer_id=ME, from_id=ME, reply_to_me=True) is None
    assert ask("а подробнее?", peer_id=MASHA, reply_to_me=True) is None
    assert ask("/кик", reply_to_me=True) is None
    assert ask("а подробнее?", reply_to_me=True, paused=True) is None


@pytest.mark.parametrize("text", ["[id555|Валентина] привет", "[id555|@Валентина], глянь", "[club7|Валентина] что нового"])
def test_a_tag_of_someone_else_with_the_same_name_does_not_call_the_agent(text):
    assert not gate.called_by_name(text, "Валентина")
    assert gate.called_by_name(text + " Валентина, а ты?", "Валентина")


def test_names_are_taken_out_of_a_text_with_the_punctuation_around_them():
    assert gate.without_names("Валентина, да", ["Валентина"]) == "да"
    assert gate.without_names("да, Моника", ["Валентина", "Моника", ""]) == "да"
    assert gate.without_names("Валентинада", ["Валентина"]) == "Валентинада"
