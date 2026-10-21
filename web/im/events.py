import asyncio

TICK = 0.5
KEEPALIVE = 25.0


async def inbox_events(version, disconnected, sleep=asyncio.sleep, healthy=lambda: True):
    """SSE: «changed», как только long poll панели увидел новое в переписке.
    Комментарий раз в KEEPALIVE секунд не даёт прокси закрыть тихое соединение. Пока long poll без связи, поток
    закрывается: браузер переподключается, а до тех пор мессенджер опрашивает VK сам и часто."""
    seen = version()
    quiet = 0.0
    yield "retry: 3000\n\n"
    while not await disconnected():
        await sleep(TICK)
        if not healthy():
            return
        now = version()
        if now != seen:
            seen, quiet = now, 0.0
            yield "event: changed\ndata: {}\n\n"
        else:
            quiet += TICK
            if quiet >= KEEPALIVE:
                quiet = 0.0
                yield ": ping\n\n"
