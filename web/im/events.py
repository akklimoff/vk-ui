import asyncio
import json

TICK = 0.5
KEEPALIVE = 25.0


def changed_event(peers) -> str:
    """peers: null — изменилось неизвестно что, браузер перечитывает и открытый чат, и список."""
    return f"event: changed\ndata: {json.dumps({'peers': None if peers is None else sorted(peers)})}\n\n"


async def inbox_events(changes, disconnected, sleep=asyncio.sleep, healthy=lambda: True, version=None):
    """SSE: «changed» с чатами, в которых long poll панели увидел новое, — как только увидел.
    `changes(since)` отдаёт текущую версию и чаты, изменившиеся после since (None — неизвестно какие).
    Комментарий раз в KEEPALIVE секунд не даёт прокси закрыть тихое соединение. Пока long poll без связи, поток
    закрывается: браузер переподключается, а до тех пор мессенджер опрашивает VK сам и часто."""
    seen = version() if version else changes(-1)[0]
    quiet = 0.0
    yield "retry: 3000\n\n"
    while not await disconnected():
        await sleep(TICK)
        if not healthy():
            return
        now, peers = changes(seen)
        if now != seen:
            seen, quiet = now, 0.0
            yield changed_event(peers)
        else:
            quiet += TICK
            if quiet >= KEEPALIVE:
                quiet = 0.0
                yield ": ping\n\n"
