import asyncio
import os

TICK = 0.5
KEEPALIVE = 25.0


def stamp(path: str) -> int:
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return 0


async def inbox_events(path: str, disconnected, sleep=asyncio.sleep):
    """SSE: «changed», как только бот отметил новое в state/inbox.json. Сам файл не читается — хватает mtime.
    Комментарий раз в KEEPALIVE секунд не даёт прокси закрыть тихое соединение."""
    seen = stamp(path)
    quiet = 0.0
    yield "retry: 3000\n\n"
    while not await disconnected():
        await sleep(TICK)
        now = stamp(path)
        if now != seen:
            seen, quiet = now, 0.0
            yield "event: changed\ndata: {}\n\n"
        else:
            quiet += TICK
            if quiet >= KEEPALIVE:
                quiet = 0.0
                yield ": ping\n\n"
