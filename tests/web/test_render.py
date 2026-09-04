import json

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from web.render import Renderer

HX = {"HX-Request": "true"}


@pytest.fixture
def client(tmp_path):
    (tmp_path / "partials").mkdir()
    (tmp_path / "base.html").write_text("<html>{% block body %}{% endblock %}</html>")
    (tmp_path / "hello.html").write_text(
        '{% extends "base.html" %}{% block body %}{% include "partials/hello.html" %}{% endblock %}')
    (tmp_path / "partials" / "hello.html").write_text("<p>{{ error or name }}</p>")
    render = Renderer(str(tmp_path))
    app = FastAPI()

    @app.get("/hello")
    def hello(request: Request):
        return render.page(request, "hello", {"name": "мир"})

    @app.post("/hello")
    def save(request: Request, bad: bool = False):
        if bad:
            return render.invalid(request, "hello", {"name": "мир"}, "плохо")
        return render.saved(request, "hello", {"name": "мир"}, toast="Сохранено", redirect="/hello")

    return TestClient(app, follow_redirects=False)


def test_page_renders_full_html_without_hx(client):
    r = client.get("/hello")
    assert r.status_code == 200 and "<html>" in r.text and "мир" in r.text


def test_page_renders_partial_only_for_hx(client):
    r = client.get("/hello", headers=HX)
    assert r.status_code == 200 and r.text.strip() == "<p>мир</p>"


def test_saved_redirects_without_hx(client):
    r = client.post("/hello")
    assert r.status_code == 303 and r.headers["location"] == "/hello"


def test_saved_returns_partial_with_toast_for_hx(client):
    r = client.post("/hello", headers=HX)
    assert r.status_code == 200 and r.text.strip() == "<p>мир</p>"
    assert json.loads(r.headers["HX-Trigger"]) == {"toast": "Сохранено"}


def test_invalid_raises_400_without_hx(client):
    r = client.post("/hello?bad=1")
    assert r.status_code == 400 and r.json()["detail"] == "плохо"


def test_invalid_returns_422_partial_for_hx(client):
    r = client.post("/hello?bad=1", headers=HX)
    assert r.status_code == 422 and r.text.strip() == "<p>плохо</p>"
    assert json.loads(r.headers["HX-Trigger"]) == {"toast": {"text": "плохо", "kind": "bad"}}


def test_history_restore_request_gets_full_page(client):
    r = client.get("/hello", headers={**HX, "HX-History-Restore-Request": "true"})
    assert "<html>" in r.text
