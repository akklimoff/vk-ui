import threading

import pytest

from web.im.live import Inbox


class Stop(BaseException):
    pass


def test_long_poll_bumps_the_version_on_changes_and_survives_a_failure():
    batches = iter([2, "сбой", 1])
    pauses = []

    def listen(changed, polled):
        batch = next(batches)
        if batch == "сбой":
            raise ConnectionError("нет сети")
        for _ in range(batch):
            changed()
            yield None

    def sleep(seconds):
        pauses.append(seconds)
        if len(pauses) == 3:
            raise Stop

    inbox = Inbox(listen, retry=7.0, sleep=sleep)
    with pytest.raises(Stop):
        inbox._run()
    assert inbox.version() == 3 and pauses == [7.0, 7.0, 7.0]


def test_long_poll_starts_once_for_any_number_of_subscribers():
    entered = threading.Event()
    calls = []

    def listen(changed, polled):
        calls.append(1)
        entered.set()
        threading.Event().wait()
        yield from ()

    inbox = Inbox(listen)
    for _ in range(5):
        inbox.start()
    assert entered.wait(1) and calls == [1] and inbox._thread.daemon


def test_long_poll_is_healthy_while_vk_answers_and_stale_after_silence():
    clock = [0.0]
    inbox = Inbox(lambda changed, polled: iter(()), sleep=lambda _: threading.Event().wait(), now=lambda: clock[0])
    assert not inbox.healthy()
    inbox.start()
    clock[0] = 80.0
    assert inbox.healthy()
    clock[0] = 100.0
    assert not inbox.healthy()
    inbox.polled()
    assert inbox.healthy()


def test_the_app_wires_its_long_poll_to_vk(settings):
    from fastapi.testclient import TestClient

    from tests.web.fakes import FakeVk
    from web.app import create_app

    bumped = threading.Event()

    class ListeningVk(FakeVk):
        def listen(self, polled=None, changed=None):
            polled()
            changed()
            bumped.set()
            threading.Event().wait()
            yield from ()

    client = TestClient(create_app(settings, vk_factory=ListeningVk))
    client.app.state.inbox.start()
    assert bumped.wait(1) and client.app.state.inbox.version() == 1 and client.app.state.inbox.healthy()
