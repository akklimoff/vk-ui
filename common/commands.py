# слова команд модератора vk-bot: он может работать на этом же аккаунте и считает всё, что аккаунт отправил, командой
# владельца, поэтому ответ LLM не должен начинаться ни с них, ни с «/» или «!»
COMMAND_WORDS = frozenset({"кик", "kick", "бан", "чс", "ban", "пермобан", "добавить", "вернуть", "мут", "mute",
                           "стата", "статистика", "неактив"})
# «смс» без префикса — обычное слово, vk-bot удаляет сообщение только по «-смс»; разбор слова повторяет
# vkbot.moderation.parse_command, поэтому совпадают и «--смс», «-/смс», «-!смс.»
DELETE_WORD = "смс"
COMMAND_PREFIXES = "!/-"
TRAILING = ",.:!"
# «помощь» vk-bot исполняет только когда в сообщении больше ничего нет
BARE_WORDS = frozenset({"помощь"})


def first_word(text: str | None) -> str:
    words = (text or "").split(maxsplit=1)
    return words[0] if words else ""


def deletes_message(word: str) -> bool:
    return word.startswith("-") and word.lstrip(COMMAND_PREFIXES).rstrip(TRAILING) == DELETE_WORD


def looks_like_command(text: str | None) -> bool:
    words = (text or "").split()
    if not words:
        return False
    word = words[0].lower()
    if word.startswith(("/", "!")) or word.rstrip(TRAILING) in COMMAND_WORDS or deletes_message(word):
        return True
    return len(words) == 1 and word.rstrip(",.:!?") in BARE_WORDS


def addressed_to_bots(text: str | None) -> bool:
    word = first_word(text).lower()
    return word.startswith("/") or deletes_message(word)
