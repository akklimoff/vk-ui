import copy

from web.im.cache import BLIND_TTL, CHANGED_MAX, FULL_TTL, LAG, Dialogs, Histories, sort_key


class Inbox:
    def __init__(self, clock=None):
        self.v = 0
        self.peers = {}
        self.at = {}
        self.unknown = 0
        self.ok = True
        self.clock = clock

    def changed(self, peers=None, at=float("-inf")):
        self.v += 1
        if peers is None:
            self.unknown = self.v
        for p in peers or ():
            self.peers[p] = self.v
            self.at[p] = at

    def changed_at(self, peer):
        return self.at.get(peer, float("-inf"))

    def version(self):
        return self.v

    def peer_version(self, peer):
        return max(self.peers.get(peer, 0), self.unknown)

    def changes_since(self, version):
        if self.unknown > version:
            return self.v, None
        return self.v, frozenset(p for p, v in self.peers.items() if v > version)

    def healthy(self):
        return self.ok


def item(peer, last, pinned=0):
    return {"conversation": {"peer": {"id": peer}, "last_message_id": last, "sort_id": {"major_id": pinned, "minor_id": last}},
            "last_message": {"id": last}}


class Vk:
    def __init__(self, items, total=None):
        self.items = items
        self.total = total if total is not None else len(items)
        self.calls = []

    def conversations(self, count, offset):
        self.calls.append(("conversations", count, offset))
        return {"items": copy.deepcopy(self.items[offset:offset + count]), "count": self.total, "profiles": [], "groups": []}

    def changed_dialogs(self, peers):
        self.calls.append(("changed", tuple(peers)))
        return {"items": [copy.deepcopy(i) for i in self.items if i["conversation"]["peer"]["id"] in peers],
                "profiles": [{"id": 9}], "groups": []}


def peers(snapshot):
    return [i["conversation"]["peer"]["id"] for i in snapshot["items"]]


def setup(items, total=None):
    clock = {"t": 0.0}
    vk, inbox = Vk(items, total), Inbox()
    return vk, inbox, Dialogs(lambda: vk, inbox, now=lambda: clock["t"]), clock


def test_an_unchanged_list_is_served_without_asking_vk():
    vk, inbox, dialogs, _ = setup([item(1, 10), item(2, 5)])
    assert peers(dialogs.snapshot(2)) == [1, 2]
    assert peers(dialogs.snapshot(2)) == [1, 2]
    assert vk.calls == [("conversations", 2, 0)]


def test_a_new_message_moves_its_chat_up_with_one_request():
    vk, inbox, dialogs, _ = setup([item(1, 10), item(2, 5), item(3, 4)])
    dialogs.snapshot(3)
    vk.items[1] = item(2, 11)
    inbox.changed([2])
    snap = dialogs.snapshot(3)
    assert peers(snap) == [2, 1, 3] and vk.calls[-1] == ("changed", (2,))
    assert {"id": 9} in snap["profiles"]


def test_pinned_chats_stay_on_top():
    vk, inbox, dialogs, _ = setup([item(1, 10, pinned=5), item(2, 5)])
    dialogs.snapshot(2)
    vk.items[1] = item(2, 99)
    inbox.changed([2])
    assert peers(dialogs.snapshot(2)) == [1, 2]
    assert sort_key(item(1, 10, pinned=5)) > sort_key(item(2, 99))


def test_a_chat_that_falls_below_the_loaded_part_is_not_shown():
    vk, inbox, dialogs, _ = setup([item(1, 10), item(2, 9), item(3, 3)], total=3)
    dialogs.snapshot(2)
    inbox.changed([3])
    assert peers(dialogs.snapshot(2)) == [1, 2]


def test_a_new_chat_appears_and_grows_the_count():
    vk, inbox, dialogs, _ = setup([item(1, 10), item(2, 5)])
    dialogs.snapshot(2)
    vk.items.insert(0, item(7, 12))
    inbox.changed([7])
    snap = dialogs.snapshot(2)
    assert peers(snap)[:1] == [7] and snap["count"] == 3


def test_an_event_without_a_chat_reloads_the_list():
    vk, inbox, dialogs, _ = setup([item(1, 10)])
    dialogs.snapshot(1)
    inbox.changed(None)
    dialogs.snapshot(1)
    assert vk.calls == [("conversations", 1, 0), ("conversations", 1, 0)]


def test_the_list_is_reloaded_after_a_while_and_often_without_long_poll():
    vk, inbox, dialogs, clock = setup([item(1, 10)])
    dialogs.snapshot(1)
    clock["t"] = FULL_TTL - 1
    dialogs.snapshot(1)
    assert len(vk.calls) == 1
    clock["t"] = FULL_TTL
    dialogs.snapshot(1)
    assert len(vk.calls) == 2
    inbox.ok = False
    clock["t"] += BLIND_TTL
    dialogs.snapshot(1)
    assert len(vk.calls) == 3


def test_a_chat_read_right_after_its_event_is_read_once_more():
    vk, inbox, dialogs, clock = setup([item(1, 10), item(2, 5)])
    dialogs.snapshot(2)
    inbox.changed([2], at=0.0)
    dialogs.snapshot(2)
    clock["t"] = LAG
    dialogs.snapshot(2)
    clock["t"] = 2 * LAG
    dialogs.snapshot(2)
    assert [c for c in vk.calls if c[0] == "changed"] == [("changed", (2,)), ("changed", (2,))]


def test_too_many_changed_chats_reload_the_list():
    vk, inbox, dialogs, _ = setup([item(1, 10)])
    dialogs.snapshot(1)
    inbox.changed(range(CHANGED_MAX + 1))
    dialogs.snapshot(1)
    assert vk.calls == [("conversations", 1, 0), ("conversations", 1, 0)]


def test_chats_whose_last_message_did_not_come_reload_the_list():
    vk, inbox, dialogs, _ = setup([item(1, 10), item(2, 5)])
    dialogs.snapshot(2)
    del vk.items[1]["last_message"]
    inbox.changed([2])
    dialogs.snapshot(2)
    assert vk.calls[-1] == ("conversations", 2, 0)


def test_a_chat_rising_from_below_does_not_inflate_the_count():
    vk, inbox, dialogs, _ = setup([item(1, 10), item(2, 9), item(3, 3)])
    dialogs.snapshot(2)
    vk.items[2] = item(3, 12)
    inbox.changed([3])
    snap = dialogs.snapshot(2)
    assert peers(snap)[0] == 3 and snap["count"] == 3


def test_more_chats_are_read_from_where_the_loaded_part_ends():
    vk, inbox, dialogs, _ = setup([item(p, 100 - p) for p in range(1, 8)])
    dialogs.snapshot(3)
    assert peers(dialogs.snapshot(6)) == [1, 2, 3, 4, 5, 6]
    assert vk.calls == [("conversations", 3, 0), ("conversations", 3, 3)]


def history_setup():
    clock = {"t": 0.0}
    inbox = Inbox()
    fetched = []

    def fetch(peer):
        def go():
            fetched.append(peer)
            return {"peer": peer, "n": len(fetched)}
        return go

    return inbox, Histories(inbox, keep=2, now=lambda: clock["t"]), fetch, fetched, clock


def test_history_is_fetched_again_only_after_its_chat_changed():
    inbox, histories, fetch, fetched, _ = history_setup()
    histories.get(5, fetch(5))
    histories.get(5, fetch(5))
    inbox.changed([6])
    histories.get(5, fetch(5))
    assert fetched == [5]
    inbox.changed([5])
    histories.get(5, fetch(5))
    assert fetched == [5, 5]


def test_sending_reads_the_history_fresh():
    inbox, histories, fetch, fetched, _ = history_setup()
    histories.get(5, fetch(5))
    histories.get(5, fetch(5), fresh=True)
    assert fetched == [5, 5]


def test_history_without_long_poll_lives_briefly():
    inbox, histories, fetch, fetched, clock = history_setup()
    inbox.ok = False
    histories.get(5, fetch(5))
    clock["t"] = BLIND_TTL
    histories.get(5, fetch(5))
    assert fetched == [5, 5]


def test_history_read_right_after_its_event_is_read_once_more():
    inbox, histories, fetch, fetched, clock = history_setup()
    clock["t"] = 100.0
    inbox.changed([5], at=99.0)
    histories.get(5, fetch(5))
    clock["t"] = 99.0 + LAG + 0.5
    histories.get(5, fetch(5))
    clock["t"] += 60
    histories.get(5, fetch(5))
    assert fetched == [5, 5]


def test_only_recent_chats_are_kept():
    inbox, histories, fetch, fetched, _ = history_setup()
    for peer in (1, 2, 3):
        histories.get(peer, fetch(peer))
    assert not histories.cached(1) and histories.cached(2) and histories.cached(3)
