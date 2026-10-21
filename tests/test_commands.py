from common.commands import addressed_to_bots, looks_like_command


def test_moderation_words_and_slash_commands_look_like_commands():
    for text in ("кик", "Бан @x", "чс", "!кик", "/бан", "добавить id5", "вернуть", "kick", "ban", "кик,",
                 "/help", "/доверие @x", "/модерация выкл", "!что угодно", "-смс", "-СМС", "стата", "Статистика",
                 "неактив."):
        assert looks_like_command(text), text
    for text in ("не надо кик", "кикни", "", None, "привет", "ну /help", "- пункт списка", "-5 градусов"):
        assert not looks_like_command(text), text


def test_slash_messages_and_the_delete_command_are_addressed_to_bots():
    assert addressed_to_bots("/help") and addressed_to_bots("  /статус")
    assert addressed_to_bots("-смс") and addressed_to_bots("-СМС.") and not addressed_to_bots("- смс пришла")
    assert not addressed_to_bots("бан за что?") and not addressed_to_bots("привет /help") and not addressed_to_bots(None)


def test_words_vk_bot_learned_later_look_like_commands():
    for text in ("мут", "Мут @x", "mute", "пермобан id5", "помощь", "Помощь!", "помощь?"):
        assert looks_like_command(text), text
    for text in ("помощь нужна", "нужна помощь", "мутно как-то"):
        assert not looks_like_command(text), text


def test_every_delete_spelling_vk_bot_accepts_looks_like_a_command():
    for text in ("--смс", "-/смс", "-!смс", "---смс", "--смс.", "-смс,", "-смс:", "-смс!", "-СМС.", "-/!-смс",
                 "--смс @x", "-смс\nпричина"):
        assert looks_like_command(text), text


def test_every_command_word_is_matched_the_way_vk_bot_normalises_it():
    for word in ("кик", "kick", "бан", "ban", "чс", "пермобан", "добавить", "вернуть", "мут", "mute"):
        for text in (word, word.upper(), word.capitalize() + " @x", word + ",.:!", "!/" + word, "/!" + word + "."):
            assert looks_like_command(text), text


def test_dash_in_ordinary_speech_is_not_a_command():
    for text in ("- купить хлеб", "-", "--", "— смс пришла", "- смс пришла", "-смска", "--смс-ка", "-смс?", "смс",
                 "смс.", "-кик", "--бан", "-мут @x", "-помощь", "-стата", "-привет", "-5 градусов", "кик-бокс",
                 "бан?", "смс -смс"):
        assert not looks_like_command(text), text
