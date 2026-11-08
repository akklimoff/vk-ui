import threading
import time

from web.pace import Pace, background


def test_starts_beyond_the_rate_wait_for_the_window():
    pace = Pace(rate=2, window=0.2)
    started = time.monotonic()
    for _ in range(3):
        pace.acquire()
    assert time.monotonic() - started >= 0.19


def test_requests_run_in_parallel_within_the_rate():
    pace = Pace(rate=3, window=1.0)
    started = time.monotonic()
    threads = [threading.Thread(target=pace.acquire) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert time.monotonic() - started < 0.1


def test_background_requests_yield_to_a_waiting_user_request():
    pace = Pace(rate=2, window=0.3)
    pace.acquire()
    pace.acquire()
    order = []

    def bg():
        with background():
            pace.acquire()
        order.append("фон")

    def user():
        pace.acquire()
        order.append("щелчок")

    first = threading.Thread(target=bg)
    first.start()
    time.sleep(0.05)
    second = threading.Thread(target=user)
    second.start()
    first.join()
    second.join()
    assert order == ["щелчок", "фон"]


def test_background_leaves_a_slot_for_the_user():
    pace = Pace(rate=3, window=10.0)
    with background():
        pace.acquire()
        pace.acquire()
    started = time.monotonic()
    pace.acquire()
    assert time.monotonic() - started < 0.1
