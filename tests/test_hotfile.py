import os
import threading
import time

from common.hotfile import RETRY_SECONDS, PartialRead, WatchedFile


def touch_later(p):
    os.utime(p, (time.time() + 10, time.time() + 10))


def test_returns_default_when_file_missing(tmp_path):
    wf = WatchedFile(str(tmp_path / "x.json"), parse=str.upper, default="DEF", log_label="x")
    assert wf.current() == "DEF"


def test_rereads_on_mtime_change(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("a")
    wf = WatchedFile(str(p), parse=str.upper, default="", log_label="x")
    assert wf.current() == "A"
    p.write_text("b")
    touch_later(p)
    assert wf.current() == "B"


def test_keeps_previous_value_on_parse_error(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("1")
    wf = WatchedFile(str(p), parse=int, default=0, log_label="x")
    assert wf.current() == 1
    p.write_text("oops")
    touch_later(p)
    assert wf.current() == 1


class Clock:
    now = 1000.0

    def __call__(self):
        return self.now


def test_failed_parse_is_retried_after_a_pause_without_a_new_write(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("1")
    attempts = []
    vk_is_down = [False]

    def parse(text):
        attempts.append(text)
        if vk_is_down[0]:
            raise RuntimeError("VK недоступен")
        return int(text)

    clock = Clock()
    wf = WatchedFile(str(p), parse=parse, default=0, log_label="x", clock=clock)
    assert wf.current() == 1
    p.write_text("2")
    touch_later(p)
    vk_is_down[0] = True
    assert wf.current() == 1 and wf.current() == 1
    assert attempts == ["1", "2"]
    vk_is_down[0] = False
    assert wf.current() == 1
    clock.now += RETRY_SECONDS
    assert wf.current() == 2


def test_partial_read_takes_effect_at_once_and_is_retried_after_a_pause(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("1")
    vk_is_down = [False]

    def parse(text):
        if vk_is_down[0]:
            raise PartialRead(-int(text))
        return int(text)

    clock = Clock()
    wf = WatchedFile(str(p), parse=parse, default=0, log_label="x", clock=clock)
    assert wf.current() == 1
    p.write_text("2")
    touch_later(p)
    vk_is_down[0] = True
    assert wf.current() == -2
    vk_is_down[0] = False
    assert wf.current() == -2
    clock.now += RETRY_SECONDS
    assert wf.current() == 2


def test_reader_waits_for_a_reload_in_progress_instead_of_taking_the_old_value(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("1")
    entered, release = threading.Event(), threading.Event()

    def parse(text):
        if text == "2":
            entered.set()
            release.wait(5)
        return int(text)

    wf = WatchedFile(str(p), parse=parse, default=0, log_label="x")
    assert wf.current() == 1
    p.write_text("2")
    touch_later(p)
    reloading = threading.Thread(target=wf.current)
    reloading.start()
    assert entered.wait(5)
    seen = []
    reader = threading.Thread(target=lambda: seen.append(wf.current()))
    reader.start()
    reader.join(0.2)
    early = list(seen)
    release.set()
    reloading.join(5)
    reader.join(5)
    assert early == [] and seen == [2]


def test_falls_back_to_default_when_file_removed(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("1")
    wf = WatchedFile(str(p), parse=int, default=0, log_label="x")
    assert wf.current() == 1
    p.unlink()
    assert wf.current() == 0


def test_rereads_a_replaced_file_even_when_its_mtime_is_the_same(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("a")
    wf = WatchedFile(str(p), parse=str.upper, default="", log_label="x")
    assert wf.current() == "A"
    before = os.stat(p)
    p.write_text("bb")
    os.utime(p, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert wf.current() == "BB"
