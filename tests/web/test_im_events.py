import asyncio
import os

from web.im.events import KEEPALIVE, TICK, inbox_events


def collect(path, ticks, touch_at=()):
    out, state = [], {"tick": 0}

    async def disconnected():
        return state["tick"] >= ticks

    async def sleep(_):
        state["tick"] += 1
        if state["tick"] in touch_at:
            os.utime(path, ns=(state["tick"] * 10**9, state["tick"] * 10**9))

    async def run():
        async for chunk in inbox_events(str(path), disconnected, sleep=sleep):
            out.append(chunk)

    asyncio.run(run())
    return out


def test_changed_is_sent_once_per_new_mark(tmp_path):
    path = tmp_path / "inbox.json"
    path.write_text("{}")
    out = collect(path, ticks=6, touch_at=(2, 5))
    assert out[0].startswith("retry:") and out.count("event: changed\ndata: {}\n\n") == 2


def test_quiet_stream_sends_keepalive_comments(tmp_path):
    out = collect(tmp_path / "нет.json", ticks=int(KEEPALIVE / TICK) + 1)
    assert out[1:] == [": ping\n\n"]
