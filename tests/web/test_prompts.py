import json

from ai.llm import PEER_LAYER, PERSONA_LAYER, SYSTEM_LAYER
from ai.service import AiService
from tests.web.conftest import AUTH
from web.prompts import prompt_peers, prompt_view

HX = {"HX-Request": "true"}
CHAT, OTHER_CHAT = 2000000001, 2000000002


def write(path, data):
    with open(path, "w", encoding="utf-8") as f:
        f.write(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False))


def persona(settings, slug, name, prompt):
    write(f"{settings.personas_dir}/{slug}.md", f"# {name}\n{prompt}")


def test_without_a_chat_the_layers_are_rules_and_persona(settings, ai_settings):
    persona(settings, "v", "В", "характер В")
    write(settings.runtime_file, {"active_persona": "v"})
    v = prompt_view(settings, AiService(ai_settings), None)
    assert [title for title, _ in v.layers] == [SYSTEM_LAYER, PERSONA_LAYER]
    assert (v.persona_name, v.note) == ("В", "") and "характер В" in v.message


def test_chat_note_sits_between_the_rules_and_the_persona(settings, ai_settings):
    write(settings.access_file, {"agent_peers": [CHAT], "peer_prompts": {str(CHAT): "тут все свои"}})
    v = prompt_view(settings, AiService(ai_settings), CHAT)
    assert [title for title, _ in v.layers] == [SYSTEM_LAYER, PEER_LAYER, PERSONA_LAYER]
    assert v.layers[1][1] == "тут все свои" and v.note == "тут все свои"
    assert v.message.index("тут все свои") > v.message.index(v.layers[0][1][:40])
    assert prompt_view(settings, AiService(ai_settings), OTHER_CHAT).note == ""


def test_persona_of_the_chat_wins_over_the_active_one(settings, ai_settings):
    persona(settings, "v", "В", "характер В")
    persona(settings, "rina", "Рина", "характер Рины")
    write(settings.runtime_file, {"active_persona": "v", "peer_personas": {str(CHAT): ["rina", "v"]}})
    v = prompt_view(settings, AiService(ai_settings), CHAT)
    assert v.persona_name == "Рина" and "характер Рины" in v.message
    assert prompt_view(settings, AiService(ai_settings), None).persona_name == "В"


def test_chats_to_choose_from_are_the_trusted_and_the_annotated(settings):
    write(settings.access_file, {"agent_peers": [OTHER_CHAT], "peer_prompts": {str(CHAT): "заметка"}})
    assert prompt_peers(settings) == [CHAT, OTHER_CHAT]
    write(settings.access_file, '{"agent_peers": "мусор"}')
    assert prompt_peers(settings) == []


def test_page_offers_chats_and_explains_the_order(client, settings):
    write(settings.access_file, {"agent_peers": [CHAT]})
    page = client.get("/prompts", auth=AUTH).text
    assert f'value="{CHAT}"' in page and "беседа 1" in page and SYSTEM_LAYER in page
    assert "по убыванию приоритета" in page and "user_prompts" not in page and "личка" not in page


def test_hx_returns_only_the_layers_of_the_chosen_chat(client, settings):
    write(settings.access_file, {"agent_peers": [CHAT], "peer_prompts": {str(CHAT): "тут все свои"}})
    with open(f"{settings.personas_dir}/rina.md", "w", encoding="utf-8") as f:
        f.write("# Рина\nхарактер Рины")
    write(settings.runtime_file, {"peer_personas": {str(CHAT): "rina"}})
    r = client.get(f"/prompts?peer={CHAT}", auth=AUTH, headers=HX)
    assert r.status_code == 200 and "<html" not in r.text and "<select" not in r.text
    assert 'id="layers"' in r.text and PEER_LAYER in r.text and "тут все свои" in r.text
    assert "Персона: <b>Рина</b>" in r.text
    assert "Рина" not in client.get("/prompts", auth=AUTH, headers=HX).text


def test_page_opens_over_a_broken_access_file(client, settings):
    write(settings.access_file, "{не json")
    page = client.get("/prompts", auth=AUTH)
    assert page.status_code == 200 and SYSTEM_LAYER in page.text
