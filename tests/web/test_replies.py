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
