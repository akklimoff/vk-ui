import pytest

from bot.agent.pictures import data_url, is_photo_url, photo_urls


@pytest.mark.parametrize("url", ["https://sun9-15.vkuserphoto.ru/s/v1/ig2/x.jpg?quality=95&sign=abc",
                                 "https://pp.userapi.com/c1/v1/x.jpg", "https://sun1-22.userapi.com/x.png"])
def test_vk_photo_storage_is_accepted(url):
    assert is_photo_url(url)


@pytest.mark.parametrize("url", [
    "http://sun9-15.vkuserphoto.ru/x.jpg", "https://vkuserphoto.ru/x.jpg", "https://evilvkuserphoto.ru/x.jpg",
    "https://sun9-15.vkuserphoto.ru.evil.com/x.jpg", "https://sun9-15.vkuserphoto.ru@evil.com/x.jpg",
    "https://user:pass@sun9-15.vkuserphoto.ru/x.jpg", "https://sun9-15.vkuserphoto.ru:8443/x.jpg",
    "https://169.254.169.254/latest/meta-data", "https://localhost/x.jpg", "http://ai:8090/v1/models",
    "file:///app/.env", "ftp://sun9-15.vkuserphoto.ru/x.jpg", "//sun9-15.vkuserphoto.ru/x.jpg",
    "https://[::1]/x.jpg", r"https://127.0.0.1\.userapi.com/x", r"https://evil.com\.userapi.com/a.jpg",
    r"https://sun9-1.vkuserphoto.ru/a\b.jpg", "https://evil.com%2f.userapi.com/x", "https://evil.com;.userapi.com/x",
    "https://evil.com\t.userapi.com/x", "https://sun9-1.vkuserphoto.ru/a b.jpg", "https://sun9-1.vkuserphoto.ru/a\n",
    "https://sun9-1.vkuserphoto.ru./x.jpg", "https://SUN9-1.vkuserphoto.ru/x.jpg", "https://sun9-1.vkuserphoto.ru",
    "https://evil.com#.userapi.com/x", "https://evil.com?.userapi.com/x", "https://.userapi.com/x",
    " https://sun9-1.vkuserphoto.ru/x.jpg", "https://sun9-15.vkuserphoto.ru:x/y", "", None, 5, ["https://sun9-1.vkuserphoto.ru/x.jpg"],
])
def test_nothing_else_is_ever_fetched(url):
    assert not is_photo_url(url)


def test_photos_and_avatars_are_found_at_any_depth_in_order_and_once():
    def photo(name):
        return {"sizes": [{"url": f"https://sun9-1.vkuserphoto.ru/{name}_s.jpg", "width": 75},
                          {"url": f"https://sun9-1.vkuserphoto.ru/{name}.jpg", "width": 1280},
                          {"url": f"https://sun9-1.vkuserphoto.ru/{name}_w.jpg", "width": 2560}]}

    result = {"items": [
        {"attachments": [{"type": "photo", "photo": photo("a")}],
         "reply_message": {"attachments": [{"type": "photo", "photo": photo("b")}]}},
        {"attachments": [{"type": "photo", "photo": photo("a")}, {"type": "link", "link": {"photo": photo("c")}}]},
    ], "profiles": [{"id": 9, "photo_100": "https://sun9-1.vkuserphoto.ru/ava100.jpg",
                     "photo_200": "https://sun9-1.vkuserphoto.ru/ava200.jpg", "photo_id": "9_1"}]}
    assert photo_urls(result) == [f"https://sun9-1.vkuserphoto.ru/{name}.jpg" for name in ("a", "b", "c", "ava200")]


def test_small_avatars_vk_adds_unasked_are_not_shown():
    profiles = [{"id": 9, "photo_50": "https://sun9-1.vkuserphoto.ru/ava50.jpg",
                 "photo_100": "https://sun9-1.vkuserphoto.ru/ava100.jpg"}]
    assert photo_urls({"profiles": profiles}) == []


def test_addresses_outside_vk_storage_and_other_fields_are_skipped():
    result = {"url": "https://sun9-1.vkuserphoto.ru/link.jpg", "photo_100": "https://evil.example/a.jpg",
              "sizes": [{"url": "http://ai:8090/v1/models", "width": 10}], "text": "https://sun9-1.vkuserphoto.ru/t.jpg"}
    assert photo_urls(result) == [] and photo_urls(5) == [] and photo_urls(None) == []


def test_picture_is_handed_over_as_a_data_url():
    assert data_url("image/png", b"\x89PNG") == "data:image/png;base64,iVBORw=="


def test_what_the_check_accepts_is_opened_by_the_http_library_at_the_same_host():
    import requests

    for url in ("https://sun9-15.vkuserphoto.ru/s/v1/x.jpg?quality=95&crop=1,93,735,735&as=32x32&u=a-b_c&cs=1x1",
                "https://pp.userapi.com/c1/v1/x.jpg"):
        assert is_photo_url(url)
        prepared = requests.Request("GET", url).prepare().url
        assert prepared.split("/")[2].endswith((".vkuserphoto.ru", ".userapi.com"))
