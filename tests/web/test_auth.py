from tests.web.conftest import AUTH
from web.auth import LoginLimiter


def test_limiter_blocks_after_max_failures():
    clock = [0.0]
    lim = LoginLimiter(max_failures=3, block_seconds=100, now=lambda: clock[0])
    for _ in range(3):
        assert lim.attempt("1.1.1.1", False) is False
    assert lim.attempt("1.1.1.1", True) is None
    assert lim.attempt("2.2.2.2", False) is False
    clock[0] = 101
    assert lim.attempt("1.1.1.1", True) is True


def test_success_resets_failures():
    lim = LoginLimiter(max_failures=2, block_seconds=100, now=lambda: 0.0)
    assert lim.attempt("ip", False) is False
    assert lim.attempt("ip", True) is True
    assert lim.attempt("ip", False) is False
    assert lim.attempt("ip", True) is True


def test_limiter_counts_simultaneous_wrong_passwords_and_forgets_expired_addresses():
    from concurrent.futures import ThreadPoolExecutor

    clock = [0.0]
    lim = LoginLimiter(max_failures=5, block_seconds=100, now=lambda: clock[0])
    with ThreadPoolExecutor(16) as pool:
        answers = list(pool.map(lambda _: lim.attempt("ip", False), range(200)))
    assert answers.count(False) == 5 and answers.count(None) == 195
    clock[0] = 101
    assert lim.attempt("ip", True) is True
    assert lim._failures == {}


def test_too_many_wrong_passwords_return_429(client):
    for _ in range(5):
        assert client.get("/", auth=("x", "wrong")).status_code == 401
    assert client.get("/", auth=("x", "wrong")).status_code == 429
    assert client.get("/", auth=AUTH).status_code == 429


def test_cross_site_post_is_rejected(client):
    r = client.post("/im/2000000001/messages/1/delete", auth=AUTH, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    assert client.post("/im/2000000001/messages/1/delete", auth=AUTH, headers={"Sec-Fetch-Site": "same-origin"}).status_code == 303
    assert client.get("/im", auth=AUTH, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200


from web.auth import SESSION_COOKIE, SESSION_SECONDS, safe_next, session_token


def logged_in(client, password="pw", next="/"):
    return client.post("/login", data={"password": password, "next": next})


def test_a_visitor_without_a_session_is_sent_to_the_login_form_and_back_where_he_was_going(client):
    assert client.get("/").headers["location"] == "/login"
    assert client.get("/im?sel=2").headers["location"] == "/login?next=%2Fim%3Fsel%3D2"
    form = client.get("/login?next=/im")
    assert form.status_code == 200 and 'name="password"' in form.text and 'value="/im"' in form.text
    assert "<nav" not in form.text


def test_htmx_and_form_requests_without_a_session_get_no_browser_password_dialog(client):
    partial = client.get("/im/dialogs", headers={"HX-Request": "true"})
    assert partial.status_code == 401 and partial.headers["HX-Redirect"] == "/login"
    assert "WWW-Authenticate" not in partial.headers
    post = client.post("/im/2000000001/read")
    assert post.status_code == 401 and "WWW-Authenticate" not in post.headers


def test_the_right_password_gives_a_session_that_outlives_the_browser_and_needs_no_password_again(client):
    response = logged_in(client, next="/im?sel=2")
    assert response.status_code == 303 and response.headers["location"] == "/im?sel=2"
    cookie = response.headers["set-cookie"]
    assert f"Max-Age={SESSION_SECONDS}" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert SESSION_SECONDS >= 400 * 24 * 3600
    assert client.get("/im").status_code == 200
    assert client.get("/login").headers["location"] == "/"


def test_every_visit_pushes_the_end_of_the_session_further(client):
    logged_in(client)
    assert f"Max-Age={SESSION_SECONDS}" in client.get("/").headers["set-cookie"]


def test_the_session_survives_a_restart_and_dies_with_the_password(settings, client):
    from fastapi.testclient import TestClient

    from tests.web.fakes import FakeVk
    from web.app import create_app

    logged_in(client)
    token = client.cookies[SESSION_COOKIE]
    assert token == session_token("pw") != session_token("pw2")

    def fresh(password):
        app = create_app(settings.model_copy(update={"web_password": password}), vk_factory=FakeVk)
        return TestClient(app, follow_redirects=False, cookies={SESSION_COOKIE: token})

    assert fresh("pw").get("/im").status_code == 200
    assert fresh("pw2").get("/im").status_code == 303


def test_a_wrong_password_shows_the_form_again_and_the_fifth_blocks_the_address(client):
    for _ in range(5):
        wrong = logged_in(client, "мимо")
        assert wrong.status_code == 401 and "Неверный пароль" in wrong.text and "set-cookie" not in wrong.headers
    blocked = logged_in(client)
    assert blocked.status_code == 429 and "Слишком много" in blocked.text and "set-cookie" not in blocked.headers


def test_attempts_are_counted_per_visitor_behind_the_proxy_and_not_for_the_proxy_itself(client):
    for _ in range(5):
        client.post("/login", data={"password": "мимо"}, headers={"X-Forwarded-For": "6.6.6.6, 1.1.1.1"})
    assert client.post("/login", data={"password": "pw"}, headers={"X-Forwarded-For": "1.1.1.1"}).status_code == 429
    assert client.post("/login", data={"password": "pw"}, headers={"X-Forwarded-For": "1.1.1.1, 2.2.2.2"}).status_code == 303


def test_cookie_is_marked_secure_behind_https(client):
    plain = logged_in(client).headers["set-cookie"]
    behind_caddy = client.post("/login", data={"password": "pw"}, headers={"X-Forwarded-Proto": "https"})
    assert "Secure" not in plain and "Secure" in behind_caddy.headers["set-cookie"]


def test_logout_ends_the_session(client):
    logged_in(client)
    out = client.post("/logout")
    assert out.status_code == 303 and out.headers["location"] == "/login"
    assert 'Max-Age=0' in out.headers["set-cookie"]
    client.cookies.clear()
    assert client.get("/im").headers["location"] == "/login?next=%2Fim"


def test_login_and_session_requests_from_another_site_are_refused(client):
    assert client.post("/login", data={"password": "pw"}, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    logged_in(client)
    assert client.post("/im/2000000001/messages/1/delete", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.post("/im/2000000001/messages/1/delete", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 303


def test_a_forged_cookie_is_not_a_session(client):
    client.cookies.set(SESSION_COOKIE, "0" * 64)
    assert client.get("/").status_code == 303


def test_after_login_the_visitor_is_returned_only_inside_the_site():
    assert safe_next("/im?sel=2") == "/im?sel=2"
    for target in ("https://evil.example", "//evil.example", "/\\evil.example", "javascript:alert(1)", "", None,
                   "/a\nb"):
        assert safe_next(target) == "/"


def test_styles_and_scripts_carry_their_version(client):
    import re

    page = client.get("/login").text
    assert re.search(r'href="/static/app\.css\?v=[1-9]\d*"', page) and re.search(r'src="/static/app\.js\?v=[1-9]\d*"', page)
    assert client.get(re.search(r'/static/app\.css\?v=\d+', page)[0]).status_code == 200
