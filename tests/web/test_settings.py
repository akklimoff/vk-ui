import json
import os

import pytest

from tests.web.conftest import AUTH

HX = {"HX-Request": "true"}
VALID = {"temperature": "0.5", "active_model": "", "paused_peers": "2000000005, 7"}


def saved(settings):
    with open(settings.runtime_file, encoding="utf-8") as f:
        return json.load(f)


def test_save_settings_writes_runtime(client, settings):
    r = client.post("/settings", data={**VALID, "active_model": "claude-opus-5"}, auth=AUTH)
    assert r.status_code == 303
    d = saved(settings)
    assert d["temperature"] == 0.5 and d["paused_peers"] == [7, 2000000005] and d["active_model"] == "claude-opus-5"


def test_form_offers_only_what_the_agent_reads(client):
    body = client.get("/settings", auth=AUTH).text
    assert 'name="temperature"' in body and 'name="paused_peers"' in body and 'name="active_model"' in body
    for gone in ("reply_delay_min", "reply_delay_max", "context_messages", "dm_debounce_seconds"):
        assert gone not in body


def test_ceilings_are_shown_read_only(client, settings):
    body = client.get("/settings", auth=AUTH).text
    for name in ("AGENT_MAX_STEPS", "AGENT_TIME_BUDGET_SECONDS", "AGENT_RESULT_CHAR_LIMIT", "AGENT_CONFIRM_TTL_SECONDS",
                 "USER_COOLDOWN_SECONDS", "CHAT_LIMIT_PER_HOUR", "GLOBAL_LIMIT_PER_MINUTE"):
        assert name in body
    assert 'name="agent_max_steps"' not in body and 'name="AGENT_MAX_STEPS"' not in body
    assert "перезапуск" in body


def test_ceilings_take_values_from_settings_and_the_loop_defaults(settings):
    from bot.agent.loop import Limits
    from web.services import ceilings

    rows = {env or title: value for title, value, env in ceilings(settings)}
    assert rows["AGENT_MAX_STEPS"] == str(settings.agent_max_steps)
    assert rows["CHAT_LIMIT_PER_HOUR"] == str(settings.chat_limit_per_hour)
    assert rows["вызовов VK на просьбу"] == str(Limits().max_calls)
    assert rows["из них пишущих"] == str(Limits().max_writes)


def test_saving_keeps_keys_the_form_does_not_show(client, settings):
    with open(settings.runtime_file, "w", encoding="utf-8") as f:
        json.dump({"active_persona": "rina", "peer_personas": {"2000000001": "rina"}, "paused": True}, f)
    client.post("/settings", data=VALID, auth=AUTH)
    d = saved(settings)
    assert d["active_persona"] == "rina" and d["peer_personas"] == {"2000000001": "rina"} and d["paused"] is True


def test_model_picker_lists_models_of_providers_with_keys(client):
    body = client.get("/settings", auth=AUTH).text
    assert "Claude Opus 5" in body and "Grok 4.6" in body and "по умолчанию из .env" in body
    assert "gpt-5-mini" not in body


def test_unknown_model_is_rejected(client, settings):
    r = client.post("/settings", data={**VALID, "active_model": "gpt-5-mini"}, auth=AUTH, headers=HX)
    assert r.status_code == 422 and "недоступна" in r.text
    assert not os.path.exists(settings.runtime_file)


def test_pause_toggle_keeps_other_fields(client, settings):
    with open(settings.runtime_file, "w", encoding="utf-8") as f:
        json.dump({"active_persona": "v", "paused": False}, f)
    client.post("/settings/pause", auth=AUTH)
    assert saved(settings)["paused"] is True and saved(settings)["active_persona"] == "v"
    client.post("/settings/pause", auth=AUTH)
    assert saved(settings)["paused"] is False


def test_bad_number_returns_400(client):
    assert client.post("/settings", data={**VALID, "temperature": "hot"}, auth=AUTH).status_code == 400


def test_save_settings_hx_returns_form_partial_with_toast(client):
    r = client.post("/settings", data=VALID, auth=AUTH, headers=HX)
    assert r.status_code == 200 and "<html" not in r.text and 'id="settings-form"' in r.text
    assert 'value="0.5"' in r.text and "7, 2000000005" in r.text and "toast" in r.headers["HX-Trigger"]


def test_bad_number_hx_returns_422_with_error_and_kept_input(client, settings):
    r = client.post("/settings", data={**VALID, "temperature": "hot"}, auth=AUTH, headers=HX)
    assert r.status_code == 422 and 'class="error"' in r.text and 'value="hot"' in r.text
    assert not os.path.exists(settings.runtime_file)


def test_parse_runtime_form_names_bad_field():
    from web.services import parse_runtime_form

    with pytest.raises(ValueError, match="Температура.*hot"):
        parse_runtime_form({**VALID, "temperature": "hot"})
    with pytest.raises(ValueError, match="Чаты на паузе"):
        parse_runtime_form({**VALID, "paused_peers": "1, x"})
    assert parse_runtime_form(VALID) == {"temperature": 0.5, "active_model": "", "paused_peers": [7, 2000000005]}
    with pytest.raises(ValueError, match="Модель"):
        parse_runtime_form({**VALID, "active_model": "grok-4.6"})


@pytest.mark.parametrize("stored", [{"paused_peers": "abc"}, {"paused_peers": 5}, {"temperature": "hot"},
                                    {"temperature": [1]}, {"peer_personas": ["x"]}, {"peer_personas": {"abc": "x"}}])
def test_settings_page_opens_over_values_of_a_wrong_type_and_names_the_file(client, settings, stored):
    with open(settings.runtime_file, "w", encoding="utf-8") as f:
        json.dump(stored, f)
    for headers in ({}, HX):
        r = client.get("/settings", auth=AUTH, headers=headers)
        assert r.status_code == 200 and 'class="error"' in r.text and "runtime.json" in r.text
        assert 'name="temperature"' in r.text


@pytest.mark.parametrize("stored", [{"peer_personas": ["x"]}, {"peer_personas": {"abc": "x"}}])
def test_saving_over_values_the_form_cannot_fix_is_refused_and_names_the_file(client, settings, stored):
    with open(settings.runtime_file, "w", encoding="utf-8") as f:
        json.dump(stored, f)
    assert client.post("/settings", data=VALID, auth=AUTH).status_code == 400
    r = client.post("/settings", data=VALID, auth=AUTH, headers=HX)
    assert r.status_code == 422 and "runtime.json" in r.text and 'value="0.5"' in r.text
    assert saved(settings) == stored


def test_saving_replaces_a_broken_value_the_form_owns(client, settings):
    with open(settings.runtime_file, "w", encoding="utf-8") as f:
        json.dump({"temperature": "hot", "paused_peers": "abc", "active_persona": "rina"}, f)
    assert client.post("/settings", data=VALID, auth=AUTH).status_code == 303
    d = saved(settings)
    assert d["temperature"] == 0.5 and d["paused_peers"] == [7, 2000000005] and d["active_persona"] == "rina"
