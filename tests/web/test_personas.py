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
