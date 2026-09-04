import pytest
from fastapi.testclient import TestClient

from bot.status import ReplyLog, ReplyRecord
from tests.web.conftest import AUTH
from web.app import create_app


class FakeVk:
    def __init__(self, token):
        self.deleted = []

    def delete_message(self, message_id):
        self.deleted.append(message_id)


@pytest.fixture
def client(settings):
    return TestClient(create_app(settings, vk_factory=FakeVk), follow_redirects=False)


def test_replies_page_shows_newest_first(client, settings):
    log = ReplyLog(f"{settings.state_dir}/replies.jsonl")
    log.append(ReplyRecord(1.0, 2000000001, 5, 10, 20, "первый", None, 0.5, "v"))
    log.append(ReplyRecord(2.0, 2000000001, 5, 11, 21, "второй", "тег", 0.7, "v"))
    page = client.get("/replies", auth=AUTH).text
    assert page.index("второй") < page.index("первый") and "тег" in page


def test_delete_calls_vk(client):
    r = client.post("/replies/21/delete", auth=AUTH)
    assert r.status_code == 303
    assert client.app.state.vk.deleted == [21]


HX = {"HX-Request": "true"}


def _log(settings):
    log = ReplyLog(f"{settings.state_dir}/replies.jsonl")
    log.append(ReplyRecord(1.0, 2000000001, 5, 10, 20, "первый", None, 0.5, "v"))
    log.append(ReplyRecord(2.0, 77, 6, 11, 21, "второй", "тег", 0.7, "v"))
    return log


def test_replies_hx_after_returns_only_newer_cards_and_next_poller(client, settings):
    _log(settings)
    r = client.get("/replies?after=1", auth=AUTH, headers=HX)
    assert r.status_code == 200 and "<html" not in r.text
    assert "второй" in r.text and "первый" not in r.text
    assert 'id="replies-poll"' in r.text and "after=2.0" in r.text and 'hx-swap-oob' in r.text


def test_replies_filter_by_peer_keeps_filter_in_poller(client, settings):
    _log(settings)
    page = client.get("/replies?peer=77", auth=AUTH).text
    assert "второй" in page and "первый" not in page and "peer=77" in page


def test_delete_hx_returns_empty_200(client):
    r = client.post("/replies/21/delete", auth=AUTH, headers=HX)
    assert r.status_code == 200 and r.text == ""
    assert client.app.state.vk.deleted == [21]


def test_peer_link_and_label_distinguish_group_chats():
    from web.services import peer_label, peer_link
    assert peer_link(2000000001) == "https://vk.com/im?sel=c1" and peer_label(2000000001) == "беседа 1"
    assert peer_link(77) == "https://vk.com/im?sel=77" and peer_label(77) == "id77"


def test_delete_vk_failure_returns_502_with_reason(settings):
    class BrokenVk(FakeVk):
        def delete_message(self, message_id):
            raise RuntimeError("[15] Access denied")

    client = TestClient(create_app(settings, vk_factory=BrokenVk), follow_redirects=False)
    r = client.post("/replies/21/delete", auth=AUTH)
    assert r.status_code == 502 and "Access denied" in r.json()["detail"]


def test_replies_page_keeps_poller_and_empty_state_outside_feed(client, settings):
    empty = client.get("/replies", auth=AUTH).text
    assert 'id="feed-empty"' in empty and "hidden" not in empty.split('id="feed-empty"')[1].split(">")[0]
    _log(settings)
    page = client.get("/replies", auth=AUTH).text
    assert page.count('id="replies-poll"') == 1 and "hx-swap-oob" not in page
    assert page.index('id="replies-poll"') < page.index('id="feed"')
    assert 'id="feed-empty" class="muted" hidden' in page


def test_replies_hx_with_new_records_hides_empty_state(client, settings):
    _log(settings)
    r = client.get("/replies?after=0", auth=AUTH, headers=HX)
    assert 'id="feed-empty"' in r.text and "hx-swap-oob" in r.text.split('id="feed-empty"')[1].split(">")[0]
