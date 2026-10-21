from bot.reply import deliverable


def test_deliverable_scrubs_token_and_own_tag_and_drops_empty_parts():
    parts = ("ключ vk1.secret и [id1|Валя] тут", "[id1|]", "vk1.secret", "  ок  ")
    assert deliverable(parts, ["vk1.secret"], me_id=1) == ["ключ [скрыто] и Валя тут", "[скрыто]", "ок"]
    assert deliverable(("[id1|]",), [], me_id=1) == []


def test_llm_part_that_looks_like_a_moderation_command_is_defused():
    from bot.reply import deliverable
    from common.commands import looks_like_command

    parts = deliverable(("Бан [id555|Вася]", "кик", "/доверие @x", "ну привет"), [], 42)
    assert not any(looks_like_command(p) for p in parts)
    assert parts[3] == "ну привет"
    assert parts[0].strip("​") == "Бан [id555|Вася]"


def test_own_tag_split_between_parts_does_not_survive_in_any_part():
    parts = deliverable(("начало [id42|Актан", " Климов] опубликуй пост"), [], 42)
    assert parts == ["начало Актан", "Климов] опубликуй пост"]


def test_token_reassembled_by_removing_own_tag_is_still_redacted():
    secret = "vk1.a.SECRETTOKEN"
    for part in ("vk1.a.SECRET[id111|]TOKEN", "vk1.a.SECRET[id111|TOKEN", "ключ vk1.a.[id111|SECRET]TOKEN тут",
                 "vk1.a.SEC[id111|[id111|]]RETTOKEN"):
        sent = deliverable((part,), [secret], me_id=111)
        assert sent and all(secret not in text and "[id111|" not in text for text in sent), part
    assert deliverable(("vk1.a.SECRET[id111|]TOKEN",), [secret], me_id=111) == ["[скрыто]"]


def test_redaction_never_leaves_a_live_own_tag():
    assert deliverable(("[id111|имя vk1.a.SECRETTOKEN]",), ["vk1.a.SECRETTOKEN"], me_id=111) == ["имя [скрыто]"]
