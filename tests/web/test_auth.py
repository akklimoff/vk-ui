from tests.web.conftest import AUTH
from web.auth import LoginLimiter


def test_limiter_blocks_after_max_failures():
    clock = [0.0]
    lim = LoginLimiter(max_failures=3, block_seconds=100, now=lambda: clock[0])
    for _ in range(3):
        assert not lim.blocked("1.1.1.1")
        lim.failed("1.1.1.1")
    assert lim.blocked("1.1.1.1")
    assert not lim.blocked("2.2.2.2")
    clock[0] = 101
    assert not lim.blocked("1.1.1.1")


def test_success_resets_failures():
    lim = LoginLimiter(max_failures=2, block_seconds=100, now=lambda: 0.0)
    lim.failed("ip")
    lim.succeeded("ip")
    lim.failed("ip")
    assert not lim.blocked("ip")


def test_too_many_wrong_passwords_return_429(client):
    for _ in range(5):
        assert client.get("/", auth=("x", "wrong")).status_code == 401
    assert client.get("/", auth=("x", "wrong")).status_code == 429
    assert client.get("/", auth=AUTH).status_code == 429


def test_cross_site_post_is_rejected(client):
    r = client.post("/settings/pause", auth=AUTH, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    assert client.post("/settings/pause", auth=AUTH, headers={"Sec-Fetch-Site": "same-origin"}).status_code == 303
    assert client.get("/", auth=AUTH, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200
