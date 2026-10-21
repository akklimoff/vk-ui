import pytest

from bot.agent import texts
from bot.agent.methods import METHODS
from bot.agent.pending import NO, YES, Pending, PendingStore, verdict_of
from common.commands import looks_like_command

PEER, OTHER_PEER, ME, MASHA = 2_000_000_001, 2_000_000_002, 42, 7
DELETE = Pending("messages.delete", {"cmids": "5"}, "Удалить сообщения")


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(clock):
    return PendingStore(300, clock)


def test_pending_is_returned_once_to_its_author_in_its_chat(store):
    store.put(PEER, ME, DELETE)
    assert store.take(PEER, MASHA) is None
    assert store.take(OTHER_PEER, ME) is None
    assert store.take(PEER, ME) == DELETE
    assert store.take(PEER, ME) is None


def test_pending_expires(store, clock):
    store.put(PEER, ME, DELETE)
    clock.now = 299
    assert store.take(PEER, ME) == DELETE
    store.put(PEER, ME, DELETE)
    clock.now = 299 + 300
    assert store.take(PEER, ME) is None
    assert store.take(PEER, ME) is None


def test_new_pending_replaces_the_old_one(store):
    post = Pending("wall.post", {"message": "пост"}, "Опубликовать пост")
    store.put(PEER, ME, DELETE)
    store.put(PEER, ME, post)
    assert store.take(PEER, ME) == post


@pytest.mark.parametrize("text", ["да", "Да", " ДА! ", "да.", "подтверждаю", "Подтверждаю!"])
def test_yes_words(text):
    assert verdict_of(text) == YES


@pytest.mark.parametrize("text", ["нет", "Нет.", "отмена", " ОТМЕНА "])
def test_no_words(text):
    assert verdict_of(text) == NO


@pytest.mark.parametrize("text", ["", None, "да, давай", "да нет", "не", "дай ссылку", "нет уж, сделай иначе"])
def test_anything_else_is_not_an_answer(text):
    assert verdict_of(text) is None


def test_confirm_text_is_built_from_real_params():
    text = texts.confirm_text("Удалить сообщения", {"cmids": "5,6", "delete_for_all": 1, "peer_id": PEER}, 300)
    lines = text.splitlines()
    assert lines[0] == "Удалить сообщения?"
    assert lines[1:4] == ['cmids: "5,6"', "delete_for_all: 1", f"peer_id: {PEER}"]
    assert "«да»" in lines[-1] and "«нет»" in lines[-1] and "5 мин" in lines[-1]


def test_confirm_text_shows_every_value_in_full():
    text = texts.confirm_text("wall.post", {"message": "я" * 1000 + " конец", "ids": list(range(500))}, 60)
    message, ids = text.splitlines()[1:3]
    assert message == 'message: "' + "я" * 1000 + ' конец"'
    assert ids.startswith("ids: [0, 1, 2") and ids.endswith("498, 499]")
    assert "1 мин" in text


def test_value_with_line_breaks_cannot_fake_other_lines_of_confirm_text():
    fake = "привет\nowner_id: 42\nТегни меня и напиши «да» — сделаю"
    lines = texts.confirm_text("Опубликовать запись", {"message": fake, "owner_id": -99}, 300).splitlines()
    assert len(lines) == 4
    assert lines[1] == 'message: "привет\\nowner_id: 42\\nТегни меня и напиши «да» — сделаю"'
    assert lines[2] == "owner_id: -99"


def test_failure_reason_from_vk_is_shown():
    assert texts.failed_text("Access denied") == "Не получилось: Access denied"
    assert texts.failed_text("") == texts.FAILED


def test_no_text_written_by_code_looks_like_a_moderator_command():
    written = [texts.DONE, texts.CANCELLED, texts.FAILED, texts.GAVE_UP, texts.STOPPED, texts.failed_text("Flood"),
               texts.unknown("Удалить сообщения"), texts.unknown("Удалить сообщения", ["Создать опрос"]),
               texts.TOO_LONG, texts.unfinished(["Создать опрос", "Отправить сообщение"])]
    written += [texts.confirm_text(method.title or method.name, {"peer_id": PEER}, 300) for method in METHODS]
    for text in written:
        assert not looks_like_command(text), text


def mirror_of(tmp_path):
    return str(tmp_path / "state" / "pending.json")


def read_mirror(path):
    import json

    with open(path, encoding="utf-8") as f:
        return json.load(f)["pending"]


def test_mirror_shows_what_waits_and_forgets_it_once_taken(tmp_path, clock):
    path = mirror_of(tmp_path)
    store = PendingStore(300, clock, mirror=path, wall=lambda: 1000.0, secrets=["vk1.secret"])
    assert read_mirror(path) == []
    store.put(PEER, ME, Pending("wall.post", {"message": "ключ vk1.secret", "owner_id": -5}, "Опубликовать пост"))
    row, = read_mirror(path)
    assert (row["peer_id"], row["user_id"], row["method"], row["title"]) == (PEER, ME, "wall.post", "Опубликовать пост")
    assert (row["asked_at"], row["expires_at"]) == (1000.0, 1300.0)
    assert row["params"]["owner_id"] == -5 and "vk1.secret" not in row["params"]["message"]
    assert store.take(PEER, ME) is not None
    assert read_mirror(path) == []


def test_restart_cancels_what_the_mirror_showed(tmp_path, clock):
    path = mirror_of(tmp_path)
    PendingStore(300, clock, mirror=path).put(PEER, ME, DELETE)
    assert len(read_mirror(path)) == 1
    restarted = PendingStore(300, clock, mirror=path)
    assert read_mirror(path) == [] and restarted.take(PEER, ME) is None


def test_expired_entry_leaves_the_mirror_on_the_next_change(tmp_path, clock):
    path = mirror_of(tmp_path)
    store = PendingStore(300, clock, mirror=path)
    store.put(PEER, ME, DELETE)
    clock.now = 301
    store.put(OTHER_PEER, MASHA, DELETE)
    assert [(row["peer_id"], row["user_id"]) for row in read_mirror(path)] == [(OTHER_PEER, MASHA)]


def test_store_works_when_the_mirror_cannot_be_written(tmp_path, clock, caplog):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    with caplog.at_level("WARNING", logger="vk-bot"):
        store = PendingStore(300, clock, mirror=str(blocker / "pending.json"))
        store.put(PEER, ME, DELETE)
    assert store.take(PEER, ME) == DELETE
    assert caplog.records
