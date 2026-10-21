import json

from bot.status import StatusWriter, read_json, write_json_atomic


def test_write_json_atomic_creates_dirs(tmp_path):
    p = tmp_path / "s" / "status.json"
    write_json_atomic(str(p), {"a": 1})
    assert json.loads(p.read_text()) == {"a": 1}
    assert read_json(str(tmp_path / "nope.json"), {}) == {}


def test_status_writer_throttles_and_counts_errors(tmp_path):
    clock = [1000.0]
    path = str(tmp_path / "status.json")
    sw = StatusWriter(path, 1, "Валя", now=lambda: clock[0])
    sw.flush(force=True)
    sw.error()
    sw.event()
    sw.flush()
    assert read_json(path, {})["errors_last_hour"] == 0
    clock[0] += 6
    sw.flush()
    data = read_json(path, {})
    assert data["errors_last_hour"] == 1 and data["last_event_at"] == 1000.0
    clock[0] += 3601
    sw.flush(force=True)
    assert read_json(path, {})["errors_last_hour"] == 0


def test_status_starts_without_a_model_and_takes_it_from_the_worker(tmp_path):
    path = str(tmp_path / "status.json")
    sw = StatusWriter(path, 1, "Валя")
    sw.flush(force=True)
    assert read_json(path, {})["model"] == "" and "provider" not in read_json(path, {})
    sw.set_model("claude-sonnet-5-5")
    sw.set_model("")
    sw.flush(force=True)
    assert read_json(path, {})["model"] == "claude-sonnet-5-5"


def test_reply_log_of_the_old_path_is_gone():
    import importlib.util

    import bot.status

    assert not hasattr(bot.status, "ReplyLog") and not hasattr(bot.status, "ReplyRecord")
    assert importlib.util.find_spec("bot.timing") is None and importlib.util.find_spec("bot.latency") is None


def test_every_flush_is_a_heartbeat_and_a_poll_is_remembered(tmp_path):
    clock = [1000.0]
    path = str(tmp_path / "status.json")
    sw = StatusWriter(path, 1, "Валя", now=lambda: clock[0])
    sw.flush(force=True)
    assert (read_json(path, {})["heartbeat_at"], read_json(path, {})["last_poll_at"]) == (1000.0, None)
    clock[0] = 1003.0
    sw.polled()
    clock[0] = 1010.0
    sw.flush()
    data = read_json(path, {})
    assert (data["heartbeat_at"], data["last_poll_at"], data["last_event_at"]) == (1010.0, 1003.0, None)


def test_a_status_that_cannot_be_written_does_not_stop_the_bot(tmp_path, caplog):
    blocker = tmp_path / "state"
    blocker.write_text("не каталог")
    sw = StatusWriter(str(blocker / "status.json"), 1, "Валя")
    with caplog.at_level("WARNING", logger="vk-bot"):
        sw.flush(force=True)
    assert len(caplog.records) == 1
