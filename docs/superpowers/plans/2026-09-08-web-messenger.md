# Web Messenger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Страница `/im` в админке — мессенджер, максимально похожий на веб-клиент ВКонтакте: список диалогов, переписка от имени аккаунта бота (текст, ответ-цитата, голосовые из `.ogg`/`.mp3`), и управление ботом прямо в чате: кому он отвечает, какой персоной, с каким промптом, кого игнорирует.

**Architecture:** Мессенджер живёт в процессе `web` как пакет `web/im/` и ходит в VK напрямую через `bot/vk.py` (единственный модуль, знающий `vk_api`). Всё, что читает VK, превращается в неизменяемые view-модели чистыми функциями (`web/im/views.py`), и только они попадают в шаблоны. Управление ботом — правки `config/access.json` и `config/runtime.json` чистыми функциями над словарями (`web/im/controls.py`) плюс атомарная запись; бот подхватывает по mtime, как и сейчас. Обновления — htmx-поллинг (открытый чат каждые 3 с, список каждые 10 с, только при видимой вкладке); ничего из VK не сохраняется на диск.

**Tech Stack:** Python 3.12, FastAPI 0.141 + Jinja2 + htmx + Alpine.js + Pico.css (вендорятся в `web/static`, без сборки), `vk_api` 11.10 (`VkUpload.audio_message` для голосовых), pytest + `fastapi.testclient`.

**Spec:** раздел «Design» ниже — он же спек (решения приняты автономно, спорные места помечены «Допущение»).

## Global Constraints

- `bot/vk.py` — единственный модуль с `import vk_api`; всё остальное тестируется без сети через `vk_factory` в `create_app`.
- Порядок слоёв системного промпта не меняется; мессенджер только редактирует содержимое слоёв `user_prompts`/`peer_prompts`.
- Приватность: текст чужих сообщений не пишется в `state/`, в логи и в query-string (только в теле POST); загруженные файлы не сохраняются на диск (`io.BytesIO`), после отправки в VK отбрасываются; `uvicorn` access-log видит только пути.
- Правки `config/` — только через `write_json_atomic` (tmp + `os.replace`), схема файлов не меняется: существующие записи вида `"@nick"` сохраняются как есть.
- Лимит VK для user-токена ≈ 3 запроса/с: поллинг открытого чата — `every 3s`, списка — `every 10s`, оба с `[document.visibilityState === 'visible']`; на один поллинг — один вызов VK.
- Страница = `templates/<page>.html` (обёртка) + `templates/partials/<page>.html`; роуты отвечают через `render.Renderer` (`page`/`saved`/`invalid`), как описано в CLAUDE.md.
- htmx не обрабатывает DOM, вставленный Alpine (`x-if`, `<template>`): элементы с `hx-*` должны быть в исходной разметке, прятать их через `x-show` + `x-cloak`.
- Комментарии в коде — только «почему» (правило 4 CLAUDE.md). Коммиты — одна строка на английском, без LLM-атрибуции (правило 5).
- Обращение к пользователю в ответах — «Актан».

---

## Design

### Что видит пользователь

Двухпанельная страница на всю ширину (`main` без `.container`), как на скриншоте VK:

- **Слева** — «Мессенджер»: поиск (фильтр по названию, на клиенте), переключатель «Только непрочитанные», список диалогов: круглый аватар 56px, зелёная точка «онлайн», название, иконка «без звука», превью «Автор: текст» (или «Стикер», «Голосовое», «Фото»), время последнего сообщения, синий кружок с числом непрочитанных, иконка закрепа. Справа от названия — бейдж режима бота: **авто** (зелёный), **по тегу** (серый), **знакомство**, **пауза**, **блок**, **молчит** (сообщества).
- **Справа** — открытый чат: шапка (аватар, название, «N участников, M онлайн» или «онлайн/был(а) недавно», бейдж режима бота, шестерёнка «Бот в этом чате», ссылка «в VK»), лента сообщений плоскими рядами в стиле VK-десктопа: аватар + синее имя у первого сообщения серии, последующие без аватара, время справа, у своих — ✓/✓✓ по `out_read`; чипы дат «сегодня / вчера / 8 сентября»; свои сообщения, отправленные ботом, помечены бейджем «бот · персона». Вложения: фото (превью, клик — оригинал в новой вкладке), стикер (256px), голосовое (`<audio controls>` + длительность + расшифровка, если VK её сделал), документ/ссылка (ссылка), видео (превью + название), пересланные («N пересланных»), цитата ответа (полоска слева: автор + текст), сервисные действия («X пригласил Y»).
- **Композер** внизу: ⊕ (файл голосового `.ogg`/`.mp3`), поле «Сообщение» (Enter — отправить, Shift+Enter — перенос), кнопка отправки, кнопка «✨ черновик от бота» (заполняет поле ответом LLM, не отправляет). У любого сообщения по наведению — «ответить» (цитата), у своих — «удалить».
- **Панель «Бот в этом чате»** (шестерёнка, выезжает поверх ленты): текущий режим и почему; переключатели, применимые к чату; персона(ы) для чата; промпт слоя собеседника/беседы; для бесед — список участников с переключателем «не отвечать этому участнику здесь».
- **Мобильный** (`< 768px`): одна панель — список или чат, кнопка «‹» назад.

Допущение: «1 в 1» понимается как раскладка, ритм и палитра VK (синий `#0077ff`, светло-серые подложки, плоские ряды сообщений, круглые аватары), а не пиксельная копия; иконки — inline-SVG, стикеры/эмодзи-пикер/звонки/поиск по сообщениям не делаем.

### Данные из VK

Все запросы идут через новые методы `VkClient` (Task 1). Формы ответов VK, на которые опираются парсеры (проверяются спайком в Task 0):

```text
messages.getConversations(count, offset, extended=1, fields)
  → {count, unread_count, items: [{conversation, last_message}], profiles: [...], groups: [...]}
  conversation: {peer: {id, type: user|chat|group, local_id}, in_read, out_read, last_message_id,
                 unread_count?, sort_id: {major_id, minor_id}, push_settings?: {disabled_forever, ...},
                 chat_settings?: {title, members_count, photo?: {photo_50, photo_100}, owner_id, active_ids}}
  last_message: как сообщение ниже
messages.getHistory(peer_id, count, start_message_id?, offset?, extended=1, fields)
  → {count, items: [message...] (новые первыми), profiles, groups, conversations: [conversation]}
  message: {id, date, peer_id, from_id, text, out, attachments: [{type, <type>: {...}}],
            fwd_messages?: [...], reply_message?: {from_id, text, ...}, action?: {type, member_id?, text?}}
  attachments: photo {sizes: [{type, url, width, height}]}; sticker {images: [{url, width, height}]};
               audio_message {id, owner_id, duration, waveform, link_ogg, link_mp3, access_key,
                              transcript?, transcript_state?}; doc {title, url, ext, size};
               video {title, image: [{url, width, height}]}; audio {artist, title}; link {url, title};
               wall {...}
messages.getConversationMembers(peer_id, fields)
  → {count, items: [{member_id, is_admin?, is_owner?, invited_by, join_date}], profiles, groups}
messages.send(peer_id, random_id, message?, reply_to?, attachment?) → message_id
messages.markAsRead(peer_id, mark_conversation_as_read=1)
messages.getById(message_ids, extended=1, fields) → {items: [message], profiles, groups}
docs.getMessagesUploadServer(type=audio_message, peer_id) → upload → docs.save
  → {type: "audio_message", audio_message: {id, owner_id, access_key, ...}}
  attachment для send: "audio_message{owner_id}_{id}_{access_key}"
```

`profiles` — `{id, first_name, last_name, photo_50, photo_100, online, sex, screen_name}`, `groups` — `{id, name, photo_50}` (в сообщениях `from_id` сообщества отрицательный).

### View-модели (`web/im/views.py`)

Неизменяемые датаклассы; шаблоны знают только их:

```python
Peer(id, title, photo, kind: "user"|"chat"|"group", online: bool, members: int)
Attachment(kind: "photo"|"sticker"|"voice"|"doc"|"video"|"audio"|"link"|"wall"|"other",
           url, preview, title, duration: int, transcript)
Quote(author, text)
BotMark(persona, model)
Message(id, ts, from_id, author, photo, text, out, read, attachments: tuple[Attachment, ...],
        reply: Quote | None, fwd_count: int, action: str, bot: BotMark | None)
Row(message, day: str | None, head: bool)      # day — чип даты перед сообщением, head — показать аватар и имя
Dialog(peer, last: Message | None, unread: int, muted: bool, pinned: bool)
Profiles(raw)                                  # name(id) / photo(id) / online(id) по profiles+groups
```

Чистые функции: `parse_conversations(raw, me_id, marks) -> list[Dialog]`, `parse_history(raw, me_id, marks) -> tuple[list[Message], int out_read]`, `attachment_of(att) -> Attachment`, `rows(messages, now, tz) -> list[Row]` (сообщения в хронологическом порядке, чипы дат, серии одного автора в пределах 5 минут), `preview(message) -> str` (текст для списка: «Стикер», «Голосовое», …), `bot_marks(records) -> dict[int, BotMark]` (из `replies.jsonl`; для этого бот начинает писать все `reply_message_ids` разбитого ответа, Task 3).

Даты считаются на сервере в зоне `Settings.web_timezone` (по умолчанию `Europe/Moscow`), чтобы чипы «сегодня/вчера» были детерминированы и тестируемы.

### Режим бота и управление (`web/im/modes.py`, `web/im/controls.py`)

`bot_mode(peer_id, lists: AccessLists, rt: RuntimeSettings) -> BotMode(label, kind, personas, reason)` — чистая проекция тех же правил, что и `limits.should_reply` + пауза, в порядке приоритета: `peer_id < 0` → «молчит»; пауза (глобальная или `paused_peers`) → «пауза»; `blocked_peers` / (личка и `blocked_users`) → «блок»; `allowed_peers` непустой и чата в нём нет → «вне белого списка»; личка: `auto_reply_users` → «авто», иначе «по тегу»; беседа: `onboarding_peers` → «знакомство», `auto_reply_peers` → «авто», иначе «по тегу». `personas` — из `runtime.peer_personas` для чата, иначе `active_persona`.

`chat_controls(peer_id, lists, rt) -> ChatControls(peer_id, private, auto, onboarding, blocked, paused, personas, prompt, blocked_members)` — состояние переключателей панели.

Правки файлов — чистые функции над сырыми словарями, сохраняющие чужие записи (`"@nick"`) и убирающие все записи, означающие того же человека (числовые и ники, разрешённые через `vk.resolve_screen_names`):

```python
set_member(data, field, ref_id, on, resolve=None) -> dict     # blocked_users, auto_reply_users, blocked_peers, auto_reply_peers, onboarding_peers
set_keyed_text(data, field, ref_id, text, resolve=None) -> dict  # user_prompts / peer_prompts
set_peer_blocked(data, peer_id, user_id, on, resolve=None) -> dict  # peer_blocked_users[peer]
set_paused_peer(data, peer_id, on) -> dict                     # runtime.paused_peers
set_peer_personas(data, peer_id, slugs) -> dict                # runtime.peer_personas[peer]
```

Роут переключателя: прочитать файл → применить функцию → `write_json_atomic` → вернуть partial панели + OOB-бейдж режима в шапке и в списке.

### Голосовые (`web/im/voice.py`, `VkClient.upload_voice`)

Принимаются `.ogg` (Opus; сигнатура `OggS`) и `.mp3` (`ID3` или MPEG-sync `0xFF 0xE0+`), до 20 МБ (`MAX_VOICE_BYTES`); тип определяется по содержимому, расширение только подсказка. `sniff_voice(data, filename) -> "ogg"|"mp3"` или `ValueError` с понятным текстом. VK для `audio_message` ждёт Ogg Opus, поэтому `.mp3` всегда конвертируется в `.ogg` через `ffmpeg` (`to_ogg(data) -> bytes`: `-c:a libopus -b:a 48k -ar 48000 -ac 1 -f ogg`, вход и выход через pipe, ничего на диске, таймаут 60 с). `prepare_voice(data, filename) -> bytes` объединяет обе функции и всегда возвращает ogg-байты. `ffmpeg` ставится в образ `web` (`apt-get install ffmpeg`, Debian-сборка включает `libopus`); локально нужен `brew install ffmpeg`. Ogg-байты оборачиваются в `io.BytesIO` с атрибутом `name="voice.ogg"` (иначе `vk_api.FilesOpener` отправит файл как `.jpg`), уходят в `VkUpload.audio_message(buf, peer_id)`; из ответа собирается строка `audio_message{owner}_{id}_{access_key}` и передаётся в `messages.send(attachment=...)` вместе с текстом, если он есть.

Входящие голосовые: `<audio controls preload="none" src="{{ link_mp3 }}">`, рядом длительность `0:20` и расшифровка серым. Ссылки VK CDN грузятся браузером напрямую, через сервер не проксируются.

### Роуты (`web/im/routes.py`, `APIRouter`, подключается в `create_app`)

| Метод и путь | Ответ |
|---|---|
| `GET /im?sel=<peer>` | полная страница; `sel` — открытый чат (как `vk.com/im?sel=`) |
| `GET /im/dialogs` | partial `im_dialogs` — `<ul>` списка (поллинг `every 10s`, `hx-swap="innerHTML"` в контейнер списка, чтобы не терять скролл) |
| `GET /im/{peer}` | partial `im_chat` (шапка + лента + композер + поллер), `HX-Push-Url: /im?sel=<peer>` |
| `GET /im/{peer}/messages?after=<id>` | partial `im_rows` с новыми сообщениями (`beforeend` в `#messages`) + OOB `#chat-state` (`out_read`, онлайн) |
| `GET /im/{peer}/messages?before=<id>` | partial `im_rows` со старыми (сентинел `hx-trigger="intersect once"` наверху ленты заменяется рядами + новым сентинелом) |
| `POST /im/{peer}/send` (`text`, `reply_to`, `voice` multipart) | partial `im_rows` с отправленным сообщением (`messages.getById`), 422 с тостом при ошибке |
| `POST /im/{peer}/read` | 204; вызывается при открытии чата и после новых входящих, если вкладка видима и не включён режим «читать без отметки» (переключатель в панели, хранится в `localStorage`) |
| `POST /im/{peer}/messages/{id}/delete` | 200, `hx-swap="delete"` ряда |
| `GET /im/{peer}/bot` | partial `im_bot` — панель бота |
| `POST /im/{peer}/bot/{switch}` (`auto`,`onboarding`,`blocked`,`paused`; поле `on`) | partial `im_bot` + OOB-бейджи |
| `POST /im/{peer}/bot/prompt` (`text`) | partial `im_bot` |
| `POST /im/{peer}/bot/personas` (`slug` multi) | partial `im_bot` |
| `POST /im/{peer}/bot/members/{user}` (`on`) | partial `im_bot` |
| `POST /im/{peer}/draft` | `text/plain` — ответ LLM через `bot.reply.generate_reply` (та же цепочка, что у бота: персона чата, слои промпта, защита от повторов), в VK не отправляется |

Ошибки VK/LLM возвращаются через `render.invalid` (422 + тост) с `sanitize_reply` над текстом ошибки, как в песочнице.

### Шаблоны и статика

- `templates/im.html` (обёртка, `{% block main_class %}im-shell{% endblock %}`) и `partials/im.html` (панели), `partials/im_dialogs.html`, `partials/im_chat.html`, `partials/im_rows.html`, `partials/im_bot.html`, `partials/im_badge.html` (бейдж режима, используется и в списке, и в шапке, и как OOB).
- `web/static/im.css` — раскладка и палитра VK (`--im-blue: #0077ff`, `--im-side: #f5f5f7`, тёмная тема через Pico-переменные), `web/static/im.js` — Alpine-компоненты `im` (панели, фильтр, «только непрочитанные»), `chat` (скролл к низу, `outRead`, отметка прочитанного), `composer` (Enter/Shift+Enter, чип файла, цитата, черновик).
- `base.html`: `<main class="{% block main_class %}container{% endblock %}">`, пункт «Мессенджер» в навигации первым.

### Обновления в реальном времени

Поллинг (см. роуты). Один вызов VK на тик: `getHistory(count=50)` для открытого чата (фильтр `id > after` на сервере), `getConversations(count=60)` для списка. Ряды новых сообщений всегда идут с аватаром (`head=True`) — серии не склеиваются через границу поллинга; это осознанное упрощение v1. Переход на `messages.getLongPollHistory(ts, pts)` (один запрос на все чаты) — отдельная задача после того, как поллинг упрётся в лимиты.

### Тестирование

- Чистые функции (`views`, `modes`, `controls`, `voice`) — юнит-тесты на фикстурах `tests/web/im_fixtures.py` (сырые словари в форме ответов VK, анонимизированные из Task 0).
- Роуты — `TestClient` с `FakeVk` (записывает вызовы, отдаёт фикстуры) и `FakeLlm`, по образцу `tests/web/test_sandbox.py`.
- Визуальная проверка — через scratch-обёртку с Basic Auth и эмуляцией телефона iframe'ами (см. память `web-admin-browser-testing`), после Task 6 и Task 12.

### Документация

CLAUDE.md/AGENTS.md: инвариант «в VK/LLM ходит только из песочницы и удаления ответа» становится неверным → обновить строку про `web/` (Task 13, по правилу 1). README — раздел про мессенджер.

---
## Tasks

### Task 0: Спайк — формы ответов VK и загрузка голосового

Одноразовый скрипт против живого VK (токен из `.env`, чат «test» из списка диалогов). Результат — знание, а не код: подтверждённые формы ответов и рабочая строка вложения. Скрипт лежит в scratchpad, в репозиторий попадают только анонимизированные фикстуры.

**Files:**
- Create: `tests/web/im_fixtures.py` (сырые ответы VK с заменёнными id/именами/URL)
- Scratch: `<scratchpad>/vk_spike.py`

**Interfaces:**
- Produces: `CONVERSATIONS`, `HISTORY`, `MEMBERS`, `SENT`, `UPLOADED_VOICE` — словари в форме ответов VK; их используют тесты Task 2–10.

- [ ] **Step 1: Скрипт спайка**

```python
# <scratchpad>/vk_spike.py — throwaway
import io, json, sys
from bot.config import Settings
from bot.vk import VkClient
import vk_api

s = Settings()
vk = VkClient(s.vk_token)
api = vk.api
F = "photo_50,photo_100,online,sex,screen_name"
conv = api.messages.getConversations(count=5, extended=1, fields=F)
print(json.dumps(conv, ensure_ascii=False)[:3000])
test_peer = next(i["conversation"]["peer"]["id"] for i in conv["items"]
                 if (i["conversation"].get("chat_settings") or {}).get("title") == "test")
hist = api.messages.getHistory(peer_id=test_peer, count=5, extended=1, fields=F)
print(json.dumps(hist, ensure_ascii=False)[:3000])
oldest = hist["items"][-1]["id"]
older = api.messages.getHistory(peer_id=test_peer, count=3, start_message_id=oldest, offset=1, extended=1)
print("older ids:", [m["id"] for m in older["items"]], "oldest was", oldest)
print(json.dumps(api.messages.getConversationMembers(peer_id=test_peer, fields=F), ensure_ascii=False)[:1500])
upload = vk_api.VkUpload(vk._session)
for path in sys.argv[1:]:                       # python vk_spike.py sample.ogg sample.mp3
    buf = io.BytesIO(open(path, "rb").read()); buf.name = "voice." + path.rsplit(".", 1)[-1]
    saved = upload.audio_message(buf, peer_id=test_peer)
    print("saved:", json.dumps(saved, ensure_ascii=False))
    a = saved["audio_message"]
    att = f"audio_message{a['owner_id']}_{a['id']}_{a.get('access_key', '')}".rstrip("_")
    mid = api.messages.send(peer_id=test_peer, random_id=0, attachment=att, message=f"спайк {path}")
    print("sent", mid, json.dumps(api.messages.getById(message_ids=mid, extended=1)["items"][0], ensure_ascii=False)[:800])
```

- [ ] **Step 2: Запустить**

Run: `PYTHONPATH=. .venv/bin/python <scratchpad>/vk_spike.py <scratchpad>/sample.ogg <scratchpad>/sample.mp3`
(тестовые файлы: любой короткий `.ogg` Opus и `.mp3`, например записанные QuickTime и сконвертированные `ffmpeg -i in.m4a -c:a libopus out.ogg`)

Проверить и записать в notepad `.omc/notepad.md`:
1. `older ids` все меньше `oldest` — семантика `start_message_id + offset=1` верна (иначе поправить `history_page` в Task 1).
2. `.ogg` дошёл до чата как голосовое (в VK видно плеер, а не документ). `.mp3` в проде всё равно конвертируется в ogg (Task 9); если VK принял и сырой `.mp3` — просто отметить это в notepad, дизайн не меняется.
3. Где в ответе `getConversations` лежат `unread_count`, `sort_id.major_id` (закреп), `push_settings.disabled_forever` (без звука), `chat_settings.photo.photo_50`.
4. Вид `attachments[].audio_message` у отправленного сообщения (`link_mp3`, `duration`, `transcript_state`).

- [ ] **Step 3: Фикстуры**

Собрать `tests/web/im_fixtures.py` из полученных ответов, заменив реальные id на `11`, `22`, `2000000001`, имена — на «Вася Пупкин», «Аня Иванова», URL — на `https://cdn.example/…`, тексты — на нейтральные. Минимальный состав, на который рассчитаны тесты ниже:

```python
ME = 1
PEER_USER = 22
PEER_CHAT = 2000000001

CONVERSATIONS = {
    "count": 2, "unread_count": 1,
    "items": [
        {"conversation": {"peer": {"id": PEER_CHAT, "type": "chat", "local_id": 1},
                          "in_read": 500, "out_read": 501, "last_message_id": 502, "unread_count": 2,
                          "sort_id": {"major_id": 1, "minor_id": 502},
                          "push_settings": {"disabled_forever": True},
                          "chat_settings": {"title": "лампочки", "members_count": 23,
                                            "photo": {"photo_50": "https://cdn.example/chat50.jpg"}}},
         "last_message": {"id": 502, "date": 1788876240, "peer_id": PEER_CHAT, "from_id": 11, "out": 0,
                          "text": "", "attachments": [{"type": "sticker", "sticker": {
                              "images": [{"url": "https://cdn.example/st64.png", "width": 64, "height": 64},
                                         {"url": "https://cdn.example/st256.png", "width": 256, "height": 256}]}}]}},
        {"conversation": {"peer": {"id": PEER_USER, "type": "user", "local_id": PEER_USER},
                          "in_read": 300, "out_read": 299, "last_message_id": 300,
                          "sort_id": {"major_id": 0, "minor_id": 300}},
         "last_message": {"id": 300, "date": 1788872640, "peer_id": PEER_USER, "from_id": ME, "out": 1,
                          "text": "Ну вот доедешь - напиши", "attachments": []}},
    ],
    "profiles": [
        {"id": 11, "first_name": "Вася", "last_name": "Пупкин", "photo_50": "https://cdn.example/u11.jpg", "online": 1},
        {"id": 22, "first_name": "Аня", "last_name": "Иванова", "photo_50": "https://cdn.example/u22.jpg", "online": 0},
        {"id": ME, "first_name": "Валентина", "last_name": "Тина", "photo_50": "https://cdn.example/me.jpg", "online": 1},
    ],
    "groups": [],
}

HISTORY = {
    "count": 4,
    "items": [
        {"id": 502, "date": 1788876240, "peer_id": PEER_CHAT, "from_id": 11, "out": 0, "text": "",
         "attachments": [{"type": "sticker", "sticker": {"images": [
             {"url": "https://cdn.example/st256.png", "width": 256, "height": 256}]}}]},
        {"id": 501, "date": 1788876180, "peer_id": PEER_CHAT, "from_id": ME, "out": 1, "text": "ну все тогда",
         "attachments": []},
        {"id": 500, "date": 1788876120, "peer_id": PEER_CHAT, "from_id": 11, "out": 0, "text": "после смены выкину.",
         "attachments": [{"type": "audio_message", "audio_message": {
             "id": 7, "owner_id": 11, "duration": 20, "waveform": [1, 5, 9], "access_key": "k",
             "link_ogg": "https://cdn.example/v.ogg", "link_mp3": "https://cdn.example/v.mp3",
             "transcript": "после смены выкину", "transcript_state": "done"}}],
         "reply_message": {"from_id": ME, "text": "выкидывай тогда"}},
        {"id": 499, "date": 1788739980, "peer_id": PEER_CHAT, "from_id": 11, "out": 0, "text": "",
         "attachments": [], "action": {"type": "chat_invite_user", "member_id": 22}},
    ],
    "profiles": CONVERSATIONS["profiles"],
    "groups": [],
    "conversations": [CONVERSATIONS["items"][0]["conversation"]],
}

MEMBERS = {
    "count": 3,
    "items": [{"member_id": ME, "is_owner": True}, {"member_id": 11, "is_admin": True}, {"member_id": 22}],
    "profiles": CONVERSATIONS["profiles"],
    "groups": [],
}

SENT = {"items": [{"id": 503, "date": 1788876300, "peer_id": PEER_CHAT, "from_id": ME, "out": 1,
                   "text": "привет из админки", "attachments": []}],
        "profiles": CONVERSATIONS["profiles"], "groups": []}

UPLOADED_VOICE = {"type": "audio_message",
                  "audio_message": {"id": 8, "owner_id": ME, "access_key": "abc", "duration": 3,
                                    "link_mp3": "https://cdn.example/out.mp3"}}
```

- [ ] **Step 4: Commit**

```bash
git add tests/web/im_fixtures.py
git commit -m "add VK response fixtures for the messenger"
```

---

### Task 1: `VkClient` — методы мессенджера

**Files:**
- Modify: `bot/vk.py`
- Test: `tests/test_vk.py` (новый; только чистая функция `voice_attachment`)

**Interfaces:**
- Produces:
  - `VkClient.conversations(count: int = 60, offset: int = 0) -> dict`
  - `VkClient.conversation(peer_id: int) -> dict` (`getConversationsById`)
  - `VkClient.history_page(peer_id: int, count: int, before_id: int | None = None) -> dict`
  - `VkClient.members(peer_id: int) -> dict`
  - `VkClient.messages_by_id(ids: list[int]) -> dict`
  - `VkClient.send(peer_id: int, text: str = "", reply_to: int | None = None, attachment: str = "") -> int`
  - `VkClient.mark_read(peer_id: int) -> None`
  - `VkClient.upload_voice(peer_id: int, data: bytes, ext: str) -> str` (строка вложения)
  - `voice_attachment(saved: dict) -> str`

- [ ] **Step 1: Тест на `voice_attachment`**

```python
# tests/test_vk.py
from bot.vk import voice_attachment


def test_voice_attachment_includes_access_key():
    saved = {"type": "audio_message", "audio_message": {"id": 8, "owner_id": 1, "access_key": "abc"}}
    assert voice_attachment(saved) == "audio_message1_8_abc"


def test_voice_attachment_without_key():
    assert voice_attachment({"audio_message": {"id": 8, "owner_id": -5}}) == "audio_message-5_8"
```

- [ ] **Step 2: Убедиться, что падает**

Run: `.venv/bin/pytest tests/test_vk.py -v`
Expected: `ImportError: cannot import name 'voice_attachment'`

- [ ] **Step 3: Реализация**

В `bot/vk.py` добавить импорты и методы (существующие методы не трогать — их зовёт бот):

```python
import io

import vk_api
from vk_api import VkUpload
from vk_api.longpoll import VkEventType, VkLongPoll
from vk_api.utils import get_random_id

PROFILE_FIELDS = "photo_50,photo_100,online,sex,screen_name"


def voice_attachment(saved: dict) -> str:
    doc = saved["audio_message"]
    key = doc.get("access_key")
    return f"audio_message{doc['owner_id']}_{doc['id']}" + (f"_{key}" if key else "")


class VkClient:
    def __init__(self, token: str):
        self._session = vk_api.VkApi(token=token)
        self.api = self._session.get_api()
        self._upload = VkUpload(self._session)
        ...  # как было

    def conversations(self, count: int = 60, offset: int = 0) -> dict:
        return self.api.messages.getConversations(count=count, offset=offset, extended=1, fields=PROFILE_FIELDS)

    def conversation(self, peer_id: int) -> dict:
        return self.api.messages.getConversationsById(peer_ids=peer_id, extended=1, fields=PROFILE_FIELDS)

    def history_page(self, peer_id: int, count: int, before_id: int | None = None) -> dict:
        params = dict(peer_id=peer_id, count=count, extended=1, fields=PROFILE_FIELDS)
        if before_id is not None:
            # offset считается от start_message_id: 1 — со следующего более старого сообщения
            params.update(start_message_id=before_id, offset=1)
        return self.api.messages.getHistory(**params)

    def members(self, peer_id: int) -> dict:
        return self.api.messages.getConversationMembers(peer_id=peer_id, fields=PROFILE_FIELDS)

    def messages_by_id(self, ids: list[int]) -> dict:
        return self.api.messages.getById(message_ids=",".join(map(str, ids)), extended=1, fields=PROFILE_FIELDS)

    def send(self, peer_id: int, text: str = "", reply_to: int | None = None, attachment: str = "") -> int:
        params = dict(peer_id=peer_id, random_id=get_random_id(), message=text)
        if reply_to:
            params["reply_to"] = reply_to
        if attachment:
            params["attachment"] = attachment
        return self.api.messages.send(**params)

    def mark_read(self, peer_id: int) -> None:
        self.api.messages.markAsRead(peer_id=peer_id, mark_conversation_as_read=1)

    def upload_voice(self, peer_id: int, data: bytes, ext: str) -> str:
        buf = io.BytesIO(data)
        # FilesOpener берёт расширение из name; без него VK получит file0.jpg и отклонит голосовое
        buf.name = f"voice.{ext}"
        return voice_attachment(self._upload.audio_message(buf, peer_id=peer_id))
```

- [ ] **Step 4: Тесты**

Run: `.venv/bin/pytest tests/test_vk.py tests/test_main.py -q`
Expected: PASS (тесты бота используют фейковый vk и не зависят от новых методов)

- [ ] **Step 5: Commit**

```bash
git add bot/vk.py tests/test_vk.py
git commit -m "add messenger methods to VkClient"
```

---
### Task 2: View-модели из ответов VK (`web/im/views.py`)

**Files:**
- Create: `web/im/__init__.py` (пустой), `web/im/views.py`
- Modify: `bot/config.py` (поле `web_timezone`)
- Test: `tests/web/test_im_views.py`

**Interfaces:**
- Consumes: фикстуры Task 0.
- Produces: датаклассы `Peer`, `Attachment`, `Quote`, `BotMark`, `Message`, `Row`, `Dialog`, класс `Profiles`; функции `parse_conversations(raw, me_id, marks=None) -> list[Dialog]`, `parse_history(raw, me_id, marks=None) -> tuple[list[Message], int]`, `attachment_of(att) -> Attachment`, `rows(messages, now, tz) -> list[Row]`, `preview(message) -> str`, `day_label(ts, now, tz) -> str`, `is_chat(peer_id) -> bool`.

- [ ] **Step 1: Тесты**

```python
# tests/web/test_im_views.py
from datetime import datetime
from zoneinfo import ZoneInfo

from tests.web.im_fixtures import HISTORY, CONVERSATIONS, ME, PEER_CHAT, PEER_USER
from web.im.views import (BotMark, Message, attachment_of, day_label, parse_conversations,
                          parse_history, preview, rows)

TZ = ZoneInfo("Europe/Moscow")


def test_parse_conversations_builds_dialogs_in_order():
    chat, user = parse_conversations(CONVERSATIONS, ME)
    assert chat.peer.id == PEER_CHAT and chat.peer.kind == "chat" and chat.peer.title == "лампочки"
    assert chat.peer.members == 23 and chat.peer.photo == "https://cdn.example/chat50.jpg"
    assert chat.unread == 2 and chat.muted and chat.pinned
    assert chat.last.author == "Вася Пупкин" and preview(chat.last) == "Стикер"
    assert user.peer.kind == "user" and user.peer.title == "Аня Иванова" and not user.peer.online
    assert user.unread == 0 and not user.muted and not user.pinned
    assert user.last.out and not user.last.read          # out_read=299 < id 300


def test_parse_history_is_chronological_with_read_marks_and_attachments():
    messages, out_read = parse_history(HISTORY, ME)
    assert out_read == 501
    assert [m.id for m in messages] == [499, 500, 501, 502]
    voice = messages[1]
    assert voice.attachments[0].kind == "voice" and voice.attachments[0].duration == 20
    assert voice.attachments[0].transcript == "после смены выкину"
    assert voice.attachments[0].url == "https://cdn.example/v.mp3"
    assert voice.reply.author == "Валентина Тина" and voice.reply.text == "выкидывай тогда"
    own = messages[2]
    assert own.out and own.read
    assert messages[0].action == "Вася Пупкин пригласил(а) Аня Иванова"
    assert messages[3].attachments[0].kind == "sticker"
    assert messages[3].attachments[0].url == "https://cdn.example/st256.png"


def test_bot_marks_attach_to_own_messages():
    messages, _ = parse_history(HISTORY, ME, marks={501: BotMark("rina", "grok-4.6")})
    assert messages[2].bot == BotMark("rina", "grok-4.6") and messages[1].bot is None


def test_attachment_of_picks_largest_photo_and_medium_preview():
    att = attachment_of({"type": "photo", "photo": {"sizes": [
        {"type": "s", "url": "s", "width": 75}, {"type": "x", "url": "x", "width": 604},
        {"type": "w", "url": "w", "width": 2560}]}})
    assert att.kind == "photo" and att.url == "w" and att.preview == "x"


def test_attachment_of_unknown_type_is_labelled():
    assert attachment_of({"type": "market", "market": {}}).kind == "other"
    assert attachment_of({"type": "wall", "wall": {}}).title == "репост"


def test_preview_prefers_text_then_attachment_label():
    msg = Message(1, 0, 11, "Вася", "", "привет", False, False)
    assert preview(msg) == "привет"
    voice = Message(1, 0, 11, "Вася", "", "", False, False,
                    attachments=(attachment_of(HISTORY["items"][2]["attachments"][0]),))
    assert preview(voice) == "Голосовое сообщение"


def test_day_label():
    now = datetime(2026, 9, 8, 18, 0, tzinfo=TZ).timestamp()
    assert day_label(now - 3600, now, TZ) == "сегодня"
    assert day_label(now - 86400, now, TZ) == "вчера"
    assert day_label(datetime(2026, 9, 1, 12, tzinfo=TZ).timestamp(), now, TZ) == "1 сентября"
    assert day_label(datetime(2025, 9, 1, 12, tzinfo=TZ).timestamp(), now, TZ) == "1 сентября 2025"


def test_rows_group_series_and_insert_day_chips():
    messages, _ = parse_history(HISTORY, ME)
    now = datetime(2026, 9, 8, 18, 0, tzinfo=TZ).timestamp()
    got = rows(messages, now, TZ)
    assert got[0].day == "вчера" and got[0].head
    assert got[1].day == "сегодня" and got[1].head          # новый день — заголовок серии
    assert got[2].head                                       # другой автор
    assert got[3].head                                       # снова Вася после Вали
```

- [ ] **Step 2: Убедиться, что падает**

Run: `.venv/bin/pytest tests/web/test_im_views.py -q`
Expected: `ModuleNotFoundError: No module named 'web.im'`

- [ ] **Step 3: Реализация**

В `bot/config.py` в `Settings` добавить `web_timezone: str = "Europe/Moscow"`.

```python
# web/im/views.py
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bot.context import ATTACHMENT_LABELS

GROUP_CHAT_PEER_BASE = 2_000_000_000
SERIES_GAP = 300.0
MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
          "сентября", "октября", "ноября", "декабря")
PREVIEW_LABELS = {"photo": "Фотография", "sticker": "Стикер", "voice": "Голосовое сообщение",
                  "doc": "Документ", "video": "Видео", "audio": "Аудиозапись", "link": "Ссылка",
                  "wall": "Запись на стене", "other": "Вложение"}


def is_chat(peer_id: int) -> bool:
    return peer_id >= GROUP_CHAT_PEER_BASE


@dataclass(frozen=True)
class Peer:
    id: int
    title: str
    photo: str = ""
    kind: str = "user"
    online: bool = False
    members: int = 0


@dataclass(frozen=True)
class Attachment:
    kind: str
    url: str = ""
    preview: str = ""
    title: str = ""
    duration: int = 0
    transcript: str = ""


@dataclass(frozen=True)
class Quote:
    author: str
    text: str


@dataclass(frozen=True)
class BotMark:
    persona: str
    model: str


@dataclass(frozen=True)
class Message:
    id: int
    ts: float
    from_id: int
    author: str
    photo: str
    text: str
    out: bool
    read: bool
    attachments: tuple[Attachment, ...] = ()
    reply: Quote | None = None
    fwd_count: int = 0
    action: str = ""
    bot: BotMark | None = None


@dataclass(frozen=True)
class Row:
    message: Message
    day: str | None
    head: bool


@dataclass(frozen=True)
class Dialog:
    peer: Peer
    last: Message | None
    unread: int
    muted: bool
    pinned: bool


class Profiles:
    def __init__(self, raw: dict):
        self._users = {p["id"]: p for p in raw.get("profiles") or []}
        self._groups = {-g["id"]: g for g in raw.get("groups") or []}

    def name(self, uid: int) -> str:
        if uid in self._users:
            p = self._users[uid]
            return f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
        if uid in self._groups:
            return self._groups[uid].get("name", f"club{-uid}")
        return f"id{uid}"

    def photo(self, uid: int) -> str:
        return (self._users.get(uid) or self._groups.get(uid) or {}).get("photo_50", "")

    def online(self, uid: int) -> bool:
        return bool((self._users.get(uid) or {}).get("online"))


def attachment_of(att: dict) -> Attachment:
    kind = att.get("type", "")
    body = att.get(kind) or {}
    if kind == "photo":
        sizes = sorted(body.get("sizes") or [], key=lambda s: s.get("width", 0))
        if not sizes:
            return Attachment("photo")
        medium = next((s for s in sizes if s.get("width", 0) >= 600), sizes[-1])
        return Attachment("photo", url=sizes[-1]["url"], preview=medium["url"])
    if kind == "sticker":
        images = body.get("images") or []
        chosen = next((i for i in images if i.get("width") == 256), images[-1] if images else {})
        return Attachment("sticker", url=chosen.get("url", ""))
    if kind == "audio_message":
        done = body.get("transcript_state") == "done"
        return Attachment("voice", url=body.get("link_mp3") or body.get("link_ogg", ""),
                          duration=int(body.get("duration", 0)),
                          transcript=body.get("transcript", "") if done else "")
    if kind == "doc":
        return Attachment("doc", url=body.get("url", ""), title=body.get("title") or "документ")
    if kind == "video":
        images = body.get("image") or []
        return Attachment("video", preview=images[-1]["url"] if images else "", title=body.get("title") or "видео")
    if kind == "audio":
        return Attachment("audio", title=" — ".join(x for x in (body.get("artist"), body.get("title")) if x))
    if kind == "link":
        return Attachment("link", url=body.get("url", ""), title=body.get("title") or body.get("url", ""))
    if kind == "wall":
        return Attachment("wall", title="репост")
    return Attachment("other", title=ATTACHMENT_LABELS.get(kind, "[вложение]").strip("[]"))


def action_text(action: dict | None, profiles: Profiles, from_id: int) -> str:
    if not action:
        return ""
    who = profiles.name(from_id)
    member = profiles.name(action["member_id"]) if action.get("member_id") else ""
    kind = action.get("type", "")
    if kind == "chat_invite_user":
        return f"{who} пригласил(а) {member}" if action.get("member_id") != from_id else f"{who} вернулся(ась) в беседу"
    if kind == "chat_invite_user_by_link":
        return f"{who} вошёл(ла) по ссылке"
    if kind == "chat_kick_user":
        return f"{who} исключил(а) {member}" if action.get("member_id") != from_id else f"{who} вышел(ла) из беседы"
    if kind == "chat_title_update":
        return f"{who} изменил(а) название: {action.get('text', '')}"
    if kind == "chat_pin_message":
        return f"{who} закрепил(а) сообщение"
    return f"{who}: {kind}"


def message_of(msg: dict, profiles: Profiles, me_id: int, out_read: int, marks: dict) -> Message:
    from_id = msg["from_id"]
    out = from_id == me_id
    reply = msg.get("reply_message")
    return Message(
        id=msg["id"], ts=float(msg["date"]), from_id=from_id,
        author=profiles.name(from_id), photo=profiles.photo(from_id),
        text=msg.get("text") or "", out=out, read=out and msg["id"] <= out_read,
        attachments=tuple(attachment_of(a) for a in msg.get("attachments") or []),
        reply=Quote(profiles.name(reply["from_id"]), reply.get("text") or preview_label(reply)) if reply else None,
        fwd_count=len(msg.get("fwd_messages") or []),
        action=action_text(msg.get("action"), profiles, from_id),
        bot=marks.get(msg["id"]),
    )


def preview_label(raw_message: dict) -> str:
    atts = raw_message.get("attachments") or []
    if atts:
        return PREVIEW_LABELS.get(attachment_of(atts[0]).kind, "Вложение")
    return "Пересланные сообщения" if raw_message.get("fwd_messages") else ""


def preview(message: Message) -> str:
    if message.action:
        return message.action
    if message.text:
        return message.text
    if message.attachments:
        return PREVIEW_LABELS.get(message.attachments[0].kind, "Вложение")
    return "Пересланные сообщения" if message.fwd_count else ""


def peer_of(conv: dict, profiles: Profiles) -> Peer:
    peer = conv["peer"]
    pid = peer["id"]
    if peer.get("type") == "chat":
        cs = conv.get("chat_settings") or {}
        return Peer(pid, cs.get("title") or f"беседа {peer.get('local_id', pid)}",
                    (cs.get("photo") or {}).get("photo_50", ""), "chat", False, int(cs.get("members_count", 0)))
    return Peer(pid, profiles.name(pid), profiles.photo(pid), "group" if pid < 0 else "user", profiles.online(pid))


def parse_conversations(raw: dict, me_id: int, marks: dict | None = None) -> list[Dialog]:
    profiles = Profiles(raw)
    dialogs = []
    for item in raw.get("items") or []:
        conv = item["conversation"]
        last = item.get("last_message")
        dialogs.append(Dialog(
            peer=peer_of(conv, profiles),
            last=message_of(last, profiles, me_id, int(conv.get("out_read", 0)), marks or {}) if last else None,
            unread=int(conv.get("unread_count", 0)),
            muted=bool((conv.get("push_settings") or {}).get("disabled_forever")),
            pinned=bool((conv.get("sort_id") or {}).get("major_id")),
        ))
    return dialogs


def parse_history(raw: dict, me_id: int, marks: dict | None = None) -> tuple[list[Message], int]:
    profiles = Profiles(raw)
    convs = raw.get("conversations") or []
    out_read = int(convs[0].get("out_read", 0)) if convs else 0
    messages = [message_of(m, profiles, me_id, out_read, marks or {}) for m in raw.get("items") or []]
    return list(reversed(messages)), out_read


def day_label(ts: float, now: float, tz: ZoneInfo) -> str:
    day = datetime.fromtimestamp(ts, tz).date()
    today = datetime.fromtimestamp(now, tz).date()
    if day == today:
        return "сегодня"
    if day == today - timedelta(days=1):
        return "вчера"
    label = f"{day.day} {MONTHS[day.month - 1]}"
    return label if day.year == today.year else f"{label} {day.year}"


def rows(messages: list[Message], now: float, tz: ZoneInfo) -> list[Row]:
    result: list[Row] = []
    prev: Message | None = None
    prev_day = None
    for m in messages:
        day = day_label(m.ts, now, tz)
        new_day = day != prev_day
        head = new_day or prev is None or prev.from_id != m.from_id or m.ts - prev.ts > SERIES_GAP or bool(prev.action)
        result.append(Row(m, day if new_day else None, head or bool(m.action)))
        prev, prev_day = m, day
    return result
```

- [ ] **Step 4: Тесты**

Run: `.venv/bin/pytest tests/web/test_im_views.py -q`
Expected: PASS (если `test_rows_group_series…` расходится по `head` на границе серий — сверить с фикстурой: 499 → 500 меняется день, 500 → 501 другой автор, 501 → 502 другой автор)

- [ ] **Step 5: Commit**

```bash
git add web/im/__init__.py web/im/views.py bot/config.py tests/web/test_im_views.py
git commit -m "add messenger view models built from VK responses"
```

---

### Task 3: Метки «ответ бота» — все id разбитого ответа в `replies.jsonl`

Сейчас `ReplyRecord.reply_message_id` — только первая часть ответа, разбитого по `|||`; остальные части в ленте мессенджера остались бы без бейджа.

**Files:**
- Modify: `bot/status.py` (`ReplyRecord.reply_message_ids`), `bot/main.py` (запись `sent_ids`)
- Create: `web/im/marks.py`
- Test: `tests/test_status.py`, `tests/test_main.py`, `tests/web/test_im_marks.py`

**Interfaces:**
- Produces: `ReplyRecord.reply_message_ids: tuple[int, ...] = ()`; `bot_marks(records: list[ReplyRecord]) -> dict[int, BotMark]`.

- [ ] **Step 1: Тесты**

```python
# tests/test_status.py (добавить)
def test_reply_record_reads_old_lines_without_ids(tmp_path):
    p = tmp_path / "r.jsonl"
    p.write_text('{"ts": 1, "peer_id": 1, "from_id": 2, "message_id": 3, "reply_message_id": 4, '
                 '"reply": "r", "tag": null, "latency_s": 0.1, "persona": "v"}\n')
    rec = ReplyLog(str(p)).read()[0]
    assert rec.reply_message_ids == ()


def test_reply_record_keeps_all_part_ids(tmp_path):
    log = ReplyLog(str(tmp_path / "r.jsonl"))
    log.append(ReplyRecord(1, 1, 2, 3, 4, "a|||b", None, 0.1, "v", reply_message_ids=(4, 5)))
    assert tuple(log.read()[0].reply_message_ids) == (4, 5)
```

```python
# tests/web/test_im_marks.py
from bot.status import ReplyRecord
from web.im.marks import bot_marks
from web.services import model_label


def test_bot_marks_cover_every_part_and_fall_back_to_first_id():
    recs = [ReplyRecord(1, 1, 2, 3, 40, "a", None, 0.1, "rina", model="grok-4.6", reply_message_ids=(40, 41)),
            ReplyRecord(2, 1, 2, 3, 50, "b", None, 0.1, "", model="")]
    marks = bot_marks(recs)
    assert marks[40].persona == "rina" and marks[41].model == model_label("grok-4.6")
    assert marks[50].persona == "по умолчанию" and marks[50].model == ""
```

В `tests/test_main.py` найти тест, проверяющий запись в `deps.replies` после `respond` с разбивкой по `|||` (или добавить рядом с существующим тестом разбивки), и утвердить `rec.reply_message_ids == tuple(sent_ids)`.

- [ ] **Step 2: Убедиться, что падает**

Run: `.venv/bin/pytest tests/test_status.py tests/web/test_im_marks.py -q`
Expected: `TypeError: unexpected keyword argument 'reply_message_ids'`, `ModuleNotFoundError`

- [ ] **Step 3: Реализация**

`bot/status.py`: в `ReplyRecord` добавить последним полем `reply_message_ids: tuple[int, ...] = ()`.
`bot/main.py`, в `deps.replies.append(ReplyRecord(...))` добавить `reply_message_ids=tuple(sent_ids)`.

```python
# web/im/marks.py
from bot.status import ReplyRecord
from web.im.views import BotMark
from web.services import model_label


def bot_marks(records: list[ReplyRecord]) -> dict[int, BotMark]:
    marks = {}
    for r in records:
        mark = BotMark(r.persona or "по умолчанию", model_label(r.model) if r.model else "")
        for mid in tuple(r.reply_message_ids) or (r.reply_message_id,):
            marks[int(mid)] = mark
    return marks
```

- [ ] **Step 4: Тесты**

Run: `.venv/bin/pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bot/status.py bot/main.py web/im/marks.py tests/test_status.py tests/test_main.py tests/web/test_im_marks.py
git commit -m "log every message id of a split reply and map them to bot marks"
```

---
### Task 4: Режим бота для чата (`web/im/modes.py`)

**Files:**
- Create: `web/im/modes.py`
- Test: `tests/web/test_im_modes.py`

**Interfaces:**
- Consumes: `bot.access.AccessLists`, `bot.runtime.RuntimeSettings`, `web.im.views.is_chat`.
- Produces: `BotMode(label, kind, personas, reason)`, `bot_mode(peer_id, lists, rt) -> BotMode`, `ChatControls(...)`, `chat_controls(peer_id, lists, rt) -> ChatControls`.

- [ ] **Step 1: Тесты**

```python
# tests/web/test_im_modes.py
from bot.access import AccessLists
from bot.runtime import RuntimeSettings
from web.im.modes import bot_mode, chat_controls

CHAT, USER = 2000000001, 22


def test_private_dialog_modes():
    assert bot_mode(USER, AccessLists(), RuntimeSettings()).label == "по тегу"
    assert bot_mode(USER, AccessLists(auto_reply_users=frozenset({USER})), RuntimeSettings()).label == "авто"
    assert bot_mode(USER, AccessLists(blocked_users=frozenset({USER})), RuntimeSettings()).label == "блок"


def test_chat_modes_by_priority():
    lists = AccessLists(auto_reply_peers=frozenset({CHAT}), onboarding_peers=frozenset({CHAT}))
    assert bot_mode(CHAT, lists, RuntimeSettings()).label == "знакомство"
    assert bot_mode(CHAT, AccessLists(auto_reply_peers=frozenset({CHAT})), RuntimeSettings()).label == "авто"
    assert bot_mode(CHAT, lists, RuntimeSettings(paused_peers=frozenset({CHAT}))).label == "пауза"
    assert bot_mode(CHAT, lists, RuntimeSettings(paused=True)).label == "пауза"
    assert bot_mode(CHAT, AccessLists(allowed_peers=frozenset({7})), RuntimeSettings()).label == "вне белого списка"
    assert bot_mode(-100, AccessLists(), RuntimeSettings()).label == "молчит"


def test_personas_come_from_peer_override_or_active():
    rt = RuntimeSettings(active_persona="valentina", peer_personas=((CHAT, ("rina", "monika")),))
    assert bot_mode(CHAT, AccessLists(), rt).personas == ("rina", "monika")
    assert bot_mode(USER, AccessLists(), rt).personas == ("valentina",)


def test_chat_controls_reflect_lists():
    lists = AccessLists(auto_reply_peers=frozenset({CHAT}), peer_prompts={CHAT: "тут все свои"},
                        peer_blocked_users={CHAT: frozenset({11})})
    c = chat_controls(CHAT, lists, RuntimeSettings(paused_peers=frozenset({CHAT})))
    assert not c.private and c.auto and not c.onboarding and c.paused and c.prompt == "тут все свои"
    assert c.blocked_members == frozenset({11})
    u = chat_controls(USER, AccessLists(user_prompts={USER: "подруга"}), RuntimeSettings())
    assert u.private and u.prompt == "подруга" and not u.auto
```

- [ ] **Step 2: Убедиться, что падает**

Run: `.venv/bin/pytest tests/web/test_im_modes.py -q`
Expected: `ModuleNotFoundError: No module named 'web.im.modes'`

- [ ] **Step 3: Реализация**

```python
# web/im/modes.py
from dataclasses import dataclass

from bot.access import AccessLists
from bot.runtime import RuntimeSettings
from web.im.views import is_chat


@dataclass(frozen=True)
class BotMode:
    label: str
    kind: str
    personas: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class ChatControls:
    peer_id: int
    private: bool
    auto: bool
    onboarding: bool
    blocked: bool
    paused: bool
    personas: tuple[str, ...]
    prompt: str
    blocked_members: frozenset[int]


def personas_for(rt: RuntimeSettings, peer_id: int) -> tuple[str, ...]:
    override = dict(rt.peer_personas).get(peer_id)
    if override:
        return tuple(override)
    return (rt.active_persona,) if rt.active_persona else ()


def bot_mode(peer_id: int, lists: AccessLists, rt: RuntimeSettings) -> BotMode:
    personas = personas_for(rt, peer_id)
    if peer_id < 0:
        return BotMode("молчит", "muted", personas, "сообщества бот игнорирует всегда")
    if rt.paused:
        return BotMode("пауза", "muted", personas, "бот на паузе целиком")
    if peer_id in rt.paused_peers:
        return BotMode("пауза", "muted", personas, "чат на паузе (paused_peers)")
    if peer_id in lists.blocked_peers:
        return BotMode("блок", "bad", personas, "чат в blocked_peers")
    if not is_chat(peer_id) and peer_id in lists.blocked_users:
        return BotMode("блок", "bad", personas, "собеседник в blocked_users")
    if lists.allowed_peers and peer_id not in lists.allowed_peers:
        return BotMode("вне белого списка", "bad", personas, "allowed_peers задан, чата в нём нет")
    if not is_chat(peer_id):
        if peer_id in lists.auto_reply_users:
            return BotMode("авто", "ok", personas, "отвечает на каждое сообщение (auto_reply_users)")
        return BotMode("по тегу", "warn", personas, "отвечает только на упоминание")
    if peer_id in lists.onboarding_peers:
        return BotMode("знакомство", "ok", personas, "знакомится с новичками (onboarding_peers)")
    if peer_id in lists.auto_reply_peers:
        return BotMode("авто", "ok", personas, "отвечает всем без тега (auto_reply_peers)")
    return BotMode("по тегу", "warn", personas, "отвечает только на упоминание")


def chat_controls(peer_id: int, lists: AccessLists, rt: RuntimeSettings) -> ChatControls:
    private = not is_chat(peer_id)
    return ChatControls(
        peer_id=peer_id, private=private,
        auto=peer_id in (lists.auto_reply_users if private else lists.auto_reply_peers),
        onboarding=not private and peer_id in lists.onboarding_peers,
        blocked=peer_id in (lists.blocked_users if private else lists.blocked_peers),
        paused=peer_id in rt.paused_peers,
        personas=tuple(dict(rt.peer_personas).get(peer_id, ())),
        prompt=(lists.user_prompts if private else lists.peer_prompts).get(peer_id, ""),
        blocked_members=lists.peer_blocked_users.get(peer_id, frozenset()),
    )
```

- [ ] **Step 4: Тесты**

Run: `.venv/bin/pytest tests/web/test_im_modes.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/im/modes.py tests/web/test_im_modes.py
git commit -m "derive the bot mode of a chat from access lists and runtime"
```

---

### Task 5: Правки `access.json` / `runtime.json` из чата (`web/im/controls.py`)

**Files:**
- Create: `web/im/controls.py`
- Test: `tests/web/test_im_controls.py`

**Interfaces:**
- Consumes: `bot.config.parse_user_refs`.
- Produces: `set_member(data, field, ref_id, on, resolve=None) -> dict`, `set_keyed_text(data, field, ref_id, text, resolve=None) -> dict`, `set_peer_blocked(data, peer_id, user_id, on, resolve=None) -> dict`, `set_paused_peer(data, peer_id, on) -> dict`, `set_peer_personas(data, peer_id, slugs) -> dict`. Все возвращают новый словарь, исходный не меняют; `resolve(frozenset[str]) -> frozenset[int]` — `vk.resolve_screen_names`.

- [ ] **Step 1: Тесты**

```python
# tests/web/test_im_controls.py
from web.im.controls import (set_keyed_text, set_member, set_paused_peer, set_peer_blocked,
                             set_peer_personas)

resolve = lambda names: frozenset({22}) if "anya" in names else frozenset()


def test_set_member_adds_once_and_removes_every_spelling():
    data = {"auto_reply_users": ["@anya", 22, "@someone"]}
    off = set_member(data, "auto_reply_users", 22, False, resolve)
    assert off["auto_reply_users"] == ["@someone"]
    assert data["auto_reply_users"] == ["@anya", 22, "@someone"]      # исходник не тронут
    on = set_member(off, "auto_reply_users", 22, True, resolve)
    assert on["auto_reply_users"] == ["@someone", 22]
    assert set_member(on, "auto_reply_users", 22, True, resolve)["auto_reply_users"] == ["@someone", 22]


def test_set_member_on_peer_lists_needs_no_resolver():
    assert set_member({}, "auto_reply_peers", 2000000001, True)["auto_reply_peers"] == [2000000001]
    assert set_member({"blocked_peers": [7, 8]}, "blocked_peers", 7, False)["blocked_peers"] == [8]


def test_set_keyed_text_reuses_existing_nick_key_and_drops_empty():
    data = {"user_prompts": {"@anya": "старый", "@other": "x"}}
    upd = set_keyed_text(data, "user_prompts", 22, "новый ", resolve)
    assert upd["user_prompts"] == {"@anya": "новый", "@other": "x"}
    assert set_keyed_text(upd, "user_prompts", 22, "  ", resolve)["user_prompts"] == {"@other": "x"}
    assert set_keyed_text({}, "peer_prompts", 2000000001, "свои")["peer_prompts"] == {"2000000001": "свои"}


def test_set_peer_blocked():
    data = {"peer_blocked_users": {"2000000001": ["@anya", 11]}}
    off = set_peer_blocked(data, 2000000001, 22, False, resolve)
    assert off["peer_blocked_users"] == {"2000000001": [11]}
    assert set_peer_blocked(off, 2000000001, 11, False)["peer_blocked_users"] == {}
    assert set_peer_blocked({}, 5, 9, True)["peer_blocked_users"] == {"5": [9]}


def test_runtime_edits():
    assert set_paused_peer({"paused_peers": [1]}, 2, True)["paused_peers"] == [1, 2]
    assert set_paused_peer({"paused_peers": [1, 2]}, 1, False)["paused_peers"] == [2]
    rt = set_peer_personas({"peer_personas": {"5": "rina"}}, 6, ["rina", "monika"])
    assert rt["peer_personas"] == {"5": "rina", "6": ["rina", "monika"]}
    assert set_peer_personas(rt, 6, [])["peer_personas"] == {"5": "rina"}
    assert set_peer_personas(rt, 6, ["monika"])["peer_personas"]["6"] == "monika"
```

- [ ] **Step 2: Убедиться, что падает**

Run: `.venv/bin/pytest tests/web/test_im_controls.py -q`
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Реализация**

```python
# web/im/controls.py
from bot.config import parse_user_refs


def means_user(entry, user_id: int, resolve) -> bool:
    ids, names = parse_user_refs(str(entry))
    if user_id in ids:
        return True
    return bool(names) and resolve is not None and user_id in resolve(names)


def set_member(data: dict, field: str, ref_id: int, on: bool, resolve=None) -> dict:
    kept = [x for x in data.get(field) or [] if not means_user(x, ref_id, resolve)]
    if on:
        kept.append(ref_id)
    return {**data, field: kept}


def set_keyed_text(data: dict, field: str, ref_id: int, text: str, resolve=None) -> dict:
    prompts = dict(data.get(field) or {})
    key = next((k for k in prompts if means_user(k, ref_id, resolve)), str(ref_id))
    if text.strip():
        prompts[key] = text.strip()
    else:
        prompts.pop(key, None)
    return {**data, field: prompts}


def set_peer_blocked(data: dict, peer_id: int, user_id: int, on: bool, resolve=None) -> dict:
    table = dict(data.get("peer_blocked_users") or {})
    kept = [x for x in table.get(str(peer_id)) or [] if not means_user(x, user_id, resolve)]
    if on:
        kept.append(user_id)
    if kept:
        table[str(peer_id)] = kept
    else:
        table.pop(str(peer_id), None)
    return {**data, "peer_blocked_users": table}


def set_paused_peer(data: dict, peer_id: int, on: bool) -> dict:
    peers = [int(p) for p in data.get("paused_peers") or [] if int(p) != peer_id]
    if on:
        peers.append(peer_id)
    return {**data, "paused_peers": sorted(peers)}


def set_peer_personas(data: dict, peer_id: int, slugs: list[str]) -> dict:
    table = dict(data.get("peer_personas") or {})
    clean = list(dict.fromkeys(s.strip() for s in slugs if s.strip()))
    if not clean:
        table.pop(str(peer_id), None)
    else:
        table[str(peer_id)] = clean[0] if len(clean) == 1 else clean
    return {**data, "peer_personas": table}
```

- [ ] **Step 4: Тесты**

Run: `.venv/bin/pytest tests/web/test_im_controls.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/im/controls.py tests/web/test_im_controls.py
git commit -m "pure edits of access and runtime files for per-chat bot controls"
```

---
### Task 6: Страница `/im` — список диалогов и чат (только чтение)

Каркас мессенджера: роутер, шаблоны, стили, Alpine-компоненты, пункт навигации. Поллинг, отправка и панель бота — следующие задачи; здесь всё статично.

**Files:**
- Create: `web/im/routes.py`, `web/templates/im.html`, `web/templates/partials/im.html`, `web/templates/partials/im_dialogs.html`, `web/templates/partials/im_chat.html`, `web/templates/partials/im_rows.html`, `web/templates/partials/im_badge.html`, `web/static/im.css`, `web/static/im.js`
- Modify: `web/app.py` (подключить роутер, передать в `Renderer` фильтры), `web/templates/base.html` (блок `main_class`, пункт «Мессенджер», подключение `im.css`/`im.js`), `web/humanize.py` (фильтры `clock`, `mmss`)
- Test: `tests/web/test_im_pages.py`, `tests/web/test_humanize.py`

**Interfaces:**
- Consumes: Task 1 (`VkClient.conversations/history_page`), Task 2 (`parse_*`, `rows`), Task 3 (`bot_marks`), Task 4 (`bot_mode`).
- Produces: `create_router(settings, vk, llm, render, safe_error) -> APIRouter`; контекст `chat_ctx(peer_id, before=None, after=None)`; шаблонные фильтры `clock(ts)` → `16:44`, `mmss(seconds)` → `0:20`; CSS-классы `.im`, `.im-side`, `.im-main`, `.dlg`, `.msg`, `.badge-mode`.

- [ ] **Step 1: Тесты страниц**

```python
# tests/web/test_im_pages.py
import pytest
from fastapi.testclient import TestClient

from tests.web.conftest import AUTH
from tests.web.im_fixtures import CONVERSATIONS, HISTORY, MEMBERS, ME, PEER_CHAT, SENT, UPLOADED_VOICE
from web.app import create_app


class FakeVk:
    me_id = ME

    def __init__(self, token):
        self.calls = []

    def conversations(self, count=60, offset=0):
        self.calls.append(("conversations", count, offset))
        return CONVERSATIONS

    def history_page(self, peer_id, count, before_id=None):
        self.calls.append(("history", peer_id, count, before_id))
        return HISTORY

    def members(self, peer_id):
        return MEMBERS

    def messages_by_id(self, ids):
        self.calls.append(("by_id", tuple(ids)))
        return SENT

    def send(self, peer_id, text="", reply_to=None, attachment=""):
        self.calls.append(("send", peer_id, text, reply_to, attachment))
        return 503

    def mark_read(self, peer_id):
        self.calls.append(("read", peer_id))

    def delete_message(self, message_id):
        self.calls.append(("delete", message_id))

    def upload_voice(self, peer_id, data, ext):
        self.calls.append(("voice", peer_id, len(data), ext))
        return "audio_message1_8_abc"

    def resolve_name(self, uid):
        return "Вася Пупкин"

    def resolve_screen_names(self, names):
        return frozenset()

    def history(self, peer_id, count):
        return HISTORY["items"]


class FakeLlm:
    def __init__(self, settings):
        self.calls = []

    def reply(self, conversation, asker, **kw):
        self.calls.append((conversation, asker, kw))
        return "черновик от llm"


@pytest.fixture
def client(settings):
    open(f"{settings.personas_dir}/rina.md", "w").write("# Рина\nперсона")
    return TestClient(create_app(settings, vk_factory=FakeVk, llm_factory=FakeLlm), follow_redirects=False)


def test_im_page_lists_dialogs_with_modes(client):
    r = client.get("/im", auth=AUTH)
    assert r.status_code == 200
    assert "лампочки" in r.text and "Аня Иванова" in r.text
    assert "Стикер" in r.text                       # превью последнего сообщения
    assert 'class="unread">2<' in r.text
    assert r.text.count("по тегу") >= 2              # бейдж режима у каждого диалога
    assert 'href="/im"' in r.text and "Мессенджер" in r.text


def test_im_page_with_sel_renders_chat(client):
    r = client.get(f"/im?sel={PEER_CHAT}", auth=AUTH)
    assert r.status_code == 200
    assert "ну все тогда" in r.text and "после смены выкину." in r.text
    assert "23 участника" in r.text
    assert 'src="https://cdn.example/v.mp3"' in r.text and "0:20" in r.text
    assert "после смены выкину</" in r.text          # расшифровка голосового
    assert "пригласил(а) Аня Иванова" in r.text
    assert 'src="https://cdn.example/st256.png"' in r.text
    assert "выкидывай тогда" in r.text               # цитата ответа
    assert r.text.count('class="im-day"') == 2          # два разных дня в фикстуре


def test_chat_partial_for_htmx_pushes_url(client):
    r = client.get(f"/im/{PEER_CHAT}", auth=AUTH, headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert r.headers["HX-Push-Url"] == f"/im?sel={PEER_CHAT}"
    assert "<nav" not in r.text and 'id="messages"' in r.text


def test_chat_marks_bot_replies(client, settings):
    import os
    os.makedirs(settings.state_dir, exist_ok=True)
    with open(f"{settings.state_dir}/replies.jsonl", "w") as f:
        f.write('{"ts": 1, "peer_id": 2000000001, "from_id": 11, "message_id": 500, "reply_message_id": 501, '
                '"reply": "ну все тогда", "tag": null, "latency_s": 1.0, "persona": "rina", "model": "grok-4.6"}\n')
    r = client.get(f"/im?sel={PEER_CHAT}", auth=AUTH)
    assert "бот · rina" in r.text


def test_dialogs_partial(client):
    r = client.get("/im/dialogs", auth=AUTH, headers={"HX-Request": "true"})
    assert r.status_code == 200 and "<li" in r.text and "<nav" not in r.text
```

```python
# tests/web/test_humanize.py (добавить)
from web.humanize import clock, mmss


def test_clock_and_mmss():
    from zoneinfo import ZoneInfo
    assert clock(1788876240, ZoneInfo("Europe/Moscow")) == "17:04"
    assert mmss(20) == "0:20" and mmss(75) == "1:15"
```

- [ ] **Step 2: Убедиться, что падает**

Run: `.venv/bin/pytest tests/web/test_im_pages.py tests/web/test_humanize.py -q`
Expected: 404 на `/im`, `ImportError` на `clock`

- [ ] **Step 3: Фильтры времени**

```python
# web/humanize.py (добавить)
from datetime import datetime


def clock(ts: float, tz) -> str:
    return datetime.fromtimestamp(ts, tz).strftime("%H:%M")


def mmss(seconds: int) -> str:
    return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"
```

- [ ] **Step 4: Роутер**

```python
# web/im/routes.py
import time
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request

from bot.access import AccessFile
from bot.runtime import RuntimeFile, runtime_defaults
from bot.status import ReplyLog
from web.im.marks import bot_marks
from web.im.modes import bot_mode
from web.im.views import Profiles, parse_conversations, parse_history, peer_of, rows
from web.render import is_hx

DIALOGS = 60
PAGE = 40
POLL_WINDOW = 50


def create_router(settings, vk, llm, render, safe_error) -> APIRouter:
    router = APIRouter()
    tz = ZoneInfo(settings.web_timezone)
    # один WatchedFile на процесс: перечитывание и разрешение @ников только при смене mtime,
    # иначе каждый тик поллинга ходил бы в users.get
    access_file = AccessFile(settings.access_file, lambda names: vk().resolve_screen_names(names))
    runtime_file = RuntimeFile(settings.runtime_file, runtime_defaults(settings))

    def lists():
        return access_file.current()

    def runtime():
        return runtime_file.current()

    def marks():
        return bot_marks(ReplyLog(f"{settings.state_dir}/replies.jsonl").read())

    def dialogs_ctx():
        access, rt = lists(), runtime()
        dialogs = parse_conversations(vk().conversations(DIALOGS), vk().me_id, marks())
        return {"dialogs": [(d, bot_mode(d.peer.id, access, rt)) for d in dialogs], "tz": tz}

    def chat_ctx(peer_id: int, before: int | None = None, after: int | None = None):
        raw = vk().history_page(peer_id, POLL_WINDOW if after else PAGE, before_id=before)
        messages, out_read = parse_history(raw, vk().me_id, marks())
        if after:
            messages = [m for m in messages if m.id > after]
        convs = raw.get("conversations") or []
        peer = peer_of(convs[0], Profiles(raw)) if convs else None
        return {"peer": peer, "peer_id": peer_id, "rows": rows(messages, time.time(), tz),
                "out_read": out_read, "oldest": messages[0].id if messages else None,
                "newest": messages[-1].id if messages else (after or 0),
                "mode": bot_mode(peer_id, lists(), runtime()), "tz": tz, "page": "im"}

    def guard(call):
        try:
            return call()
        except Exception as e:
            raise HTTPException(502, f"VK: {safe_error(e)}")

    @router.get("/im")
    def im_page(request: Request, sel: int | None = None):
        ctx = {"page": "im", "sel": sel, **guard(dialogs_ctx)}
        if sel is not None:
            ctx["chat"] = guard(lambda: chat_ctx(sel))
        return render.page(request, "im", ctx)

    @router.get("/im/dialogs")
    def dialogs_partial(request: Request):
        return render.partial(request, "im_dialogs", {"page": "im", **guard(dialogs_ctx)})

    @router.get("/im/{peer_id}")
    def chat_partial(request: Request, peer_id: int):
        ctx = guard(lambda: chat_ctx(peer_id))
        if not is_hx(request):
            return render.page(request, "im", {"page": "im", "sel": peer_id, "chat": ctx, **guard(dialogs_ctx)})
        return render.partial(request, "im_chat", {"chat": ctx, "page": "im"}, push_url=f"/im?sel={peer_id}")

    return router
```

В `web/app.py`: `from web.im.routes import create_router`; после определения `vk`, `llm`, `safe_error` и `render` — `app.include_router(create_router(settings, vk, llm, render, safe_error))`. В `Renderer(...)` добавить фильтры `clock=clock, mmss=mmss` (импорт из `web.humanize`) и `preview=preview` (из `web.im.views`). Убедиться, что `/im/{peer_id}` объявлен после `/im/dialogs` (иначе `dialogs` попадёт в `int` и даст 422).

- [ ] **Step 5: Шаблоны**

`web/templates/base.html`: `<main class="{% block main_class %}container{% endblock %}">`; в список навигации первым пунктом `("/im", "Мессенджер", "im")`; после `app.css` — `<link rel="stylesheet" href="/static/im.css">`, после `app.js` — `<script src="/static/im.js"></script>`.

```html
{# web/templates/im.html #}
{% extends "base.html" %}{% block main_class %}im-shell{% endblock %}{% block body %}
{% include "partials/im.html" %}
{% endblock %}
```

```html
{# web/templates/partials/im.html #}
<div class="im" x-data="im({{ sel or 'null' }})" :class="{ 'show-chat': pane === 'chat' }">
  <aside class="im-side">
    <header class="im-side-head">
      <b>Мессенджер</b>
      <input type="search" placeholder="Поиск" x-model="filter" aria-label="Поиск по диалогам">
      <label class="im-unread-toggle"><input type="checkbox" role="switch" x-model="unreadOnly"> Только непрочитанные</label>
    </header>
    <div id="dialogs" class="im-dialogs">
      <ul id="dialog-list" hx-get="/im/dialogs" hx-trigger="every 10s [document.visibilityState === 'visible']"
          hx-target="#dialog-list" hx-swap="innerHTML">{% include "partials/im_dialogs.html" %}</ul>
    </div>
  </aside>
  <section id="chat" class="im-main">
    {% if chat %}{% include "partials/im_chat.html" %}{% else %}
    <div class="im-empty muted">Выберите диалог</div>{% endif %}
  </section>
</div>
```

```html
{# web/templates/partials/im_dialogs.html — только <li>, вставляется в #dialog-list #}
{% for d, mode in dialogs %}<li class="dlg" data-title="{{ d.peer.title|lower }}" data-unread="{{ d.unread }}"
    x-show="matches($el)" :class="{ active: sel === {{ d.peer.id }} }">
  <a hx-get="/im/{{ d.peer.id }}" hx-target="#chat" hx-swap="innerHTML" href="/im?sel={{ d.peer.id }}" @click="open({{ d.peer.id }})">
    <span class="ava">{% if d.peer.photo %}<img src="{{ d.peer.photo }}" alt="">{% else %}<i>{{ d.peer.title[:1] }}</i>{% endif %}
      {% if d.peer.online %}<b class="dot"></b>{% endif %}</span>
    <span class="body">
      <span class="line"><span class="title">{{ d.peer.title }}</span>
        {% if d.muted %}<svg class="ico" viewBox="0 0 24 24"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3l3-3-1.4-1.4-3 3-3-3L10.7 9l3 3-3 3 1.4 1.4 3-3 3 3 1.4-1.4-3-3z"/></svg>{% endif %}
        {% with m = mode %}{% include "partials/im_badge.html" %}{% endwith %}
        <time class="muted">{% if d.last %}{{ d.last.ts|clock(tz) }}{% endif %}</time></span>
      <span class="line"><span class="preview muted">{% if d.last %}{% if d.last.out %}Вы{% else %}{{ d.last.author.split(' ')[0] }}{% endif %}: {{ d.last|preview }}{% endif %}</span>
        {% if d.unread %}<span class="unread">{{ d.unread }}</span>{% elif d.last and d.last.out %}<span class="ticks {{ 'read' if d.last.read }}">✓{{ '✓' if d.last.read }}</span>{% endif %}
        {% if d.pinned %}<svg class="ico" viewBox="0 0 24 24"><path d="M16 12V4h1V2H7v2h1v8l-2 2v2h5v6h2v-6h5v-2l-2-2z"/></svg>{% endif %}</span>
    </span>
  </a>
</li>{% endfor %}
```

```html
{# web/templates/partials/im_badge.html — ожидает m: BotMode #}
<span class="badge-mode {{ m.kind }}" title="{{ m.reason }}">{{ m.label }}</span>
```

```html
{# web/templates/partials/im_chat.html — ожидает chat: dict из chat_ctx #}
{% set c = chat %}
<div class="im-chat" x-data="chat({{ c.peer_id }}, {{ c.out_read }})">
  <header class="im-chat-head">
    <button type="button" class="back" @click="$dispatch('im-back')" aria-label="Назад">‹</button>
    <span class="ava">{% if c.peer and c.peer.photo %}<img src="{{ c.peer.photo }}" alt="">{% endif %}</span>
    <span class="body">
      <b>{{ c.peer.title if c.peer else c.peer_id|peer_label }}</b>
      <small class="muted">{% if c.peer and c.peer.kind == 'chat' %}{{ c.peer.members }} участника{% elif c.peer %}{{ 'онлайн' if c.peer.online else 'не в сети' }}{% endif %}</small>
    </span>
    <span id="chat-badge">{% with m = c.mode %}{% include "partials/im_badge.html" %}{% endwith %}</span>
    <a class="muted" href="{{ c.peer_id|peer_link }}" title="Открыть в VK" target="_blank" rel="noopener">VK</a>
  </header>
  <div id="messages" class="im-messages" x-ref="list">
    {% if c.oldest %}<div class="im-more" hx-get="/im/{{ c.peer_id }}/messages?before={{ c.oldest }}" hx-trigger="intersect once delay:500ms" hx-swap="outerHTML"></div>{% endif %}
    {% include "partials/im_rows.html" %}
  </div>
  <div id="chat-state" data-out-read="{{ c.out_read }}" hidden></div>
</div>
```

```html
{# web/templates/partials/im_rows.html — ожидает rows, tz #}
{% for r in rows %}{% set m = r.message %}
{% if r.day %}<div class="im-day"><span>{{ r.day }}</span></div>{% endif %}
{% if m.action %}<div class="im-action muted" data-id="{{ m.id }}">{{ m.action }}</div>{% else %}
<article class="msg {{ 'head' if r.head }} {{ 'out' if m.out }}" data-id="{{ m.id }}" data-from="{{ m.from_id }}">
  <span class="ava">{% if r.head %}{% if m.photo %}<img src="{{ m.photo }}" alt="">{% else %}<i>{{ m.author[:1] }}</i>{% endif %}{% endif %}</span>
  <div class="body">
    {% if r.head %}<div class="name"><a href="https://vk.com/id{{ m.from_id }}">{{ m.author }}</a>
      {% if m.bot %}<span class="badge">бот · {{ m.bot.persona }}{% if m.bot.model %} · {{ m.bot.model }}{% endif %}</span>{% endif %}</div>
    {% elif m.bot %}<div class="name"><span class="badge">бот · {{ m.bot.persona }}</span></div>{% endif %}
    {% if m.reply %}<blockquote class="quote"><b>{{ m.reply.author }}</b><span>{{ m.reply.text }}</span></blockquote>{% endif %}
    {% if m.text %}<p class="text">{{ m.text }}</p>{% endif %}
    {% for a in m.attachments %}
      {% if a.kind == 'photo' %}<a href="{{ a.url }}" target="_blank" rel="noopener"><img class="photo" src="{{ a.preview }}" alt="фото" loading="lazy"></a>
      {% elif a.kind == 'sticker' %}<img class="sticker" src="{{ a.url }}" alt="стикер" loading="lazy">
      {% elif a.kind == 'voice' %}<div class="voice"><audio controls preload="none" src="{{ a.url }}"></audio><span class="muted">{{ a.duration|mmss }}</span>
        {% if a.transcript %}<p class="transcript muted">{{ a.transcript }}</p>{% endif %}</div>
      {% elif a.kind == 'video' %}<div class="video">{% if a.preview %}<img src="{{ a.preview }}" alt="" loading="lazy">{% endif %}<span>{{ a.title }}</span></div>
      {% elif a.kind in ('doc', 'link') %}<a class="doc" href="{{ a.url }}" target="_blank" rel="noopener">{{ a.title }}</a>
      {% else %}<span class="badge">{{ a.title }}</span>{% endif %}
    {% endfor %}
    {% if m.fwd_count %}<span class="muted">{{ m.fwd_count }} пересланных</span>{% endif %}
  </div>
  <span class="meta">{% if m.out %}<span class="ticks" :class="{ read: {{ m.id }} <= outRead }">✓<span x-show="{{ m.id }} <= outRead">✓</span></span>{% endif %}<time class="muted">{{ m.ts|clock(tz) }}</time></span>
</article>{% endif %}
{% endfor %}
```

- [ ] **Step 6: Стили и скрипт**

```css
/* web/static/im.css */
:root { --im-blue: #0077ff; --im-side: #f5f5f7; --im-line: #e2e3e5; --im-hover: #eef1f6; }
@media (prefers-color-scheme: dark) { :root { --im-side: #19191c; --im-line: #2c2d31; --im-hover: #26272b; } }
main.im-shell { max-width: none; padding: 0; height: calc(100vh - 57px); }
.im { display: grid; grid-template-columns: 340px 1fr; height: 100%; }
.im-side { border-right: 1px solid var(--im-line); display: flex; flex-direction: column; min-height: 0; }
.im-side-head { padding: 0.75rem 0.75rem 0.25rem; display: flex; flex-direction: column; gap: 0.5rem; }
.im-side-head input[type=search] { margin: 0; background: var(--im-side); border-color: transparent; border-radius: 10px; }
.im-unread-toggle { font-size: 0.85em; color: var(--pico-muted-color); display: flex; gap: 0.5rem; align-items: center; }
.im-dialogs { overflow-y: auto; flex: 1; }
#dialog-list { list-style: none; margin: 0; padding: 0; }
.dlg a { display: flex; gap: 0.7rem; padding: 0.55rem 0.75rem; text-decoration: none; color: inherit; border-radius: 10px; margin: 0 0.4rem; }
.dlg a:hover { background: var(--im-hover); }
.dlg.active a { background: var(--im-hover); }
.ava { position: relative; flex: 0 0 auto; width: 52px; height: 52px; border-radius: 50%; overflow: visible; background: var(--im-side); display: grid; place-items: center; }
.ava img { width: 100%; height: 100%; border-radius: 50%; object-fit: cover; }
.ava i { font-style: normal; font-weight: 600; color: var(--pico-muted-color); }
.ava .dot { position: absolute; right: 2px; bottom: 2px; width: 12px; height: 12px; border-radius: 50%; background: #4bb34b; border: 2px solid var(--pico-background-color); }
.dlg .body { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 0.15rem; }
.dlg .line { display: flex; align-items: center; gap: 0.35rem; min-width: 0; }
.dlg .title { font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.dlg time { margin-left: auto; font-size: 0.8em; }
.dlg .preview { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 0.92em; }
.unread { background: var(--im-blue); color: #fff; border-radius: 999px; min-width: 1.4em; padding: 0 0.45em; font-size: 0.8em; text-align: center; }
.ico { width: 14px; height: 14px; fill: var(--pico-muted-color); flex: 0 0 auto; }
.badge-mode { font-size: 0.7em; font-weight: 600; padding: 0.05rem 0.45rem; border-radius: 999px; background: var(--im-side); color: var(--pico-muted-color); white-space: nowrap; }
.badge-mode.ok { background: #e3f5e1; color: #2e7d32; }
.badge-mode.warn { background: var(--im-side); }
.badge-mode.bad { background: #fde7e7; color: #c62828; }
.badge-mode.muted { background: var(--im-side); color: var(--pico-muted-color); }

.im-main { display: flex; flex-direction: column; min-height: 0; min-width: 0; }
.im-empty { display: grid; place-items: center; height: 100%; }
.im-chat { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.im-chat-head { display: flex; align-items: center; gap: 0.7rem; padding: 0.5rem 1rem; border-bottom: 1px solid var(--im-line); }
.im-chat-head .ava { width: 36px; height: 36px; }
.im-chat-head .body { display: flex; flex-direction: column; line-height: 1.2; min-width: 0; }
.im-chat-head .back { display: none; margin: 0; padding: 0 0.5rem; width: auto; background: none; border: none; color: var(--im-blue); font-size: 1.6rem; }
.im-messages { flex: 1; overflow-y: auto; padding: 0.5rem 1rem; display: flex; flex-direction: column; gap: 0.15rem; }
.im-day { position: sticky; top: 0.25rem; text-align: center; margin: 0.5rem 0; z-index: 1; }
.im-day span { background: var(--pico-background-color); border: 1px solid var(--im-line); border-radius: 999px; padding: 0.15rem 0.8rem; font-size: 0.85em; }
.im-action { text-align: center; font-size: 0.85em; margin: 0.35rem 0; }
.msg { display: grid; grid-template-columns: 40px 1fr auto; gap: 0 0.6rem; padding: 0.15rem 0.35rem; border-radius: 8px; align-items: start; }
.msg.head { margin-top: 0.5rem; }
.msg:hover { background: var(--im-hover); }
.msg .ava { width: 40px; height: 40px; background: transparent; }
.msg .name { font-weight: 600; color: var(--im-blue); display: flex; gap: 0.5rem; align-items: baseline; }
.msg .name a { text-decoration: none; }
.msg .text { margin: 0; white-space: pre-wrap; word-break: break-word; }
.msg .meta { font-size: 0.8em; display: flex; gap: 0.3rem; align-items: center; padding-top: 0.2rem; }
.ticks { color: var(--im-blue); letter-spacing: -0.2em; }
.quote { margin: 0.2rem 0; padding: 0.1rem 0.6rem; border-left: 2px solid var(--im-blue); display: flex; flex-direction: column; font-size: 0.92em; }
.msg .photo { max-width: 320px; max-height: 320px; border-radius: 10px; display: block; margin: 0.25rem 0; }
.msg .sticker { width: 168px; height: 168px; display: block; }
.voice { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; margin: 0.25rem 0; }
.voice audio { height: 36px; max-width: 320px; }
.voice .transcript { flex-basis: 100%; margin: 0; font-size: 0.9em; }
.video { display: flex; gap: 0.5rem; align-items: center; }
.video img { width: 120px; border-radius: 8px; }

@media (max-width: 767px) {
  main.im-shell { height: calc(100dvh - 57px); }
  .im { grid-template-columns: 1fr; }
  .im-main { display: none; }
  .im.show-chat .im-side { display: none; }
  .im.show-chat .im-main { display: flex; }
  .im-chat-head .back { display: block; }
  .msg .photo { max-width: 100%; }
}
```

```js
// web/static/im.js
document.addEventListener("alpine:init", () => {
  Alpine.data("im", (sel) => ({
    sel, pane: sel ? "chat" : "list", filter: "", unreadOnly: false,
    init() {
      this.$el.addEventListener("im-back", () => { this.pane = "list"; });
    },
    open(id) { this.sel = id; this.pane = "chat"; },
    matches(li) {
      const byTitle = !this.filter || li.dataset.title.includes(this.filter.toLowerCase());
      const byUnread = !this.unreadOnly || Number(li.dataset.unread) > 0;
      return byTitle && byUnread;
    },
  }));

  Alpine.data("chat", (peerId, outRead) => ({
    peerId, outRead,
    init() {
      this.$nextTick(() => this.scrollBottom());
      this.$el.addEventListener("htmx:afterSwap", (e) => {
        const state = document.getElementById("chat-state");
        if (state) this.outRead = Number(state.dataset.outRead);
        if (e.detail.target.id === "messages" || e.detail.target.classList.contains("im-more")) this.keepScroll(e);
      });
    },
    nearBottom() {
      const el = this.$refs.list;
      return el.scrollHeight - el.scrollTop - el.clientHeight < 120;
    },
    scrollBottom() { this.$refs.list.scrollTop = this.$refs.list.scrollHeight; },
    keepScroll(e) { if (this.nearBottom()) this.scrollBottom(); },
  }));
});
```

- [ ] **Step 7: Тесты**

Run: `.venv/bin/pytest tests/web -q`
Expected: PASS. Если `test_im_page_lists_dialogs_with_modes` не находит `class="unread">2<` — проверить, что `unread_count` берётся из `conversation`, а не из корня ответа.

- [ ] **Step 8: Визуальная проверка**

По памяти `web-admin-browser-testing`: поднять scratch-обёртку с Basic Auth, `VK_TOKEN` из `.env` (реальные данные) или `FakeVk`, открыть `/im?sel=<peer>`, сравнить со скриншотом VK: пропорции колонок, аватары, серии сообщений, чипы дат. Записать расхождения в `.omc/notepad.md` для Task 12.

- [ ] **Step 9: Commit**

```bash
git add web/im/routes.py web/templates/im.html web/templates/partials/im*.html web/static/im.css web/static/im.js web/app.py web/templates/base.html web/humanize.py tests/web/test_im_pages.py tests/web/test_humanize.py
git commit -m "add read-only messenger page with dialogs and chat view"
```

---
### Task 7: Живая лента — поллинг новых и подгрузка старых сообщений

**Files:**
- Modify: `web/im/routes.py`, `web/templates/partials/im_chat.html`, `web/templates/partials/im_rows.html`
- Test: `tests/web/test_im_pages.py`

**Interfaces:**
- Consumes: `chat_ctx(peer_id, before, after)` из Task 6.
- Produces: `GET /im/{peer}/messages?after=<id>` → ряды новых + OOB `#chat-state` + OOB `#chat-poll`; `GET /im/{peer}/messages?before=<id>` → ряды старых + новый сентинел `.im-more`.

- [ ] **Step 1: Тесты**

```python
# tests/web/test_im_pages.py (добавить)
def test_poll_returns_only_newer_rows_and_moves_cursor(client):
    r = client.get(f"/im/{PEER_CHAT}/messages?after=500", auth=AUTH, headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert 'data-id="501"' in r.text and 'data-id="502"' in r.text and 'data-id="500"' not in r.text
    assert 'id="chat-poll"' in r.text and "after=502" in r.text and 'hx-swap-oob="true"' in r.text
    assert 'id="chat-state"' in r.text and 'data-out-read="501"' in r.text


def test_poll_without_news_is_empty_but_keeps_cursor(client):
    r = client.get(f"/im/{PEER_CHAT}/messages?after=502", auth=AUTH, headers={"HX-Request": "true"})
    assert r.status_code == 200 and "<article" not in r.text and "after=502" in r.text


def test_older_page_replaces_sentinel(client):
    r = client.get(f"/im/{PEER_CHAT}/messages?before=499", auth=AUTH, headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert client.app.state.vk.calls[-1] == ("history", PEER_CHAT, 40, 499)
    assert 'class="im-more"' in r.text and "before=499" in r.text   # фикстура отдаёт те же id — сентинел на самый старый
```

- [ ] **Step 2: Убедиться, что падает**

Run: `.venv/bin/pytest tests/web/test_im_pages.py -q -k "poll or older"`
Expected: 404

- [ ] **Step 3: Роут**

```python
# web/im/routes.py (добавить в create_router, ПЕРЕД @router.get("/im/{peer_id}"))
    @router.get("/im/{peer_id}/messages")
    def messages_partial(request: Request, peer_id: int, after: int | None = None, before: int | None = None):
        ctx = guard(lambda: chat_ctx(peer_id, before=before, after=after))
        return render.partial(request, "im_rows_page", {"chat": ctx, "after": after, "before": before, "page": "im"})
```

```html
{# web/templates/partials/im_rows_page.html #}
{% set c = chat %}
{% if before %}{% if c.oldest %}<div class="im-more" hx-get="/im/{{ c.peer_id }}/messages?before={{ c.oldest }}" hx-trigger="intersect once" hx-swap="outerHTML"></div>{% endif %}{% endif %}
{% with rows = c.rows, tz = c.tz %}{% include "partials/im_rows.html" %}{% endwith %}
{% if after is not none %}
<div id="chat-poll" hx-swap-oob="true" hx-get="/im/{{ c.peer_id }}/messages?after={{ c.newest }}"
     hx-trigger="every 3s [document.visibilityState === 'visible']" hx-target="#messages" hx-swap="beforeend"></div>
<div id="chat-state" hx-swap-oob="true" data-out-read="{{ c.out_read }}" hidden></div>
{% endif %}
```

В `partials/im_chat.html` после `#chat-state` добавить поллер с начальным курсором:

```html
  <div id="chat-poll" hx-get="/im/{{ c.peer_id }}/messages?after={{ c.newest }}"
       hx-trigger="every 3s [document.visibilityState === 'visible']" hx-target="#messages" hx-swap="beforeend"></div>
```

`chat_ctx` для `before`: `oldest` = id самого старого полученного сообщения (уже так). Для `after`: `newest` = максимум из `after` и id новых, чтобы курсор не откатывался (уже так через `messages[-1].id if messages else after`).

- [ ] **Step 4: Тесты**

Run: `.venv/bin/pytest tests/web -q`
Expected: PASS

- [ ] **Step 5: Проверка в браузере**

Открыть чат в scratch-обёртке с реальным токеном, написать в него с телефона: сообщение появляется ≤ 3 с, скролл остаётся внизу; прокрутить вверх — подгружается страница старых, позиция не прыгает (htmx `outerHTML` сентинела вставляет ряды сверху; если прыгает — в `keepScroll` запомнить `scrollHeight` до свопа и восстановить `scrollTop += delta` через `htmx:beforeSwap`/`afterSwap`).

- [ ] **Step 6: Commit**

```bash
git add web/im/routes.py web/templates/partials/im_chat.html web/templates/partials/im_rows_page.html tests/web/test_im_pages.py
git commit -m "poll new messages and lazy-load older ones in the messenger"
```

---

### Task 8: Отправка текста, ответ-цитата, отметка прочитанного, удаление

**Files:**
- Modify: `web/im/routes.py`, `web/templates/partials/im_chat.html`, `web/templates/partials/im_rows.html`, `web/static/im.js`, `web/static/im.css`
- Test: `tests/web/test_im_pages.py`

**Interfaces:**
- Consumes: `VkClient.send/mark_read/delete_message/messages_by_id`.
- Produces: `POST /im/{peer}/send` (form `text`, `reply_to`), `POST /im/{peer}/read`, `POST /im/{peer}/messages/{id}/delete`; Alpine-компонент `composer`.

- [ ] **Step 1: Тесты**

```python
# tests/web/test_im_pages.py (добавить)
def test_send_text_appends_sent_message(client):
    r = client.post(f"/im/{PEER_CHAT}/send", data={"text": "привет из админки", "reply_to": "500"},
                    auth=AUTH, headers={"HX-Request": "true"})
    assert r.status_code == 200
    vk = client.app.state.vk
    assert ("send", PEER_CHAT, "привет из админки", 500, "") in vk.calls
    assert ("by_id", (503,)) in vk.calls
    assert 'data-id="503"' in r.text and "привет из админки" in r.text
    assert "after=503" in r.text                    # курсор поллинга сдвинут, чтобы не продублировать


def test_send_empty_is_422(client):
    r = client.post(f"/im/{PEER_CHAT}/send", data={"text": "   "}, auth=AUTH, headers={"HX-Request": "true"})
    assert r.status_code == 422 and "send" not in [c[0] for c in client.app.state.vk.calls]


def test_send_vk_error_is_sanitized(client, settings):
    def boom(*a, **k):
        raise RuntimeError(f"bad token {settings.vk_token}")
    client.app.state.vk = FakeVk("t")
    client.app.state.vk.send = boom
    r = client.post(f"/im/{PEER_CHAT}/send", data={"text": "x"}, auth=AUTH, headers={"HX-Request": "true"})
    assert r.status_code == 422 and settings.vk_token not in r.text and "[скрыто]" in r.text


def test_mark_read_and_delete(client):
    assert client.post(f"/im/{PEER_CHAT}/read", auth=AUTH, headers={"HX-Request": "true"}).status_code == 204
    assert client.post(f"/im/{PEER_CHAT}/messages/501/delete", auth=AUTH, headers={"HX-Request": "true"}).status_code == 200
    calls = client.app.state.vk.calls
    assert ("read", PEER_CHAT) in calls and ("delete", 501) in calls
```

- [ ] **Step 2: Убедиться, что падает**

Run: `.venv/bin/pytest tests/web/test_im_pages.py -q -k "send or read"`
Expected: 404/405

- [ ] **Step 3: Роуты**

```python
# web/im/routes.py (добавить в create_router)
from fastapi import Form
from fastapi.responses import RedirectResponse, Response

    def sent_ctx(peer_id: int, message_id: int):
        raw = vk().messages_by_id([message_id])
        messages, out_read = parse_history(raw, vk().me_id, marks())
        return {"peer_id": peer_id, "rows": rows(messages, time.time(), tz), "out_read": out_read,
                "newest": message_id, "oldest": None, "tz": tz}

    def send_form_error(request: Request, peer_id: int, error: str):
        return render.invalid(request, "im_error", {"page": "im"}, error)

    @router.post("/im/{peer_id}/send")
    async def send_message(request: Request, peer_id: int, text: str = Form(""), reply_to: str = Form("")):
        text = text.strip()
        if not text:
            return send_form_error(request, peer_id, "Пустое сообщение")
        reply_id = int(reply_to) if reply_to.strip() else None
        try:
            message_id = vk().send(peer_id, text, reply_to=reply_id)
            ctx = sent_ctx(peer_id, message_id)
        except Exception as e:
            return send_form_error(request, peer_id, f"VK не отправил: {safe_error(e)}")
        if not is_hx(request):
            return RedirectResponse(f"/im?sel={peer_id}", status_code=303)
        return render.partial(request, "im_rows_page", {"chat": ctx, "after": message_id, "before": None, "page": "im"},
                              toast="Отправлено")

    @router.post("/im/{peer_id}/read")
    def mark_read(peer_id: int):
        guard(lambda: vk().mark_read(peer_id))
        return Response(status_code=204)

    @router.post("/im/{peer_id}/messages/{message_id}/delete")
    def delete_message(request: Request, peer_id: int, message_id: int):
        guard(lambda: vk().delete_message(message_id))
        return Response(status_code=200) if is_hx(request) else RedirectResponse(f"/im?sel={peer_id}", status_code=303)
```

`partials/im_error.html`: `<div class="error">{{ error }}</div>` (для не-htmx запросов `render.invalid` бросит 400 — этого достаточно, форма работает без JS только как запасной путь).

- [ ] **Step 4: Композер и действия у сообщений**

В `partials/im_chat.html` после `#messages`:

```html
  <form class="im-composer" x-data="composer()" method="post" action="/im/{{ c.peer_id }}/send"
        hx-post="/im/{{ c.peer_id }}/send" hx-target="#messages" hx-swap="beforeend" hx-disabled-elt="find button[type=submit]"
        hx-on::after-request="if (event.detail.successful) reset()" @im-reply.window="quote($event.detail)">
    <div class="quote-bar" x-show="reply" x-cloak><b x-text="reply?.author"></b><span x-text="reply?.text"></span>
      <button type="button" @click="reply = null" aria-label="Убрать цитату">×</button></div>
    <input type="hidden" name="reply_to" :value="reply?.id || ''">
    <div class="row-input">
      <textarea name="text" rows="1" placeholder="Сообщение" x-ref="t" x-model="text" @input="grow()"
                @keydown.enter.exact.prevent="$el.form.requestSubmit()"></textarea>
      <button type="submit" class="send" aria-label="Отправить"><svg viewBox="0 0 24 24"><path d="M2 21l21-9L2 3v7l15 2-15 2z"/></svg></button>
    </div>
  </form>
```

В `partials/im_rows.html` внутрь `<article class="msg">` перед `.meta`:

```html
  <span class="actions">
    <button type="button" title="Ответить" @click="$dispatch('im-reply', { id: {{ m.id }}, author: {{ m.author|tojson }}, text: {{ (m.text or (m|preview))[:80]|tojson }} })">↩</button>
    {% if m.out %}<button type="button" title="Удалить" hx-post="/im/{{ c.peer_id }}/messages/{{ m.id }}/delete" hx-confirm="Удалить сообщение у всех?" hx-target="closest article" hx-swap="delete">✕</button>{% endif %}
  </span>
```

(`c` определён во всех местах включения `im_rows.html`: `{% set c = chat %}` в `im_chat.html` и `im_rows_page.html`.)

`im.js` — компонент `composer`:

```js
  Alpine.data("composer", () => ({
    text: "", reply: null,
    grow() { const t = this.$refs.t; t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 160) + "px"; },
    quote(d) { this.reply = d; this.$refs.t.focus(); },
    reset() { this.text = ""; this.reply = null; this.$nextTick(() => this.grow()); },
  }));
```

В `chat`: `markRead()` — `fetch("/im/" + peerId + "/read", { method: "POST", headers: { "HX-Request": "true" } })`, вызывается из `init()` и после `afterSwap` цели `#messages`, если `document.visibilityState === "visible"` и `localStorage.getItem("im.readOnOpen") !== "off"` (обернуть чтение `localStorage` в `try`). `hx-confirm` использует `window.confirm` — в браузерной автоматизации не кликать «Удалить» (см. правило про диалоги), в ручной проверке ок.

CSS: `.im-composer { border-top: 1px solid var(--im-line); padding: 0.5rem 1rem; }`, `.row-input { display: flex; gap: 0.5rem; align-items: flex-end; }`, `.row-input textarea { flex: 1; margin: 0; min-height: 44px; max-height: 160px; border-radius: 22px; background: var(--im-side); resize: none; }`, `.send { width: 44px; height: 44px; border-radius: 50%; padding: 0; margin: 0; }`, `.send svg { width: 20px; fill: #fff; }`, `.quote-bar { display: flex; gap: 0.5rem; align-items: center; border-left: 2px solid var(--im-blue); padding-left: 0.6rem; margin-bottom: 0.4rem; font-size: 0.9em; }`, `.msg .actions { display: none; gap: 0.2rem; }`, `.msg:hover .actions { display: flex; }`, `.actions button { width: auto; padding: 0 0.4rem; margin: 0; background: none; border: none; color: var(--pico-muted-color); }`.

- [ ] **Step 5: Тесты**

Run: `.venv/bin/pytest tests/web -q`
Expected: PASS

- [ ] **Step 6: Проверка в браузере**

Отправить текст и ответ с цитатой в чат «test»; убедиться в VK на телефоне, что цитата прикрепилась, поле очистилось, сообщение появилось один раз (поллинг не дублирует — курсор `after` сдвинут OOB-поллером из ответа `send`).

- [ ] **Step 7: Commit**

```bash
git add web/im/routes.py web/templates/partials/im_chat.html web/templates/partials/im_rows.html web/templates/partials/im_error.html web/static/im.js web/static/im.css tests/web/test_im_pages.py
git commit -m "send text and quoted replies, mark read, delete own messages from the messenger"
```

---
### Task 9: Голосовые сообщения из `.ogg` / `.mp3` (mp3 конвертируется в ogg)

**Files:**
- Create: `web/im/voice.py`
- Modify: `web/im/routes.py` (multipart в `/send`), `web/templates/partials/im_chat.html`, `web/static/im.js`, `web/static/im.css`, `Dockerfile.web` (ffmpeg), `README.md` (локально нужен ffmpeg)
- Test: `tests/web/test_im_voice.py`, `tests/web/test_im_pages.py`

**Interfaces:**
- Consumes: `VkClient.upload_voice(peer_id, data, ext) -> str` (Task 1), `VkClient.send(..., attachment=)`.
- Produces: `sniff_voice(data: bytes, filename: str) -> str` (`"ogg"` | `"mp3"`, иначе `ValueError`), `to_ogg(data: bytes, run=subprocess.run) -> bytes`, `prepare_voice(data: bytes, filename: str, run=subprocess.run) -> bytes` (всегда ogg), `MAX_VOICE_BYTES = 20 * 1024 * 1024`; поле формы `voice` в `POST /im/{peer}/send`.

- [ ] **Step 1: Тесты**

```python
# tests/web/test_im_voice.py
import shutil
import subprocess

import pytest

from web.im.voice import MAX_VOICE_BYTES, prepare_voice, sniff_voice, to_ogg

OGG = b"OggS" + b"\0" * 40
MP3 = b"ID3\x04" + b"\0" * 40


def test_sniff_by_magic_bytes_not_extension():
    assert sniff_voice(OGG, "whatever.bin") == "ogg"
    assert sniff_voice(MP3, "voice.mp3") == "mp3"
    assert sniff_voice(b"\xff\xfb\x90\x00" + b"\0" * 40, "voice.mp3") == "mp3"


def test_sniff_rejects_other_files():
    with pytest.raises(ValueError, match="ogg"):
        sniff_voice(b"RIFF....WAVE" + b"\0" * 40, "voice.wav")
    with pytest.raises(ValueError, match="пуст"):
        sniff_voice(b"", "voice.ogg")


def test_sniff_rejects_oversize():
    with pytest.raises(ValueError, match="20"):
        sniff_voice(b"OggS" + b"\0" * MAX_VOICE_BYTES, "v.ogg")


def test_to_ogg_pipes_through_ffmpeg():
    seen = {}

    def run(cmd, **kw):
        seen["cmd"], seen["input"] = cmd, kw["input"]
        return subprocess.CompletedProcess(cmd, 0, stdout=OGG, stderr=b"")

    assert to_ogg(MP3, run=run) == OGG
    assert seen["input"] == MP3 and seen["cmd"][0] == "ffmpeg" and "libopus" in seen["cmd"]
    assert "pipe:0" in seen["cmd"] and "pipe:1" in seen["cmd"]


def test_to_ogg_reports_ffmpeg_failure_and_absence():
    def fails(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"Invalid data found")

    with pytest.raises(ValueError, match="Invalid data"):
        to_ogg(MP3, run=fails)

    def missing(cmd, **kw):
        raise FileNotFoundError

    with pytest.raises(ValueError, match="ffmpeg"):
        to_ogg(MP3, run=missing)


def test_prepare_voice_passes_ogg_through_and_converts_mp3():
    assert prepare_voice(OGG, "v.ogg", run=lambda *a, **k: pytest.fail("ogg не конвертируем")) == OGG
    converted = prepare_voice(MP3, "v.mp3", run=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, OGG, b""))
    assert converted == OGG


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="нужен ffmpeg")
def test_real_ffmpeg_converts_mp3_to_opus():
    mp3 = subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.3",
                          "-c:a", "libmp3lame", "-f", "mp3", "pipe:1"], capture_output=True, check=True).stdout
    ogg = to_ogg(mp3)
    assert ogg[:4] == b"OggS" and b"OpusHead" in ogg[:200]
```

```python
# tests/web/test_im_pages.py (добавить)
def test_send_voice_uploads_then_sends_attachment(client):
    r = client.post(f"/im/{PEER_CHAT}/send", data={"text": ""},
                    files={"voice": ("hello.ogg", b"OggS" + b"\0" * 100, "audio/ogg")},
                    auth=AUTH, headers={"HX-Request": "true"})
    assert r.status_code == 200
    calls = client.app.state.vk.calls
    assert ("voice", PEER_CHAT, 104, "ogg") in calls
    assert ("send", PEER_CHAT, "", None, "audio_message1_8_abc") in calls


def test_send_mp3_is_converted_before_upload(client, monkeypatch):
    monkeypatch.setattr("web.im.routes.prepare_voice", lambda data, name: b"OggS" + b"\0" * 10)
    r = client.post(f"/im/{PEER_CHAT}/send", data={"text": "с голосом"},
                    files={"voice": ("hello.mp3", b"ID3\x04" + b"\0" * 100, "audio/mpeg")},
                    auth=AUTH, headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert ("voice", PEER_CHAT, 14, "ogg") in client.app.state.vk.calls


def test_send_bad_voice_is_422_without_vk_calls(client):
    r = client.post(f"/im/{PEER_CHAT}/send", data={"text": ""},
                    files={"voice": ("x.wav", b"RIFF" + b"\0" * 100, "audio/wav")},
                    auth=AUTH, headers={"HX-Request": "true"})
    assert r.status_code == 422 and "ogg" in r.text
    assert not [c for c in client.app.state.vk.calls if c[0] in ("voice", "send")]
```

- [ ] **Step 2: Убедиться, что падает**

Run: `.venv/bin/pytest tests/web/test_im_voice.py tests/web/test_im_pages.py -q -k "voice or mp3"`
Expected: `ModuleNotFoundError`, а в `/send` — 422 «Пустое сообщение»

- [ ] **Step 3: Реализация**

```python
# web/im/voice.py
import subprocess

MAX_VOICE_BYTES = 20 * 1024 * 1024
FFMPEG_TIMEOUT = 60
ACCEPTED = "Нужен .ogg (Opus) или .mp3"
# VK принимает голосовые только как Ogg Opus; моно 48 кГц — то, что пишет сам клиент VK
FFMPEG_TO_OPUS = ["ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-vn", "-c:a", "libopus",
                  "-b:a", "48k", "-ar", "48000", "-ac", "1", "-f", "ogg", "pipe:1"]


def sniff_voice(data: bytes, filename: str) -> str:
    if not data:
        raise ValueError("Файл пуст")
    if len(data) > MAX_VOICE_BYTES:
        raise ValueError(f"Файл больше {MAX_VOICE_BYTES // (1024 * 1024)} МБ")
    if data[:4] == b"OggS":
        return "ogg"
    # mp3 начинается либо с тега ID3, либо сразу с MPEG-фрейма (11 бит синхронизации)
    if data[:3] == b"ID3" or (data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return "mp3"
    raise ValueError(f"{ACCEPTED}, а не «{filename}»")


def to_ogg(data: bytes, run=subprocess.run) -> bytes:
    try:
        done = run(FFMPEG_TO_OPUS, input=data, capture_output=True, timeout=FFMPEG_TIMEOUT)
    except FileNotFoundError:
        raise ValueError("ffmpeg не установлен, mp3 сконвертировать нечем") from None
    except subprocess.TimeoutExpired:
        raise ValueError("ffmpeg не уложился в минуту") from None
    if done.returncode != 0 or not done.stdout:
        tail = done.stderr.decode(errors="replace").strip().splitlines()[-1:] or ["без деталей"]
        raise ValueError(f"Не удалось сконвертировать mp3: {tail[0]}")
    return done.stdout


def prepare_voice(data: bytes, filename: str, run=subprocess.run) -> bytes:
    return data if sniff_voice(data, filename) == "ogg" else to_ogg(data, run=run)
```

В `routes.send_message` заменить сигнатуру и тело:

```python
from fastapi import File, Form, UploadFile
from starlette.concurrency import run_in_threadpool
from web.im.voice import prepare_voice

    @router.post("/im/{peer_id}/send")
    async def send_message(request: Request, peer_id: int, text: str = Form(""), reply_to: str = Form(""),
                           voice: UploadFile | None = File(None)):
        text = text.strip()
        data = await voice.read() if voice is not None and voice.filename else b""
        if not text and not data:
            return send_form_error(request, peer_id, "Пустое сообщение")
        reply_id = int(reply_to) if reply_to.strip() else None
        try:
            attachment = ""
            if data:
                ogg = await run_in_threadpool(prepare_voice, data, voice.filename)
                attachment = await run_in_threadpool(vk().upload_voice, peer_id, ogg, "ogg")
        except ValueError as e:
            return send_form_error(request, peer_id, str(e))
        except Exception as e:
            return send_form_error(request, peer_id, f"VK не принял голосовое: {safe_error(e)}")
        try:
            message_id = vk().send(peer_id, text, reply_to=reply_id, attachment=attachment)
            ctx = sent_ctx(peer_id, message_id)
        except Exception as e:
            return send_form_error(request, peer_id, f"VK не отправил: {safe_error(e)}")
        ...  # ответ как в Task 8
```

Файл живёт только в памяти (`await voice.read()`), на диск не пишется; `UploadFile` Starlette спулит на диск свыше 1 МБ во временный файл ОС и удаляет его при закрытии — этого достаточно, отдельно ничего не сохраняем. Конвертация ffmpeg — pipe в pipe, тоже без файлов. Роут `async`, а `subprocess.run` и загрузка в VK блокирующие, поэтому идут через `run_in_threadpool`, чтобы не останавливать event loop на минуту. `monkeypatch.setattr("web.im.routes.prepare_voice", ...)` в тесте работает, потому что функция импортируется в модуль роутов по имени.

`Dockerfile.web` после `WORKDIR /app` (ffmpeg из Debian уже с `libopus`):

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -r -f /var/lib/apt/lists/*
```

- [ ] **Step 4: Композер — кнопка ⊕ и чип файла**

В `partials/im_chat.html` форме добавить `enctype="multipart/form-data"`, перед `.row-input`:

```html
    <div class="file-chip" x-show="file" x-cloak><span x-text="file?.name"></span><span class="muted" x-text="size"></span>
      <button type="button" @click="clearFile()" aria-label="Убрать файл">×</button></div>
```

внутри `.row-input` первым элементом:

```html
      <label class="attach" title="Голосовое из .ogg/.mp3"><input type="file" name="voice" accept=".ogg,.mp3,audio/ogg,audio/mpeg" x-ref="f" @change="pick()" hidden><svg viewBox="0 0 24 24"><path d="M12 2a10 10 0 100 20 10 10 0 000-20zm5 11h-4v4h-2v-4H7v-2h4V7h2v4h4z"/></svg></label>
```

`composer` в `im.js`:

```js
    file: null,
    get size() { return this.file ? (this.file.size / 1024 / 1024).toFixed(1) + " МБ" : ""; },
    pick() { const f = this.$refs.f.files[0]; this.file = f || null; if (f && !/\.(ogg|mp3)$/i.test(f.name)) { toast("Нужен .ogg или .mp3", "bad"); this.clearFile(); } },
    clearFile() { this.file = null; this.$refs.f.value = ""; },
    reset() { this.text = ""; this.reply = null; this.clearFile(); this.$nextTick(() => this.grow()); },
```

CSS: `.attach { width: 44px; height: 44px; display: grid; place-items: center; cursor: pointer; margin: 0; }`, `.attach svg { width: 26px; fill: var(--pico-muted-color); }`, `.file-chip { display: inline-flex; gap: 0.5rem; align-items: center; background: var(--im-side); border-radius: 999px; padding: 0.2rem 0.8rem; margin-bottom: 0.4rem; font-size: 0.9em; }`.

- [ ] **Step 5: Тесты**

Run: `.venv/bin/pytest -q`
Expected: PASS (включая `test_real_ffmpeg_converts_mp3_to_opus`, локально ffmpeg есть)

- [ ] **Step 6: Проверка на живом VK**

Отправить в «test» `.ogg` и `.mp3` (те же файлы, что в Task 0) с текстом и без: в VK на телефоне оба видны как голосовые с плеером; в админке отправленное сообщение появилось с `<audio>`.

- [ ] **Step 7: Commit**

```bash
git add web/im/voice.py web/im/routes.py web/templates/partials/im_chat.html web/static/im.js web/static/im.css Dockerfile.web tests/web/test_im_voice.py tests/web/test_im_pages.py
git commit -m "send voice messages from ogg or mp3 files, converting mp3 to opus with ffmpeg"
```

---

### Task 10: Панель «Бот в этом чате»

**Files:**
- Create: `web/templates/partials/im_bot.html`
- Modify: `web/im/routes.py`, `web/templates/partials/im_chat.html`, `web/static/im.css`, `web/static/im.js`
- Test: `tests/web/test_im_bot.py`

**Interfaces:**
- Consumes: Task 4 (`bot_mode`, `chat_controls`), Task 5 (`set_*`), `bot.personas.list_personas`, `VkClient.members`, `web.services.access_raw/load_runtime_dict`, `bot.status.write_json_atomic`.
- Produces: `GET /im/{peer}/bot`, `POST /im/{peer}/bot/{switch}`, `POST /im/{peer}/bot/prompt`, `POST /im/{peer}/bot/personas`, `POST /im/{peer}/bot/members/{user}`; partial `im_bot` с OOB `#chat-badge`.

- [ ] **Step 1: Тесты**

```python
# tests/web/test_im_bot.py
import json

import pytest
from fastapi.testclient import TestClient

from tests.web.conftest import AUTH
from tests.web.im_fixtures import PEER_CHAT, PEER_USER
from tests.web.test_im_pages import FakeLlm, FakeVk
from web.app import create_app

HX = {"HX-Request": "true"}


@pytest.fixture
def client(settings):
    open(f"{settings.personas_dir}/rina.md", "w").write("# Рина\nперсона")
    open(f"{settings.personas_dir}/monika.md", "w").write("# Моника\nперсона")
    return TestClient(create_app(settings, vk_factory=FakeVk, llm_factory=FakeLlm), follow_redirects=False)


def access(settings):
    return json.load(open(settings.access_file))


def runtime(settings):
    return json.load(open(settings.runtime_file))


def test_panel_shows_mode_members_and_switches(client):
    r = client.get(f"/im/{PEER_CHAT}/bot", auth=AUTH, headers=HX)
    assert r.status_code == 200
    assert "по тегу" in r.text and 'name="on"' in r.text
    assert "Вася Пупкин" in r.text and "Аня Иванова" in r.text        # участники
    assert "Валентина Тина" not in r.text.split("Участники")[1]         # себя в списке нет
    assert "Рина" in r.text and "Моника" in r.text                      # персоны


def test_switch_auto_in_chat_writes_access_and_updates_badge(client, settings):
    r = client.post(f"/im/{PEER_CHAT}/bot/auto", data={"on": "1"}, auth=AUTH, headers=HX)
    assert r.status_code == 200
    assert access(settings)["auto_reply_peers"] == [PEER_CHAT]
    assert 'id="chat-badge" hx-swap-oob="true"' in r.text and ">авто<" in r.text
    client.post(f"/im/{PEER_CHAT}/bot/auto", data={}, auth=AUTH, headers=HX)
    assert access(settings)["auto_reply_peers"] == []


def test_switch_auto_in_private_dialog_uses_user_list(client, settings):
    client.post(f"/im/{PEER_USER}/bot/auto", data={"on": "1"}, auth=AUTH, headers=HX)
    assert access(settings)["auto_reply_users"] == [PEER_USER]
    client.post(f"/im/{PEER_USER}/bot/blocked", data={"on": "1"}, auth=AUTH, headers=HX)
    assert access(settings)["blocked_users"] == [PEER_USER]


def test_onboarding_is_chats_only(client):
    assert client.post(f"/im/{PEER_USER}/bot/onboarding", data={"on": "1"}, auth=AUTH, headers=HX).status_code == 404
    assert client.post(f"/im/{PEER_CHAT}/bot/onboarding", data={"on": "1"}, auth=AUTH, headers=HX).status_code == 200


def test_pause_and_personas_go_to_runtime(client, settings):
    client.post(f"/im/{PEER_CHAT}/bot/paused", data={"on": "1"}, auth=AUTH, headers=HX)
    assert runtime(settings)["paused_peers"] == [PEER_CHAT]
    r = client.post(f"/im/{PEER_CHAT}/bot/personas", data=[("slug", "rina"), ("slug", "monika")], auth=AUTH, headers=HX)
    assert r.status_code == 200 and runtime(settings)["peer_personas"] == {str(PEER_CHAT): ["rina", "monika"]}
    client.post(f"/im/{PEER_CHAT}/bot/personas", data=[("slug", "nope")], auth=AUTH, headers=HX)
    assert runtime(settings)["peer_personas"] == {str(PEER_CHAT): ["rina", "monika"]}   # неизвестный slug — 422, файл не тронут


def test_prompt_goes_to_the_right_layer(client, settings):
    client.post(f"/im/{PEER_CHAT}/bot/prompt", data={"text": "тут все свои"}, auth=AUTH, headers=HX)
    assert access(settings)["peer_prompts"] == {str(PEER_CHAT): "тут все свои"}
    client.post(f"/im/{PEER_USER}/bot/prompt", data={"text": "подруга"}, auth=AUTH, headers=HX)
    assert access(settings)["user_prompts"] == {str(PEER_USER): "подруга"}


def test_member_block_in_chat(client, settings):
    client.post(f"/im/{PEER_CHAT}/bot/members/11", data={"on": "1"}, auth=AUTH, headers=HX)
    assert access(settings)["peer_blocked_users"] == {str(PEER_CHAT): [11]}
    r = client.get(f"/im/{PEER_CHAT}/bot", auth=AUTH, headers=HX)
    assert "checked" in r.text.split("Вася Пупкин")[1].split("</li>")[0]
```

- [ ] **Step 2: Убедиться, что падает**

Run: `.venv/bin/pytest tests/web/test_im_bot.py -q`
Expected: 404

- [ ] **Step 3: Роуты**

```python
# web/im/routes.py (добавить в create_router)
from bot.personas import list_personas
from bot.status import write_json_atomic
from web.im.controls import set_keyed_text, set_member, set_paused_peer, set_peer_blocked, set_peer_personas
from web.im.modes import chat_controls
from web.im.views import Profiles, is_chat
from web.services import access_raw, load_runtime_dict

    SWITCHES = {  # переключатель → (файл, поле для лички, поле для беседы)
        "auto": ("access", "auto_reply_users", "auto_reply_peers"),
        "blocked": ("access", "blocked_users", "blocked_peers"),
        "onboarding": ("access", None, "onboarding_peers"),
        "paused": ("runtime", "paused_peers", "paused_peers"),
    }

    def bot_ctx(peer_id: int, error: str = ""):
        access, rt = lists(), runtime()
        raw = vk().members(peer_id) if is_chat(peer_id) else {}
        profiles = Profiles(raw)
        members = [(m["member_id"], profiles.name(m["member_id"]), profiles.photo(m["member_id"]))
                   for m in raw.get("items") or [] if m["member_id"] != vk().me_id and m["member_id"] > 0]
        return {"peer_id": peer_id, "mode": bot_mode(peer_id, access, rt), "c": chat_controls(peer_id, access, rt),
                "members": members, "personas": list_personas(settings.personas_dir),
                "active": rt.active_persona, "error": error, "page": "im"}

    def bot_panel(request: Request, peer_id: int, toast: str | None = None):
        return render.partial(request, "im_bot", guard(lambda: bot_ctx(peer_id)), toast=toast)

    @router.get("/im/{peer_id}/bot")
    def bot_page(request: Request, peer_id: int):
        return bot_panel(request, peer_id)

    @router.post("/im/{peer_id}/bot/{switch}")
    def bot_switch(request: Request, peer_id: int, switch: str, on: str = Form("")):
        if switch not in SWITCHES:
            raise HTTPException(404)
        target, user_field, peer_field = SWITCHES[switch]
        field = peer_field if is_chat(peer_id) else user_field
        if field is None:
            raise HTTPException(404, "только для бесед")
        enabled = bool(on)
        if target == "runtime":
            write_json_atomic(settings.runtime_file, set_paused_peer(load_runtime_dict(settings.runtime_file), peer_id, enabled))
        else:
            data = set_member(access_raw(settings.access_file), field, peer_id, enabled, vk().resolve_screen_names)
            write_json_atomic(settings.access_file, data)
        return bot_panel(request, peer_id, toast="Сохранено")

    @router.post("/im/{peer_id}/bot/prompt")
    def bot_prompt(request: Request, peer_id: int, text: str = Form("")):
        field = "peer_prompts" if is_chat(peer_id) else "user_prompts"
        data = set_keyed_text(access_raw(settings.access_file), field, peer_id, text, vk().resolve_screen_names)
        write_json_atomic(settings.access_file, data)
        return bot_panel(request, peer_id, toast="Промпт сохранён")

    @router.post("/im/{peer_id}/bot/personas")
    async def bot_personas(request: Request, peer_id: int):
        slugs = [str(v) for v in (await request.form()).getlist("slug")]
        known = {p.slug for p in list_personas(settings.personas_dir)}
        unknown = [s for s in slugs if s not in known]
        if unknown:
            return render.invalid(request, "im_bot", guard(lambda: bot_ctx(peer_id)), f"Нет персоны: {', '.join(unknown)}")
        write_json_atomic(settings.runtime_file, set_peer_personas(load_runtime_dict(settings.runtime_file), peer_id, slugs))
        return bot_panel(request, peer_id, toast="Персоны сохранены")

    @router.post("/im/{peer_id}/bot/members/{user_id}")
    def bot_member(request: Request, peer_id: int, user_id: int, on: str = Form("")):
        data = set_peer_blocked(access_raw(settings.access_file), peer_id, user_id, bool(on), vk().resolve_screen_names)
        write_json_atomic(settings.access_file, data)
        return bot_panel(request, peer_id, toast="Сохранено")
```

Порядок объявления: `/im/{peer_id}/bot/prompt`, `/personas`, `/members/{user_id}` — раньше `/im/{peer_id}/bot/{switch}`, иначе `prompt` попадёт в `switch`.

- [ ] **Step 4: Шаблон панели**

```html
{# web/templates/partials/im_bot.html #}
<div id="bot-panel" class="im-bot">
  <span id="chat-badge" hx-swap-oob="true">{% with m = mode %}{% include "partials/im_badge.html" %}{% endwith %}</span>
  {% if error %}<div class="error">{{ error }}</div>{% endif %}
  <header><b>Бот в этом чате</b> {% with m = mode %}{% include "partials/im_badge.html" %}{% endwith %}
    <small class="muted">{{ mode.reason }}</small></header>
  {% for switch, title, hint, value, show in [
      ("auto", "Отвечать без тега", "на каждое сообщение" if c.private else "всем участникам, как в личке", c.auto, True),
      ("onboarding", "Знакомиться с новичками", "вопросы вошедшим", c.onboarding, not c.private),
      ("paused", "Пауза в этом чате", "runtime.paused_peers", c.paused, True),
      ("blocked", "Заблокировать", "бот молчит здесь всегда", c.blocked, True)] %}
  {% if show %}<form hx-post="/im/{{ peer_id }}/bot/{{ switch }}" hx-target="#bot-panel" hx-swap="outerHTML" hx-trigger="change">
    <label><input type="checkbox" role="switch" name="on" value="1" {{ 'checked' if value }}> {{ title }} <small>{{ hint }}</small></label>
  </form>{% endif %}{% endfor %}
  <form hx-post="/im/{{ peer_id }}/bot/personas" hx-target="#bot-panel" hx-swap="outerHTML" hx-trigger="change">
    <label>Персоны для этого чата <small>пусто — активная «{{ active or 'по умолчанию' }}»; несколько — случайная на каждый ответ</small></label>
    <div class="persona-list">{% for p in personas %}
      <label><input type="checkbox" name="slug" value="{{ p.slug }}" {{ 'checked' if p.slug in c.personas }}> {{ p.name }}</label>{% endfor %}</div>
  </form>
  <form hx-post="/im/{{ peer_id }}/bot/prompt" hx-target="#bot-panel" hx-swap="outerHTML">
    <label>{{ "Про этого собеседника" if c.private else "Про эту беседу" }} <small>слой {{ "user_prompts" if c.private else "peer_prompts" }}</small>
      <textarea name="text" x-data="autogrow" @input="grow()">{{ c.prompt }}</textarea></label>
    <button class="outline">Сохранить промпт</button>
  </form>
  {% if members %}<details open><summary>Участники <span class="muted">{{ members|length }}</span></summary>
    <ul class="members">{% for uid, name, photo in members %}<li>
      <span class="ava">{% if photo %}<img src="{{ photo }}" alt="">{% endif %}</span>
      <a href="https://vk.com/id{{ uid }}">{{ name }}</a>
      <form hx-post="/im/{{ peer_id }}/bot/members/{{ uid }}" hx-target="#bot-panel" hx-swap="outerHTML" hx-trigger="change">
        <label title="Не отвечать этому участнику в этой беседе"><input type="checkbox" role="switch" name="on" value="1" {{ 'checked' if uid in c.blocked_members }}> игнор</label>
      </form></li>{% endfor %}</ul>
  </details>{% endif %}
</div>
```

В `partials/im_chat.html` в шапку добавить шестерёнку и контейнер панели:

```html
    <button type="button" class="gear" aria-label="Бот в этом чате" @click="panel = !panel"
            hx-get="/im/{{ c.peer_id }}/bot" hx-target="#bot-slot" hx-swap="innerHTML" hx-trigger="click once">⚙</button>
  </header>
  <div id="bot-slot" class="im-bot-slot" x-show="panel" x-cloak></div>
```

и `panel: false` в состоянии `chat`. CSS: `.im-bot-slot { position: absolute; right: 0; top: 57px; width: min(420px, 100%); max-height: calc(100% - 57px); overflow-y: auto; background: var(--pico-card-background-color); border-left: 1px solid var(--im-line); box-shadow: var(--pico-card-box-shadow); z-index: 5; }` (`.im-main { position: relative; }`), `.im-bot { padding: 1rem; display: flex; flex-direction: column; gap: 0.75rem; }`, `.persona-list { display: flex; flex-wrap: wrap; gap: 0.5rem 1rem; }`, `.members { list-style: none; padding: 0; margin: 0; }`, `.members li { display: flex; align-items: center; gap: 0.6rem; padding: 0.3rem 0; }`, `.members .ava { width: 32px; height: 32px; }`, `.members form { margin-left: auto; margin-bottom: 0; }`.

- [ ] **Step 5: Тесты**

Run: `.venv/bin/pytest -q`
Expected: PASS. Если `test_panel_shows_mode_members_and_switches` падает на «Валентина Тина» — проверить, что `bot_ctx` фильтрует `vk().me_id`.

- [ ] **Step 6: Проверка hot-reload у бота**

В scratch-обёртке включить «Отвечать без тега» для чата «test», убедиться `cat config/access.json` содержит peer в `auto_reply_peers`, а запущенный локально бот (`python -m bot.main`) в логах пишет «Списки доступа перечитаны» и отвечает в «test» без тега. Выключить — перестаёт.

- [ ] **Step 7: Commit**

```bash
git add web/im/routes.py web/templates/partials/im_bot.html web/templates/partials/im_chat.html web/static/im.css web/static/im.js tests/web/test_im_bot.py
git commit -m "control the bot per chat from the messenger: mode, lists, personas, prompt, members"
```

---
### Task 11: «Черновик от бота» в композере

Кнопка ✨ просит LLM ответить на текущий диалог так, как ответил бы бот в этом чате (персона чата, слои промпта, защита от повторов), и кладёт текст в поле ввода. В VK ничего не уходит, пока владелец не нажмёт «Отправить».

**Files:**
- Create: `web/im/draft.py`
- Modify: `web/im/routes.py`, `web/templates/partials/im_chat.html`, `web/static/im.js`
- Test: `tests/web/test_im_draft.py`, `tests/web/test_im_pages.py`

**Interfaces:**
- Consumes: `bot.reply.ReplyRequest/generate_reply`, `bot.context.build_context`, `bot.repetition.own_messages`, `bot.access.scoped_prompts`, `bot.runtime.persona_for`, `bot.personas.load_persona`, `bot.llm.secrets_of`.
- Produces: `draft_reply(settings, llm, vk, lists, rt, peer_id) -> str`; `POST /im/{peer}/draft` → `text/plain`.

- [ ] **Step 1: Тесты**

```python
# tests/web/test_im_draft.py
from bot.access import AccessLists
from bot.runtime import RuntimeSettings
from tests.web.im_fixtures import HISTORY, ME, PEER_CHAT
from web.im.draft import draft_reply


class Llm:
    def __init__(self):
        self.calls = []

    def reply(self, conversation, asker, **kw):
        self.calls.append((conversation, asker, kw))
        return "ну и ладно"


class Vk:
    me_id = ME

    def history(self, peer_id, count):
        return HISTORY["items"]

    def resolve_name(self, uid):
        return {11: "Вася Пупкин", 22: "Аня Иванова"}.get(uid, "Кто-то")


def test_draft_uses_chat_persona_layers_and_last_speaker(settings):
    open(f"{settings.personas_dir}/rina.md", "w").write("# Рина\nты рина")
    llm = Llm()
    lists = AccessLists(auto_reply_peers=frozenset({PEER_CHAT}), peer_prompts={PEER_CHAT: "тут все свои"}, chat_prompt="беседа")
    rt = RuntimeSettings(active_persona="valentina", peer_personas=((PEER_CHAT, ("rina",)),), temperature=0.5)
    text = draft_reply(settings, llm, Vk(), lists, rt, PEER_CHAT)
    assert text == "ну и ладно"
    conversation, asker, kw = llm.calls[-1]
    assert asker == "Вася Пупкин" and "Ты: ну все тогда" in conversation
    assert kw["persona_prompt"] == "ты рина" and kw["user_prompt"] == "тут все свои" and kw["private_prompt"] == "беседа"
    assert kw["auto_chat"] and not kw["is_private"] and kw["temperature"] == 0.5
    assert kw["own_recent"] == ["ну все тогда"]
```

```python
# tests/web/test_im_pages.py (добавить)
def test_draft_route_returns_plain_text_and_sends_nothing(client):
    r = client.post(f"/im/{PEER_CHAT}/draft", auth=AUTH, headers={"HX-Request": "true"})
    assert r.status_code == 200 and r.text == "черновик от llm"
    assert r.headers["content-type"].startswith("text/plain")
    assert "send" not in [c[0] for c in client.app.state.vk.calls]
```

- [ ] **Step 2: Убедиться, что падает**

Run: `.venv/bin/pytest tests/web/test_im_draft.py tests/web/test_im_pages.py -q -k draft`
Expected: `ModuleNotFoundError`, 404

- [ ] **Step 3: Реализация**

```python
# web/im/draft.py
from bot.access import scoped_prompts
from bot.context import build_context
from bot.llm import secrets_of
from bot.personas import load_persona
from bot.reply import ReplyRequest, generate_reply
from bot.repetition import own_messages
from bot.runtime import persona_for
from web.im.views import is_chat


def draft_reply(settings, llm, vk, lists, rt, peer_id: int) -> str:
    history = vk.history(peer_id, rt.context_messages)
    conversation = build_context(history, vk.resolve_name, settings.message_char_limit,
                                 settings.context_char_budget, vk.me_id)
    private = not is_chat(peer_id)
    general_prompt, specific_prompt = scoped_prompts(lists, peer_id, private)
    last_other = next((m["from_id"] for m in history if m.get("from_id") != vk.me_id), peer_id)
    slug = persona_for(rt, peer_id)
    persona = load_persona(settings.personas_dir, slug) if slug else None
    request = ReplyRequest(
        conversation, vk.resolve_name(last_other), is_private=private,
        auto_chat=not private and (peer_id in lists.auto_reply_peers or peer_id in lists.onboarding_peers),
        persona_prompt=persona.prompt if persona else settings.persona_prompt,
        private_prompt=general_prompt, user_prompt=specific_prompt,
        temperature=rt.temperature, seed=last_other,
        own_recent=own_messages(history, vk.me_id), model=rt.active_model,
    )
    reply, _ = generate_reply(llm, request, [settings.vk_token, *secrets_of(settings)], vk.me_id)
    return reply
```

Роут:

```python
from fastapi.responses import PlainTextResponse
from web.im.draft import draft_reply

    @router.post("/im/{peer_id}/draft")
    def bot_draft(peer_id: int):
        try:
            return PlainTextResponse(draft_reply(settings, llm(), vk(), lists(), runtime(), peer_id))
        except Exception as e:
            raise HTTPException(502, f"Не удалось получить черновик: {safe_error(e)}")
```

Композер (`partials/im_chat.html`, внутри `.row-input` перед `.send`):

```html
      <button type="button" class="draft" title="Черновик от бота" hx-post="/im/{{ c.peer_id }}/draft" hx-swap="none"
              hx-disabled-elt="this" hx-on::after-request="if (event.detail.successful) draft(event.detail.xhr.responseText)">✨</button>
```

`composer.draft(t) { this.text = t; this.$nextTick(() => { this.grow(); this.$refs.t.focus(); }); }`. Ошибка 502 покажется тостом через уже существующий обработчик `htmx:responseError`.

- [ ] **Step 4: Тесты**

Run: `.venv/bin/pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/im/draft.py web/im/routes.py web/templates/partials/im_chat.html web/static/im.js tests/web/test_im_draft.py tests/web/test_im_pages.py
git commit -m "draft a bot reply into the composer without sending"
```

---

### Task 12: Мобильная раскладка, склейка серий после поллинга, визуальная доводка

**Files:**
- Modify: `web/im/routes.py`, `web/templates/partials/im_chat.html`, `web/templates/partials/im_rows_page.html`, `web/static/im.css`, `web/static/im.js`
- Test: `tests/web/test_im_pages.py`

**Interfaces:**
- Consumes: всё выше.
- Produces: параметр `last_from` в `GET /im/{peer}/messages?after=` (серии не рвутся на границе поллинга); переключатель «читать без отметки» в панели; проверенная раскладка на 390px.

- [ ] **Step 1: Тест склейки серий**

```python
# tests/web/test_im_pages.py (добавить)
def test_poll_continues_series_of_same_author(client):
    r = client.get(f"/im/{PEER_CHAT}/messages?after=501&last_from=11&last_ts=1788876200", auth=AUTH, headers={"HX-Request": "true"})
    assert 'class="msg  "' in r.text or 'class="msg "' in r.text        # 502 от Васи без head
    r = client.get(f"/im/{PEER_CHAT}/messages?after=501&last_from=1&last_ts=1788876200", auth=AUTH, headers={"HX-Request": "true"})
    assert 'class="msg head' in r.text
```

- [ ] **Step 2: Реализация**

`rows(messages, now, tz, prev=None)` в `views.py`: необязательный `prev: Message | None` — «последнее уже отрисованное сообщение», с ним сравнивается первое новое (автор, `SERIES_GAP`, день). В `chat_ctx` принять `last_from: int | None`, `last_ts: float | None` и передать `prev=Message(0, last_ts, last_from, "", "", "", False, False)` при обоих заданных. Поллер (`im_rows_page.html` и `im_chat.html`) формирует URL через `hx-vals='js:{last_from: lastFrom(), last_ts: lastTs()}'`, где функции в `chat` читают `dataset.from`/`dataset.ts` у последнего `.msg` (добавить `data-ts="{{ m.ts }}"` в ряд). Чип дня для первого нового сообщения ставится, только если день отличается от `prev`.

- [ ] **Step 3: Мобильная раскладка и мелочи**

- Переход в чат на телефоне: клик по диалогу → `pane = 'chat'`; кнопка «‹» → `pane = 'list'`; `history.back` не трогаем (htmx уже пушит `/im?sel=`).
- Композер на телефоне: `position: sticky; bottom: 0`, `100dvh`, чтобы клавиатура не прятала поле.
- В панель бота добавить переключатель «Читать без отметки» (Alpine, `localStorage["im.readOnOpen"]`, `try/catch`), подпись «VK не увидит, что сообщения прочитаны».
- `Escape` в композере убирает цитату; `Ctrl/Cmd+K` фокусирует поиск.
- Список диалогов: при поллинге сохранять `active` (класс ставится через `:class` от `sel`, поэтому переживает `innerHTML`), фильтр применяется через `x-show` к новым `<li>` автоматически.
- Пустой чат (нет сообщений): заглушка «Сообщений пока нет».

- [ ] **Step 4: Визуальная сверка со скриншотом VK**

По памяти `web-admin-browser-testing`: три iframe 390px (список, чат, панель бота) и десктоп 1400px. Сравнить с образцом: колонка 340px, аватар 52px, имя синим, время справа, ✓✓ синие, чип даты залипает сверху, стикер 168px, голосовое с плеером и расшифровкой. Расхождения править в `im.css` до совпадения по ритму и пропорциям; сделать скриншоты и сохранить в scratchpad для отчёта пользователю.

- [ ] **Step 5: Тесты**

Run: `.venv/bin/pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add web/im web/templates web/static tests/web/test_im_pages.py
git commit -m "messenger: mobile layout, series continuity across polls, read-without-marking toggle"
```

---

### Task 13: Документация и деплой

**Files:**
- Modify: `CLAUDE.md`, `AGENTS.md`, `README.md`, `.env.example`

- [ ] **Step 1: CLAUDE.md и AGENTS.md (правило 1 — изменилась граница модуля `web/`)**

В описании `web/` заменить «в VK/LLM ходит только из песочницы и удаления ответа» на: «в VK ходит из песочницы, удаления ответа и мессенджера `/im` (`web/im/`: чтение диалогов и истории, отправка текста и голосовых, отметка прочитанного, участники беседы), в LLM — из песочницы и черновика мессенджера». Добавить строку модуля:

```
- `web/im/` — мессенджер: `views.py` превращает ответы VK в неизменяемые view-модели (шаблоны знают только их),
  `modes.py` — режим бота для чата (та же логика, что `limits.should_reply` + пауза), `controls.py` — чистые правки
  `access.json`/`runtime.json` из чата (чужие записи `"@nick"` сохраняются), `voice.py` — проверка `.ogg`/`.mp3`
  по сигнатуре, `draft.py` — черновик ответа через `reply.generate_reply`. Ничего из VK не пишется на диск.
```

Тот же текст — в `AGENTS.md` (правило 2). Ничего больше в этих файлах не менять.

- [ ] **Step 2: README и `.env.example`**

README: раздел «Мессенджер» — что умеет, что не умеет (стикеры, эмодзи, поиск по сообщениям), про голосовые (`.ogg` Opus или `.mp3`, до 20 МБ; mp3 перекодируется в Opus через `ffmpeg`, локально `brew install ffmpeg`), про то, что переключатели в чате пишут в `config/`. `.env.example`: `# WEB_TIMEZONE=Europe/Moscow` с подписью «зона для чипов дат в мессенджере».

- [ ] **Step 3: Прогон всего**

Run: `.venv/bin/pytest -q && .venv/bin/python -c "import evals.run; print('evals import ok')"`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md AGENTS.md README.md .env.example
git commit -m "document the messenger page"
```

- [ ] **Step 5: Деплой (по памяти `prod-server-layout`)**

```bash
git bundle create /tmp/im.bundle <lastProdSha>..main
scp /tmp/im.bundle root@SERVER_IP:/root/
ssh root@SERVER_IP 'cd /root/vk_mcp && git pull --ff-only /root/im.bundle main && docker compose up -d --build'
```

Проверить `https://<WEB_DOMAIN>/im` с телефона и ноутбука; `docker logs --since 10m vk_mcp-web-1` без ошибок; бот (`vk_mcp-bot-1`) продолжает отвечать.

---

## Self-review (выполнен при написании плана)

- **Покрытие дизайна:** список и чат — Task 6; поллинг и подгрузка — Task 7; отправка/цитата/прочитано/удаление — Task 8; голосовые — Task 9; режим и управление ботом в чате, участники — Task 4, 5, 10; черновик — Task 11; мобильный, полировка — Task 12; документация и инвариант CLAUDE.md — Task 13; фикстуры и проверка форм VK — Task 0.
- **Не вошло намеренно:** стикеры и эмодзи-пикер, отправка фото, поиск по сообщениям, `getLongPollHistory`, кастомный плеер с волной.
- **Открытые допущения для Актана:** (1) «1 в 1» = раскладка и ритм VK, не пиксельная копия; (2) отметка «прочитано» при открытии чата включена по умолчанию, отключается в панели; (3) мессенджер — часть админки под тем же Basic Auth и Caddy, отдельного входа нет; (4) поллинг вместо long poll в `web` — до появления проблем с лимитами; (5) `.mp3` всегда перекодируется в Ogg Opus через `ffmpeg` (в образе `web` и локально).
