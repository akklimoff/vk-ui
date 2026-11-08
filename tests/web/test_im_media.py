import pytest

from tests.web.conftest import AUTH
from web.im.media import MediaCache, Unsatisfiable, allowed, byte_range, media_url, safe_type

VOICE = "https://psv4.userapi.com/c1/u1/audiomsg/d1/v.mp3"


def test_only_vk_cdn_over_https_is_proxied():
    assert allowed(VOICE) and allowed("https://sun9-1.userapi.com/x.jpg") and allowed("https://x.vkuserphoto.ru/p.jpg")
    assert not allowed("http://psv4.userapi.com/v.mp3")
    assert not allowed("https://userapi.com.evil.example/v.mp3")
    assert not allowed("https://169.254.169.254/latest")
    assert not allowed("file:///etc/passwd")
    # urllib3, по которому соединяется requests, увидел бы здесь хост 127.0.0.1:8080
    assert not allowed("https://127.0.0.1:8080\\@a.userapi.com/")
    assert not allowed("https://a.userapi.com@127.0.0.1/") and not allowed("https://a.userapi.com:8443/v.mp3")
    assert not allowed("https://a.userapi.com/\nx")


def test_ranges_follow_rfc_7233():
    assert byte_range("bytes=0-", 10) == (0, 9)
    assert byte_range("bytes=2-5", 10) == (2, 5)
    assert byte_range("bytes=-3", 10) == (7, 9)
    assert byte_range("bytes=5-100", 10) == (5, 9)
    assert byte_range(None, 10) is None and byte_range("items=1-2", 10) is None
    for bad in ("bytes=20-", "bytes=-0"):
        with pytest.raises(Unsatisfiable):
            byte_range(bad, 10)


def test_files_are_downloaded_once_and_evicted_oldest_first():
    fetched = []

    def fetch(url):
        fetched.append(url)
        return b"x" * 4, "audio/mpeg"

    cache = MediaCache(fetch, limit=8)
    a, b, c = (f"https://psv4.userapi.com/{n}.mp3" for n in "abc")
    cache.get(a)
    cache.get(a)
    cache.get(b)
    cache.get(c)
    cache.get(a)
    assert fetched == [a, b, c, a]


def test_only_media_types_keep_their_content_type():
    assert safe_type("audio/mpeg") == "audio/mpeg" and safe_type("image/jpeg; q=1") == "image/jpeg"
    assert safe_type("text/html") == "application/octet-stream"
    assert safe_type("image/svg+xml") == "application/octet-stream"


def test_media_url_quotes_the_address_and_the_name():
    assert media_url("") == ""
    assert media_url(VOICE, "голосовое.mp3").startswith("/im/media?u=https%3A%2F%2Fpsv4.userapi.com%2F")
    assert media_url(VOICE, "голосовое.mp3").endswith("&name=%D0%B3%D0%BE%D0%BB%D0%BE%D1%81%D0%BE%D0%B2%D0%BE%D0%B5.mp3")


BODY = bytes(range(100))


@pytest.fixture
def client(settings, monkeypatch):
    from fastapi.testclient import TestClient

    import web.im.media as module
    from tests.web.fakes import FakeVk
    from web.app import create_app

    monkeypatch.setattr(module.MediaCache, "_download", lambda self, url: (BODY, "audio/mpeg"))
    return TestClient(create_app(settings, vk_factory=FakeVk), follow_redirects=False)


def test_voice_is_served_with_ranges_for_seeking(client):
    media = BODY
    r = client.get("/im/media", params={"u": VOICE}, headers={"Range": "bytes=10-19"}, auth=AUTH)
    assert r.status_code == 206 and r.content == media[10:20]
    assert r.headers["content-range"] == "bytes 10-19/100" and r.headers["accept-ranges"] == "bytes"
    assert r.headers["x-content-type-options"] == "nosniff" and "sandbox" in r.headers["content-security-policy"]
    whole = client.get("/im/media", params={"u": VOICE, "name": "голосовое.mp3"}, auth=AUTH)
    assert whole.status_code == 200 and whole.content == media
    assert whole.headers["content-disposition"] == "attachment; filename*=UTF-8''%D0%B3%D0%BE%D0%BB%D0%BE%D1%81%D0%BE%D0%B2%D0%BE%D0%B5.mp3"


def test_a_range_past_the_end_is_unsatisfiable(client):
    r = client.get("/im/media", params={"u": VOICE}, headers={"Range": "bytes=500-"}, auth=AUTH)
    assert r.status_code == 416 and r.headers["content-range"] == "bytes */100"


def test_media_is_served_only_to_the_panel_itself(client):
    r = client.get("/im/media", params={"u": VOICE}, headers={"Sec-Fetch-Site": "cross-site"}, auth=AUTH)
    assert r.status_code == 403
    assert client.get("/im/media", params={"u": VOICE}, headers={"Sec-Fetch-Site": "same-origin"}, auth=AUTH).status_code == 200


def test_foreign_addresses_are_not_proxied(client):
    assert client.get("/im/media", params={"u": "https://evil.example/x"}, auth=AUTH).status_code == 404
    assert client.get("/im/media", params={"u": VOICE}, auth=None).status_code in (302, 303, 401)
