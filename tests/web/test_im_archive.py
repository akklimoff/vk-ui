from tests.web.conftest import AUTH
from tests.web.fakes import FakeVk
from web.im.archive import Archive


def test_archive_is_cached_for_a_while_and_refetched_on_demand():
    clock, asked = [0.0], []

    def fetch():
        asked.append(clock[0])
        return {len(asked)}

    archive = Archive(fetch, ttl=10, now=lambda: clock[0])
    assert archive.peers() == {1}
    clock[0] = 9
    assert archive.peers() == {1}
    assert archive.peers(fresh=True) == {2}
    clock[0] = 19.5
    assert archive.peers() == {3} and asked == [0, 9, 19.5]


def test_a_failing_archive_keeps_the_last_known_one_and_is_not_asked_again_at_once():
    clock, answers = [0.0], [{7}, RuntimeError("[15] Access denied"), {8}]

    def fetch():
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    archive = Archive(fetch, ttl=10, now=lambda: clock[0])
    assert archive.peers() == {7}
    assert archive.peers(fresh=True) == {7}
    assert archive.peers() == {7} and len(answers) == 1
    clock[0] = 10
    assert archive.peers() == {8}


def test_a_failing_first_archive_leaves_the_messenger_working(client):
    def denied():
        raise RuntimeError("[15] Access denied")

    client.app.state.vk = FakeVk("t")
    client.app.state.vk.archived_peers = denied
    hx = {"HX-Request": "true"}
    assert client.get("/im/dialogs", auth=AUTH, headers=hx).status_code == 200
    assert client.get("/im/2000000001", auth=AUTH, headers=hx).status_code == 200
