import pytest

from ai.personas import (PersonaFile, list_personas, load_persona, parse_persona,
                          persona_path, render_persona)


def test_parse_takes_name_from_heading():
    p = parse_persona("valya", "# Валентина\n\nТы — Валя.\n")
    assert (p.slug, p.name, p.prompt) == ("valya", "Валентина", "Ты — Валя.")


def test_parse_without_heading_uses_slug_as_name():
    p = parse_persona("bob", "просто текст")
    assert (p.name, p.prompt) == ("bob", "просто текст")


def test_render_roundtrip():
    text = render_persona("Имя", "промпт\nдве строки")
    assert parse_persona("x", text).prompt == "промпт\nдве строки"


def test_persona_path_rejects_bad_slug(tmp_path):
    with pytest.raises(ValueError):
        persona_path(str(tmp_path), "../etc")


def test_list_and_load(tmp_path):
    (tmp_path / "b.md").write_text("# B\nб")
    (tmp_path / "a.md").write_text("# A\nа")
    (tmp_path / "ignore.txt").write_text("x")
    assert [p.slug for p in list_personas(str(tmp_path))] == ["a", "b"]
    assert load_persona(str(tmp_path), "a").prompt == "а"
    assert load_persona(str(tmp_path), "zzz") is None
    assert list_personas(str(tmp_path / "missing")) == []


def test_persona_file_falls_back(tmp_path):
    pf = PersonaFile(str(tmp_path), "nope", fallback_prompt="дефолт")
    assert pf.current() == "дефолт"
    (tmp_path / "nope.md").write_text("# N\nновый")
    assert pf.current() == "новый"


def test_agent_prompt_delegates_tone_to_persona():
    from ai.config import DEFAULT_AGENT_PROMPT

    fmt = DEFAULT_AGENT_PROMPT.split("Формат:")[1].split("Безопасность:")[0]
    assert "личности" in fmt
