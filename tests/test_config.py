from bot.config import parse_ids, parse_user_refs


def test_parse_ids_mixed_separators():
    assert parse_ids("1, 2 3,4") == frozenset({1, 2, 3, 4})
    assert parse_ids("") == frozenset()


def test_parse_user_refs_numeric_forms():
    ids, names = parse_user_refs("123 @456 @id3842758 id99")
    assert ids == frozenset({123, 456, 3842758, 99})
    assert names == frozenset()


def test_parse_user_refs_screen_names():
    ids, names = parse_user_refs("@kamyrc, @Aktan durov")
    assert ids == frozenset()
    assert names == frozenset({"kamyrc", "aktan", "durov"})


def test_parse_user_refs_empty():
    assert parse_user_refs("") == (frozenset(), frozenset())


def test_settings_keep_nothing_of_the_old_reply_path():
    from bot.config import Settings

    gone = {"llm_provider", "context_messages", "reply_delay_min", "reply_delay_max", "dm_debounce_seconds",
            "onboarding_questions", "onboarding_ttl_hours"}
    assert gone & set(Settings.model_fields) == set()


def test_vk_client_keeps_no_helpers_of_the_old_reply_path():
    from bot.vk import VkClient

    assert not hasattr(VkClient, "history") and not hasattr(VkClient, "resolve_gender")
