import json

from bot.agent import gate
from bot.agent.rejections import QUEUE_FULL, RATE_LIMITED, Rejection, RejectionLog, read_rejections

PEER, OTHER_PEER, MASHA, STRANGER = 2_000_000_001, 2_000_000_002, 7, 9


class Clock:
    now = 1000.0

    def __call__(self):
        return self.now


def make(tmp_path, **kw):
    clock = Clock()
    path = str(tmp_path / "state" / "rejections.json")
    return RejectionLog(path, now=clock, **kw), path, clock


def test_same_rejection_is_one_row_with_a_counter(tmp_path):
    log, path, clock = make(tmp_path)
    log.note(PEER, STRANGER, gate.USER_NOT_TRUSTED)
    clock.now = 1010.0
    log.note(PEER, STRANGER, gate.USER_NOT_TRUSTED)
    log.note(OTHER_PEER, MASHA, gate.CHAT_NOT_TRUSTED)
    log.flush(force=True)
    assert read_rejections(path) == [Rejection(1010.0, PEER, STRANGER, gate.USER_NOT_TRUSTED, 2),
                                     Rejection(1010.0, OTHER_PEER, MASHA, gate.CHAT_NOT_TRUSTED, 1)]


def test_only_the_newest_rows_are_kept(tmp_path):
    log, path, clock = make(tmp_path, keep=2)
    for step, peer in enumerate((PEER, OTHER_PEER, PEER + 5)):
        clock.now = 1000.0 + step
        log.note(peer, STRANGER, gate.CHAT_NOT_TRUSTED)
    log.flush(force=True)
    assert [r.peer_id for r in read_rejections(path)] == [PEER + 5, OTHER_PEER]


def test_disk_is_touched_at_most_once_per_interval(tmp_path):
    log, path, clock = make(tmp_path)
    log.note(PEER, STRANGER, gate.USER_NOT_TRUSTED)
    log.flush()
    assert len(read_rejections(path)) == 1
    log.note(OTHER_PEER, STRANGER, gate.CHAT_NOT_TRUSTED)
    log.flush()
    assert len(read_rejections(path)) == 1
    clock.now += 6
    log.flush()
    assert len(read_rejections(path)) == 2


def test_nothing_new_means_no_write(tmp_path):
    log, path, clock = make(tmp_path)
    log.flush(force=True)
    assert read_rejections(path) == [] and not (tmp_path / "state").exists()


def test_rows_survive_a_restart(tmp_path):
    log, path, clock = make(tmp_path)
    log.note(PEER, STRANGER, gate.USER_NOT_TRUSTED)
    log.flush(force=True)
    again = RejectionLog(path, now=clock)
    again.note(PEER, STRANGER, gate.USER_NOT_TRUSTED)
    again.flush(force=True)
    assert read_rejections(path)[0].count == 2


def test_event_without_a_sender_is_stored_with_zero(tmp_path):
    log, path, clock = make(tmp_path)
    log.note(PEER, None, gate.NO_SENDER)
    log.flush(force=True)
    assert read_rejections(path) == [Rejection(1000.0, PEER, 0, gate.NO_SENDER, 1)]


def test_requests_dropped_after_the_gate_are_kept_too(tmp_path):
    log, path, clock = make(tmp_path)
    log.note(PEER, MASHA, RATE_LIMITED)
    clock.now = 1001.0
    log.note(PEER, MASHA, QUEUE_FULL)
    log.flush(force=True)
    assert [row.reason for row in read_rejections(path)] == [QUEUE_FULL, RATE_LIMITED]


def test_garbage_rows_and_unknown_reasons_are_skipped(tmp_path):
    path = tmp_path / "rejections.json"
    path.write_text(json.dumps({"rejections": [
        {"ts": 5, "peer_id": PEER, "from_id": 9, "reason": gate.PAUSED},
        {"ts": 6, "peer_id": PEER, "from_id": 9, "reason": "текст сообщения"},
        {"ts": "вчера", "peer_id": PEER, "from_id": 9, "reason": gate.PAUSED},
        "строка", None,
    ]}))
    assert read_rejections(str(path)) == [Rejection(5.0, PEER, 9, gate.PAUSED, 1)]
    path.write_text("[1, 2]")
    assert read_rejections(str(path)) == []
    path.write_text("{не json")
    assert read_rejections(str(path)) == []
    assert read_rejections(str(tmp_path / "nope.json")) == []


def test_unwritable_path_is_only_logged(tmp_path, caplog):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    log = RejectionLog(str(blocker / "rejections.json"))
    log.note(PEER, STRANGER, gate.USER_NOT_TRUSTED)
    with caplog.at_level("WARNING", logger="vk-bot"):
        log.flush(force=True)
    assert caplog.records


def test_rows_of_a_failed_write_are_written_next_time(tmp_path):
    log, path, clock = make(tmp_path)
    blocker = tmp_path / "state"
    blocker.write_text("не каталог")
    log.note(PEER, STRANGER, gate.USER_NOT_TRUSTED)
    log.flush(force=True)
    blocker.unlink()
    log.flush(force=True)
    assert len(read_rejections(path)) == 1
