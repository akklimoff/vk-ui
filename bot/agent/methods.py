import re
from dataclasses import dataclass, field
from typing import Mapping

READ, WRITE_HERE, OUTWARD, DESTRUCTIVE, UNLISTED = "read", "write_here", "outward", "destructive", "unlisted"


@dataclass(frozen=True)
class Method:
    name: str
    kind: str
    peer_param: str = ""
    chat_param: str = ""
    elsewhere: str | None = None
    params: frozenset[str] = frozenset()
    escalate: Mapping[str, str] = field(default_factory=dict)
    json_params: frozenset[str] = frozenset()
    title: str = ""
    note: str = ""


def row(name: str, kind: str, *params: str, **rest) -> Method:
    return Method(name, kind, params=frozenset(params), **rest)


# таблица ничего не запрещает: она задаёт класс действия (от него зависят «да» в «Избранном» и потолок записей),
# адрес по умолчанию и подсказку модели; метод не из таблицы вызывается так же, запрещённые — в DENIED_*
METHODS: tuple[Method, ...] = (
    row("messages.getHistory", READ, "count", "offset", "start_message_id", "rev", peer_param="peer_id",
        note="история переписки, от новых к старым, до 200 за раз; дальше — offset"),
    row("messages.search", READ, "q", "count", "date", "offset", peer_param="peer_id",
        note="поиск по сообщениям одной переписки"),
    row("messages.searchConversations", READ, "q", "count",
        note="найти беседу или диалог по названию или имени — так узнаётся peer_id другой беседы"),
    row("messages.getConversations", READ, "count", "offset", "filter",
        note="список всех диалогов и бесед аккаунта с последним сообщением, от свежих к старым"),
    row("messages.getConversationMembers", READ, "fields", peer_param="peer_id",
        note="участники: кто админ, кто кого пригласил и когда"),
    row("messages.getConversationsById", READ, peer_param="peer_ids", note="название и настройки беседы"),
    row("messages.getByConversationMessageId", READ, "conversation_message_ids", peer_param="peer_id",
        note="сообщения по их номерам в переписке (conversation_message_id)"),
    row("messages.getHistoryAttachments", READ, "media_type", "count", "start_from", peer_param="peer_id",
        note="вложения переписки: photo, video, audio, doc, link"),
    row("messages.getInviteLink", READ, "reset", peer_param="peer_id", escalate={"reset": DESTRUCTIVE},
        title="Сбросить ссылку-приглашение",
        note="ссылка-приглашение в беседу; reset делает старую ссылку нерабочей"),
    row("users.get", READ, "user_ids", "name_case", "fields",
        note="профили по id или нику; в fields — что нужно: bdate, city, status, about, counters, photo_max_orig, "
             "last_seen, relation и т. д."),
    row("users.search", READ, "q", "count", "city", "age_from", "age_to", "fields",
        note="найти человека по имени и фамилии"),
    row("friends.get", READ, "user_id", "count", "offset", "order", "fields",
        note="друзья: свои или другого человека; с fields сразу придут имена"),
    row("friends.search", READ, "q", "count", "fields", note="найти среди своих друзей по имени"),
    row("friends.getRequests", READ, "out", "count", note="заявки в друзья"),
    row("groups.get", READ, "user_id", "extended", "count", note="сообщества, в которых состоит человек"),
    row("groups.getById", READ, "group_id", "group_ids", "fields", note="сообщества по id или адресу"),
    row("utils.resolveScreenName", READ, "screen_name", note="чей это ник или адрес"),
    row("wall.get", READ, "owner_id", "domain", "count", "offset", note="посты со стены человека или сообщества"),
    row("photos.getAll", READ, "owner_id", "count", "offset", "extended", note="все фото человека или сообщества"),
    row("photos.get", READ, "owner_id", "album_id", "count", "rev", "extended",
        note="фото альбома: album_id profile — аватарки, wall — со стены, saved — сохранённые"),
    row("polls.getById", READ, "owner_id", "poll_id", note="опрос и его результаты"),
    row("polls.getVoters", READ, "owner_id", "poll_id", "answer_ids", note="кто как проголосовал"),
    row("messages.send", WRITE_HERE, "message", "reply_to", "attachment", "forward_messages", "sticker_id",
        peer_param="peer_id", elsewhere=OUTWARD, title="Отправить сообщение",
        note="отдельное сообщение; сам ответ на просьбу отправлять им не нужно, он уйдёт без этого; attachment — "
             "вложения через запятую: photo<owner>_<id>, video…, doc…, wall…, poll…"),
    row("messages.edit", WRITE_HERE, "message", "conversation_message_id", "attachment", "keep_forward_messages",
        peer_param="peer_id", elsewhere=OUTWARD, title="Изменить сообщение", note="исправить своё сообщение"),
    row("messages.pin", WRITE_HERE, "conversation_message_id", "message_id", peer_param="peer_id",
        elsewhere=OUTWARD, title="Закрепить сообщение", note="закрепить сообщение"),
    row("messages.unpin", WRITE_HERE, peer_param="peer_id", elsewhere=OUTWARD, title="Открепить сообщение",
        note="открепить сообщение"),
    row("messages.sendReaction", WRITE_HERE, "cmid", "reaction_id", peer_param="peer_id", elsewhere=OUTWARD,
        title="Поставить реакцию", note="реакция на сообщение"),
    row("messages.markAsRead", WRITE_HERE, "mark_conversation_as_read", peer_param="peer_id", elsewhere=OUTWARD,
        title="Отметить прочитанным", note="отметить переписку прочитанной"),
    row("polls.create", WRITE_HERE, "question", "add_answers", "is_anonymous", "is_multiple", "end_date",
        "owner_id", json_params=frozenset({"add_answers"}), title="Создать опрос",
        note="создать опрос; add_answers — массив вариантов; чтобы опрос появился в беседе, отправь его "
             "вложением poll<owner_id>_<id>"),
    row("polls.addVote", OUTWARD, "owner_id", "poll_id", "answer_ids", title="Проголосовать в опросе",
        note="проголосовать"),
    row("likes.add", OUTWARD, "type", "owner_id", "item_id", title="Поставить лайк",
        note="лайк; type — post, photo, video, comment"),
    row("likes.delete", OUTWARD, "type", "owner_id", "item_id", title="Убрать лайк", note="убрать лайк"),
    row("wall.post", OUTWARD, "message", "owner_id", "publish_date", "from_group", "attachments",
        title="Опубликовать пост", note="пост на стену: свою или, с owner_id, чужую; publish_date делает его отложенным"),
    row("wall.createComment", OUTWARD, "owner_id", "post_id", "message", "reply_to_comment",
        title="Написать комментарий", note="комментарий к посту"),
    row("wall.repost", OUTWARD, "object", "message", "group_id", title="Сделать репост",
        note="репост; object — wall<owner>_<id>"),
    row("photos.createComment", OUTWARD, "owner_id", "photo_id", "message", title="Написать комментарий к фото",
        note="комментарий к фото"),
    row("friends.add", OUTWARD, "user_id", "text", title="Заявка в друзья",
        note="отправить или принять заявку в друзья"),
    row("groups.join", OUTWARD, "group_id", title="Вступить в сообщество", note="вступить в сообщество"),
    row("status.set", OUTWARD, "text", title="Сменить статус", note="статус на странице"),
    row("account.saveProfileInfo", OUTWARD, "first_name", "last_name", "bdate", "status", "home_town", "relation",
        title="Изменить профиль", note="данные профиля; смену имени VK отправляет на проверку"),
    row("photos.saveOwnerPhoto", OUTWARD, "from_url", title="Сменить аватарку",
        note="поставить аватаркой картинку, которая уже есть во ВКонтакте: from_url — её url из вложения, "
             "альбома или профиля"),
    row("messages.setChatPhoto", OUTWARD, "from_url", chat_param="chat_id", title="Сменить фото беседы",
        note="поставить фото беседы: from_url — url картинки из ВКонтакте"),
    # photos.getMessagesUploadServer токену официального приложения закрыт (ошибка 15), стена принимает загрузку
    row("photos.saveWallPhoto", WRITE_HERE, "from_url", "group_id", title="Загрузить картинку",
        note="загрузить картинку по её url из ВКонтакте: вернёт фото, его вложение photo<owner_id>_<id> годится "
             "и для messages.send, и для wall.post; фото, у которого уже есть owner_id и id, загружать не нужно — "
             "прикладывай сразу"),
    row("messages.createChat", OUTWARD, "user_ids", "title", title="Создать беседу", note="новая беседа"),
    row("messages.addChatUser", OUTWARD, "user_id", "visible_messages_count", chat_param="chat_id",
        title="Пригласить в беседу", note="добавить человека в беседу"),
    row("messages.delete", DESTRUCTIVE, "cmids", "delete_for_all", "spam", peer_param="peer_id",
        title="Удалить сообщения", note="удалить сообщения по их номерам в переписке (conversation_message_id)"),
    row("messages.removeChatUser", DESTRUCTIVE, "user_id", "member_id", chat_param="chat_id",
        title="Исключить из беседы", note="исключить из беседы; member_id сообщества — с минусом"),
    row("messages.editChat", DESTRUCTIVE, "title", chat_param="chat_id", title="Переименовать беседу",
        note="переименовать беседу"),
    row("wall.delete", DESTRUCTIVE, "owner_id", "post_id", title="Удалить пост", note="удалить пост"),
    row("friends.delete", DESTRUCTIVE, "user_id", title="Удалить из друзей", note="удалить из друзей"),
    row("groups.leave", DESTRUCTIVE, "group_id", title="Выйти из сообщества", note="выйти из сообщества"),
    row("account.ban", DESTRUCTIVE, "owner_id", title="Занести в чёрный список", note="в чёрный список"),
    row("account.unban", OUTWARD, "owner_id", title="Убрать из чёрного списка", note="убрать из чёрного списка"),
)

BY_NAME = {method.name.lower(): method for method in METHODS}

METHOD_NAME = re.compile(r"[A-Za-z]+(\.[A-Za-z]+)?")
# execute выполняет на сервере VK произвольный набор вызовов и обошёл бы этот список целиком
DENIED_PREFIXES = ("execute.", "auth.", "secure.", "ads.", "orders.")
DENIED_EXACT = frozenset(name.lower() for name in (
    "execute", "account.changePassword", "account.registerDevice", "account.unregisterDevice",
    "messages.deleteConversation", "messages.deleteDialog", "friends.deleteAllRequests",
))
# ключ long poll даёт читать все события аккаунта мимо агента, callback-сервер — слать их на чужой адрес
DENIED_PARTS = ("longpollserver", "callback")
READ_PREFIXES = ("get", "search", "is", "are", "check", "resolve", "lookup")


def find_method(name: str) -> Method | None:
    return BY_NAME.get(name.lower())


def action_title(name: str) -> str:
    row = find_method(name)
    return row.title if row and row.title else name


def denied(name: str) -> bool:
    lowered = name.lower()
    if lowered in DENIED_EXACT or lowered.startswith(DENIED_PREFIXES):
        return True
    return any(part in lowered for part in DENIED_PARTS)


def reads_by_name(name: str) -> bool:
    return name.rpartition(".")[2].lower().startswith(READ_PREFIXES)
