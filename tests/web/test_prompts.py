import json

from ai.llm import PERSONA_LAYER, PRIVATE_LAYER, SYSTEM_LAYER, USER_LAYER
from tests.web.conftest import AUTH
from web.services import prompt_view


def test_prompt_view_layers_for_group_chat(settings):
    open(f"{settings.personas_dir}/v.md", "w").write("# В\nперсона")
    json.dump({"active_persona": "v"}, open(settings.runtime_file, "w"))
    v = prompt_view(settings, user_key=None)
    assert [t for t, _ in v.layers] == [SYSTEM_LAYER, PERSONA_LAYER]
    assert v.persona_name == "В" and "персона" in v.message


def test_prompt_view_for_private_user(settings):
    json.dump({"private_prompt": "лично", "user_prompts": {"@bob": "это Боб"}}, open(settings.access_file, "w"))
    v = prompt_view(settings, user_key="@bob")
    assert [t for t, _ in v.layers] == [SYSTEM_LAYER, USER_LAYER, PRIVATE_LAYER, PERSONA_LAYER]
    assert "это Боб" in v.message


def test_prompts_page_lists_user_keys(client, settings):
    json.dump({"user_prompts": {"@bob": "x"}}, open(settings.access_file, "w"))
    page = client.get("/prompts", auth=AUTH).text
    assert "@bob" in page and SYSTEM_LAYER in page


def test_prompts_hx_returns_layers_partial_for_selected_user(client, settings):
    json.dump({"user_prompts": {"@bob": "это Боб"}}, open(settings.access_file, "w"))
    r = client.get("/prompts?user=@bob", auth=AUTH, headers={"HX-Request": "true"})
    assert r.status_code == 200 and "<html" not in r.text and "<select" not in r.text
    assert 'id="layers"' in r.text and USER_LAYER in r.text and "это Боб" in r.text
