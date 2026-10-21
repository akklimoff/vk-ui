import asyncio

from web.im.events import KEEPALIVE, TICK, inbox_events


def collect(ticks, bump_at=()):
    out, state = [], {"tick": 0, "version": 0}

    async def disconnected():
        return state["tick"] >= ticks

    async def sleep(_):
        state["tick"] += 1
        if state["tick"] in bump_at:
            state["version"] += 1

    async def run():
        async for chunk in inbox_events(lambda: state["version"], disconnected, sleep=sleep):
            out.append(chunk)

    asyncio.run(run())
    return out


def test_changed_is_sent_once_per_new_version():
    out = collect(ticks=6, bump_at=(2, 5))
    assert out[0].startswith("retry:") and out.count("event: changed\ndata: {}\n\n") == 2


def test_quiet_stream_sends_keepalive_comments():
    out = collect(ticks=int(KEEPALIVE / TICK) + 1)
    assert out[1:] == [": ping\n\n"]


def test_stream_closes_while_long_poll_has_no_connection():
    state = {"tick": 0}

    async def disconnected():
        return state["tick"] >= 100

    async def sleep(_):
        state["tick"] += 1

    async def run():
        return [chunk async for chunk in inbox_events(lambda: 0, disconnected, sleep=sleep, healthy=lambda: state["tick"] < 3)]

    assert asyncio.run(run()) == ["retry: 3000\n\n"] and state["tick"] == 3
