import json

from tests.web.conftest import AUTH


def test_create_activate_and_list(client, settings):
    r = client.post("/personas", data={"slug": "bob", "name": "Боб", "prompt": "Ты — Боб."}, auth=AUTH)
    assert r.status_code == 303
    assert open(f"{settings.personas_dir}/bob.md").read() == "# Боб\n\nТы — Боб.\n"
    r = client.post("/personas/bob/activate", auth=AUTH)
    assert r.status_code == 303
    assert json.load(open(settings.runtime_file))["active_persona"] == "bob"
    page = client.get("/personas", auth=AUTH).text
    assert "Боб" in page and "активна" in page


def test_bad_slug_rejected(client):
    r = client.post("/personas", data={"slug": "../x", "name": "n", "prompt": "p"}, auth=AUTH)
    assert r.status_code == 400


def test_edit_persona(client, settings):
    client.post("/personas", data={"slug": "a", "name": "A", "prompt": "старый"}, auth=AUTH)
    client.post("/personas/a", data={"name": "A2", "prompt": "новый"}, auth=AUTH)
    assert open(f"{settings.personas_dir}/a.md").read() == "# A2\n\nновый\n"


HX = {"HX-Request": "true"}


def test_activate_hx_returns_list_partial_with_toast(client):
    client.post("/personas", data={"slug": "bob", "name": "Боб", "prompt": "p"}, auth=AUTH)
    r = client.post("/personas/bob/activate", auth=AUTH, headers=HX)
    assert r.status_code == 200 and "<html" not in r.text
    assert 'id="personas"' in r.text and "активна" in r.text and "toast" in r.headers["HX-Trigger"]


def test_update_persona_hx_stays_in_editor_with_toast(client, settings):
    client.post("/personas", data={"slug": "a", "name": "A", "prompt": "старый"}, auth=AUTH)
    r = client.post("/personas/a", data={"name": "A2", "prompt": "новый"}, auth=AUTH, headers=HX)
    assert r.status_code == 200 and "<html" not in r.text
    assert 'value="A2"' in r.text and "новый" in r.text and "toast" in r.headers["HX-Trigger"]
    assert open(f"{settings.personas_dir}/a.md").read() == "# A2\n\nновый\n"


def test_create_bad_slug_hx_returns_422_with_kept_input(client, settings):
    r = client.post("/personas", data={"slug": "../x", "name": "Имя", "prompt": "текст"}, auth=AUTH, headers=HX)
    assert r.status_code == 422 and 'class="error"' in r.text
    assert 'value="../x"' in r.text and 'value="Имя"' in r.text and ">текст</textarea>" in r.text


def test_create_hx_opens_editor_of_new_persona(client, settings):
    r = client.post("/personas", data={"slug": "bob", "name": "Боб", "prompt": "p"}, auth=AUTH, headers=HX)
    assert r.status_code == 200 and 'hx-post="/personas/bob"' in r.text and "toast" in r.headers["HX-Trigger"]
    assert r.headers["HX-Push-Url"] == "/personas/bob/edit"


def test_empty_list_speaks_of_the_agent(client):
    page = client.get("/personas", auth=AUTH).text
    assert "агент использует PERSONA_PROMPT" in page and "бот использует" not in page
