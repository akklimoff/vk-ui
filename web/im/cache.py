import threading
import time
from collections import OrderedDict

# полная сверка списка с VK: ловит то, о чём long poll не сообщает (удаление последнего сообщения, новые аватары)
FULL_TTL = 300.0
# long poll без связи — событий нет, и список перечитывается по времени, как до кэша
BLIND_TTL = 10.0
VK_PAGE = 200
HISTORY_TTL = 300.0
HISTORY_KEEP = 30
# getConversationsById и getById берут не больше 100 id
CHANGED_MAX = 100
# ответ, взятый у VK в первые секунды после события, мог его ещё не учесть: такой перечитывается ещё раз
LAG = 3.0


def peer_of_item(item: dict) -> int:
    return item["conversation"]["peer"]["id"]


def sort_key(item: dict) -> tuple[int, int]:
    """Порядок списка VK: закреплённые по major_id, остальные по id последнего сообщения — оба по убыванию."""
    conv = item["conversation"]
    sort = conv.get("sort_id") or {}
    return int(sort.get("major_id") or 0), int(sort.get("minor_id") or conv.get("last_message_id") or 0)


class Dialogs:
    """Первые диалоги аккаунта в памяти процесса — на диск ничего не пишется.

    Полный getConversations (1,5 с на 60 диалогов) идёт раз в FULL_TTL; между ними список правится по событиям
    long poll: изменившиеся беседы приходят одним execute и встают на своё место по sort_id."""

    def __init__(self, vk, inbox, now=time.monotonic):
        self._vk = vk
        self._inbox = inbox
        self._now = now
        self._items: list[dict] = []
        self._profiles: dict[int, dict] = {}
        self._groups: dict[int, dict] = {}
        self._total = 0
        self._synced: float | None = None
        self._version = 0
        self._recheck: dict[int, float] = {}
        self._lock = threading.Lock()

    def snapshot(self, at_least: int) -> dict:
        """Ответ в форме getConversations: не меньше at_least первых бесед, если столько есть у VK."""
        with self._lock:
            self._sync(at_least)
            return {"items": list(self._items), "profiles": list(self._profiles.values()),
                    "groups": list(self._groups.values()), "count": self._total}

    def drop(self) -> None:
        with self._lock:
            self._synced = None

    def _sync(self, at_least: int) -> None:
        now = self._now()
        stale = (self._synced is None or now - self._synced >= FULL_TTL
                 or (not self._inbox.healthy() and now - self._synced >= BLIND_TTL))
        if stale:
            self._reload(max(at_least, len(self._items)))
            return
        version, peers = self._inbox.changes_since(self._version)
        due = {p for p, at in self._recheck.items() if now - at >= LAG}
        if peers is None or len((peers or set()) | due) > CHANGED_MAX:
            self._reload(max(at_least, len(self._items)))
            return
        refresh = set(peers) | due
        if refresh:
            if not self._merge(self._vk().changed_dialogs(sorted(refresh))):
                self._reload(max(at_least, len(self._items)))
                return
            for peer in refresh:
                self._recheck.pop(peer, None)
                if now - self._inbox.changed_at(peer) < LAG:
                    self._recheck[peer] = now
        self._version = version
        if at_least > len(self._items) and len(self._items) < self._total:
            self._extend(at_least)

    def _reload(self, count: int) -> None:
        # версия — до запроса: изменение посреди загрузки должно перечитаться в следующий раз, а не потеряться
        version = self._inbox.version()
        items, profiles, groups, total = [], {}, {}, 0
        while True:
            raw = self._vk().conversations(min(VK_PAGE, count - len(items)), len(items))
            total = int(raw.get("count", 0))
            page = raw.get("items") or []
            items += page
            profiles.update({p["id"]: p for p in raw.get("profiles") or []})
            groups.update({g["id"]: g for g in raw.get("groups") or []})
            if not page or len(items) >= min(count, total):
                break
        self._items, self._profiles, self._groups, self._total = items, profiles, groups, total
        self._synced, self._version = self._now(), version
        self._recheck.clear()

    def _extend(self, count: int) -> None:
        seen = {peer_of_item(i) for i in self._items}
        while len(self._items) < min(count, self._total):
            raw = self._vk().conversations(min(VK_PAGE, count - len(self._items)), len(self._items))
            page = [i for i in raw.get("items") or [] if peer_of_item(i) not in seen]
            self._total = int(raw.get("count", self._total))
            self._remember(raw)
            if not raw.get("items"):
                break
            self._items += page
            seen |= {peer_of_item(i) for i in page}
            if not page:
                break

    def _merge(self, raw: dict) -> bool:
        """False — VK не отдал последние сообщения бесед (getById внутри execute упал): список надо перечитать."""
        fresh = {peer_of_item(i): i for i in raw.get("items") or []}
        if any(i["conversation"].get("last_message_id") and "last_message" not in i for i in fresh.values()):
            return False
        if not fresh:
            return True
        self._remember(raw)
        complete = len(self._items) >= self._total
        tail = sort_key(self._items[-1]) if self._items else (0, 0)
        kept = [i for i in self._items if peer_of_item(i) not in fresh]
        # беседа, которая по порядку ниже последней загруженной, лежит за пределами загруженной части списка
        added = [i for i in fresh.values() if complete or sort_key(i) >= tail]
        self._items = sorted(kept + added, key=sort_key, reverse=True)
        # поднявшаяся снизу беседа и новая выглядят одинаково: счётчик VK поправит следующая загрузка
        self._total = max(self._total, len(self._items))
        return True

    def _remember(self, raw: dict) -> None:
        self._profiles.update({p["id"]: p for p in raw.get("profiles") or []})
        self._groups.update({g["id"]: g for g in raw.get("groups") or []})


class Histories:
    """Последние сообщения недавно открытых чатов в памяти процесса. Ответ годен, пока long poll не видел
    в этом чате ничего нового: повторное открытие и поллинг без новостей не ходят в VK."""

    def __init__(self, inbox, keep: int = HISTORY_KEEP, ttl: float = HISTORY_TTL, now=time.monotonic):
        self._inbox = inbox
        self._keep = keep
        self._ttl = ttl
        self._now = now
        self._entries: OrderedDict[int, tuple[int, float, dict]] = OrderedDict()
        self._locks: dict[int, threading.Lock] = {}
        self._lock = threading.Lock()

    def get(self, peer: int, fetch, fresh: bool = False) -> dict:
        with self._peer_lock(peer):
            mark = self._inbox.peer_version(peer)
            with self._lock:
                entry = self._entries.get(peer)
            ttl = self._ttl if self._inbox.healthy() else BLIND_TTL
            if entry and entry[1] - self._inbox.changed_at(peer) < LAG:
                ttl = min(ttl, LAG)
            if not fresh and entry and entry[0] == mark and self._now() - entry[1] < ttl:
                with self._lock:
                    self._entries.move_to_end(peer)
                return entry[2]
            raw = fetch()
            with self._lock:
                self._entries[peer] = (mark, self._now(), raw)
                self._entries.move_to_end(peer)
                while len(self._entries) > self._keep:
                    gone, _ = self._entries.popitem(last=False)
                    self._locks.pop(gone, None)
            return raw

    def cached(self, peer: int) -> bool:
        with self._lock:
            return peer in self._entries

    def drop(self, peer: int) -> None:
        with self._lock:
            self._entries.pop(peer, None)

    def _peer_lock(self, peer: int) -> threading.Lock:
        with self._lock:
            return self._locks.setdefault(peer, threading.Lock())
