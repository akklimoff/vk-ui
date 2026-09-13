# VK-look redesign of `/im` — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** make the messenger page `/im` look and behave like vk.com/im (no-bubbles mode) in light and dark themes, with a VK shell, a custom voice player, a photo viewer and the chat details described in the spec.

**Architecture:** the routes, htmx contracts and element ids stay; the templates, `im.css` and `im.js` are rewritten around a set of `--vk-*` tokens scoped to `body.page-im`; VK icons are vendored as an SVG sprite and used through a Jinja macro; the view models gain `waveform`, `last_seen`/`sex`, an `unread` row flag and a few pure helpers (`presence`, `wave_bars`, `short_since`).

**Tech Stack:** FastAPI + Jinja2, htmx 2, Alpine.js 3, Pico.css (still loaded, overridden inside `.page-im`), `@vkontakte/icons` 3.70.0 SVGs (MIT), pytest, Playwright MCP for visual checks.

**Spec:** `docs/superpowers/specs/2026-09-14-vk-im-redesign-design.md` — every size, colour and token value comes from there; when this plan and the spec disagree, the spec wins.

## Global Constraints

- Work on branch `vk-im-look` off `main` (7e26b3c). One-line English imperative commit messages, no LLM attribution of any kind.
- Code comments only for a non-visible "why"; no section headers, no restating the line.
- Nothing from VK is written to disk; message text never goes into logs, `state/` or query strings.
- Never send anything to real VK from tests or demos; tests use `FakeVk` from `tests/web/test_im_pages.py`.
- Tokens (light | dark) exactly as in the spec table; font stack `-apple-system, BlinkMacSystemFont, "Roboto", "Helvetica Neue", Geneva, arial, Tahoma, verdana, sans-serif`; base text 13px/18px.
- Element ids/classes relied on by JS and tests stay: `#messages`, `#chat-poll`, `#chat-state`, `#composer-error`, `#bot-slot`, `#bot-panel`, `#chat-badge`, `#dialog-list`, `#chat`, `.dlg`, `.msg`, `.head`, `.out`, `.im-day`, `.im-more`, `.im-empty`, `data-id/from/ts`, `class="msg {head} {out}"` spacing.
- Other admin pages keep their Pico look and the `.topnav`; only `/im` gets the VK shell.
- Icons: only names present in `@vkontakte/icons` 3.70.0; the sprite keeps the MIT notice.
- Test command: `.venv/bin/pytest -q`. Suite must stay green after every task.
- Scratchpad (session-only, not in repo): `$S=/private/tmp/claude-501/-Users-aklimoff-Documents-ComputerScience-PetProjects-vk-mcp/573544de-11b8-45da-bebe-b5834be340a6/scratchpad`; VK icon sources at `$S/vk-ref/icons/package/src/svg/<size>/<name>.svg`; demo server `$S/im_demo.py`.

---

## File map

| File | Responsibility |
|---|---|
| `web/static/vk-icons.svg` (new) | sprite of `<symbol>`s from `@vkontakte/icons`, MIT notice in a leading comment |
| `web/templates/partials/im_icons.html` (new) | macro `icon(name, cls='')` → `<svg class="ico …" width height><use href="/static/vk-icons.svg#name"/></svg>` |
| `web/render.py` | `NavItem`, `NAV`, Jinja global `nav` |
| `web/templates/base.html` | `{% block body_class %}`, `{% block nav %}` (default `.topnav` from `nav`) |
| `web/templates/im.html` | page wrapper: `page-im` body class, `im_shell.html` in the nav block |
| `web/templates/partials/im_shell.html` (new) | VK header 48 + left nav 164 + mobile drawer |
| `web/templates/partials/im.html` | card: dialog list side + `#chat` + empty-state template |
| `web/templates/partials/im_empty.html` (new) | «Выберите чат» |
| `web/templates/partials/im_dialogs.html` | `<li class="dlg">` rows |
| `web/templates/partials/im_chat.html` | chat header, history wrapper, scroll-down, composer, viewer, panel slot |
| `web/templates/partials/im_rows.html` | message rows, day chip, unread separator, attachments |
| `web/templates/partials/im_voice.html` (new) | voice player markup with server-rendered wave |
| `web/templates/partials/im_bot.html` | bot side panel |
| `web/templates/partials/im_badge.html` | unchanged markup, restyled |
| `web/static/im.css` | rewritten: tokens, shell, list, chat, composer, player, viewer, panel, mobile |
| `web/static/im.js` | `im` (+close/drawer), `chat` (+atBottom/pending/stuck/viewer), `composer` (+ready), `voice`, `readMark` |
| `web/im/views.py` | `Attachment.waveform`, `wave_bars`, `Peer.last_seen/sex`, `Profiles.last_seen/sex`, `presence`, `Row.unread`, `rows(in_read=)` |
| `web/humanize.py` | `MONTHS_SHORT`, `short_since` |
| `web/app.py` | filters `since`, `presence`, `wave_bars` |
| `web/im/routes.py` | `now` in contexts, `in_read` on chat open |
| `bot/vk.py` | `PROFILE_FIELDS` + `last_seen` |
| tests | `tests/web/test_vk_icons.py` (new), `test_im_views.py`, `test_humanize.py`, `test_im_pages.py`, `test_im_bot.py`, `tests/test_vk.py`, `im_fixtures.py` |

---

### Task 0: Branch and icon sprite

**Files:**
- Create: `web/static/vk-icons.svg`, `web/templates/partials/im_icons.html`, `tests/web/test_vk_icons.py`
- Build script (scratchpad only, not committed): `$S/build_sprite.py`

**Interfaces:**
- Produces: Jinja macro `icon(name, cls='')` (import with `{% from "partials/im_icons.html" import icon %}`); sprite symbols listed below; test that every `icon('…')` in templates and every `NAV` icon exists in the sprite.

- [ ] **Step 1: Create the branch**

```bash
git checkout -q main && git checkout -q -b vk-im-look
```

- [ ] **Step 2: Write the failing sprite test**

`tests/web/test_vk_icons.py`:

```python
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web"


def used_icons() -> set[str]:
    used = set()
    for path in (WEB / "templates").rglob("*.html"):
        text = path.read_text()
        used |= set(re.findall(r"""icon\(['"]([a-z0-9_]+)['"]""", text))
        used |= set(re.findall(r"vk-icons\.svg#([a-z0-9_]+)", text))
    return used


def test_every_icon_used_in_templates_is_in_the_sprite():
    from web.render import NAV
    sprite = (WEB / "static" / "vk-icons.svg").read_text()
    have = set(re.findall(r'<symbol id="([a-z0-9_]+)"', sprite))
    used = used_icons() | {item.icon for item in NAV}
    assert used and used <= have, used - have


def test_sprite_keeps_the_mit_notice_and_uses_current_color():
    sprite = (WEB / "static" / "vk-icons.svg").read_text()
    assert "MIT" in sprite and "VK LLC" in sprite
    assert 'fill="currentColor"' in sprite and "#000" not in sprite
```

- [ ] **Step 3: Run it to see it fail**

Run: `.venv/bin/pytest -q tests/web/test_vk_icons.py`
Expected: FAIL — `web/static/vk-icons.svg` missing (and `NAV` not importable until Task 2; that is fine, the sprite test is completed in Task 2's run).

- [ ] **Step 4: Build the sprite**

`$S/build_sprite.py`:

```python
import pathlib
import re
import sys

SRC = pathlib.Path(sys.argv[1])
OUT = pathlib.Path("web/static/vk-icons.svg")
NAMES = """message_outline_20 pulse_outline_20 users_outline_20 text_outline_20 key_outline_20 gear_outline_20
reply_outline_20 robot_outline_20 cancel_20
cancel_24 chevron_left_24 logo_vk_outline_24 robot_outline_24 reply_24 delete_outline_24 add_circle_outline_24
magic_wand_outline_24 send_24 chevron_down_24 document_outline_24 menu_outline_24
mute_cross_16 pin_16 check_outline_16 check_double_outline_16 search_outline_16 cancel_16 message_forward_outline_16
play_circle_32 pause_circle_32 messages_outline_56""".split()

parts = ['<svg xmlns="http://www.w3.org/2000/svg" style="display:none">',
         "<!-- @vkontakte/icons 3.70.0 — MIT License, Copyright (c) 2017-present, VK LLC -->"]
for name in NAMES:
    size = name.rsplit("_", 1)[1]
    svg = (SRC / size / f"{name}.svg").read_text()
    assert "url(#" not in svg and "<mask" not in svg, name
    inner = re.search(r"<svg[^>]*>(.*)</svg>", svg, re.S).group(1)
    inner = re.sub(r"<!--.*?-->|<title>.*?</title>|<desc>.*?</desc>", "", inner, flags=re.S)
    inner = re.sub(r'<rect id="Shape" opacity="0.4"[^>]*></rect>', "", inner)
    inner = re.sub(r' id="[^"]*"', "", inner)
    inner = re.sub(r"\s+", " ", inner).replace("> <", "><").strip()
    parts.append(f'<symbol id="{name}" viewBox="0 0 {size} {size}">{inner}</symbol>')
parts.append("</svg>")
OUT.write_text("\n".join(parts) + "\n")
print(len(NAMES), "symbols", OUT.stat().st_size, "bytes")
```

Run: `.venv/bin/python $S/build_sprite.py $S/vk-ref/icons/package/src/svg`
Expected: `31 symbols … bytes`; `grep -c '<symbol' web/static/vk-icons.svg` → 31; `grep -c 'fill="currentColor"' web/static/vk-icons.svg` ≥ 31.

- [ ] **Step 5: Write the macro**

`web/templates/partials/im_icons.html`:

```jinja
{% macro icon(name, cls='') %}{% set size = name.rsplit('_', 1)[1] %}<svg class="ico{{ ' ' ~ cls if cls }}" width="{{ size }}" height="{{ size }}" aria-hidden="true"><use href="/static/vk-icons.svg#{{ name }}"/></svg>{% endmacro %}
```

- [ ] **Step 6: Run the second sprite test**

Run: `.venv/bin/pytest -q tests/web/test_vk_icons.py::test_sprite_keeps_the_mit_notice_and_uses_current_color`
Expected: PASS (the first test passes after Task 2 adds `NAV`).

- [ ] **Step 7: Commit**

```bash
git add web/static/vk-icons.svg web/templates/partials/im_icons.html tests/web/test_vk_icons.py
git commit -m "vendor VK icons as an SVG sprite"
```

---

### Task 1: View-model fields and helpers

**Files:**
- Modify: `web/im/views.py`, `web/humanize.py`, `bot/vk.py:8`, `web/app.py:35-36`, `web/im/routes.py:49-70`, `tests/web/im_fixtures.py:26`
- Test: `tests/web/test_im_views.py`, `tests/web/test_humanize.py`, `tests/test_vk.py`

**Interfaces:**
- Produces: `Attachment.waveform: tuple[int, ...]`; `wave_bars(waveform, duration) -> tuple[int, ...]` (bar heights, px, 2…12); `Peer.last_seen: float`, `Peer.sex: int`; `presence(peer, now, tz) -> str`; `Row.unread: bool`; `rows(messages, now, tz, prev=None, in_read=None)`; `short_since(ts, now, tz) -> str`; Jinja filters `since(ts, now, tz)`, `presence(peer, now, tz)`, `wave_bars(waveform, duration)`; contexts from `dialogs_ctx` and `chat_ctx` carry `now`.

- [ ] **Step 1: Failing view tests**

Append to `tests/web/test_im_views.py` (extend the import line with `Peer, presence, wave_bars`):

```python
def test_attachment_of_keeps_voice_waveform():
    att = attachment_of(HISTORY["items"][2]["attachments"][0])
    assert att.waveform == (1, 5, 9)
    assert attachment_of({"type": "audio_message", "audio_message": {"duration": 3}}).waveform == ()


def test_wave_bars_follow_vk_sizing():
    assert wave_bars((), 1) == (2,) * 22                      # секунда — 22 столбика, пустая волна — плоская
    assert len(wave_bars((31,) * 128, 60)) == 80             # не длиннее 80
    assert wave_bars((31,), 1) == (12,) * 22                  # максимум 12px
    bars = wave_bars((1, 5, 9), 20)
    assert len(bars) == 60 and bars[:20] == (2,) * 20 and bars[-20:] == (3,) * 20


def test_peer_of_reads_last_seen_and_sex_for_users():
    chat, user = parse_conversations(CONVERSATIONS, ME)
    assert user.peer.last_seen == 1783059300 and user.peer.sex == 1
    assert chat.peer.last_seen == 0 and chat.peer.sex == 0


def test_presence():
    now = datetime(2026, 9, 8, 18, 0, tzinfo=TZ).timestamp()
    assert presence(Peer(1, "x", online=True), now, TZ) == "онлайн"
    assert presence(Peer(1, "x"), now, TZ) == ""
    assert presence(Peer(1, "x", sex=1, last_seen=now - 30), now, TZ) == "была в сети только что"
    assert presence(Peer(1, "x", sex=1, last_seen=now - 300), now, TZ) == "была в сети 5 мин назад"
    assert presence(Peer(1, "x", sex=2, last_seen=now - 7200), now, TZ) == "был в сети сегодня в 16:00"
    assert presence(Peer(1, "x", sex=2, last_seen=now - 86400), now, TZ) == "был в сети вчера в 18:00"
    july = datetime(2026, 7, 3, 9, 15, tzinfo=TZ).timestamp()
    assert presence(Peer(1, "x", last_seen=july), now, TZ) == "был(а) в сети 3 июля в 09:15"


def test_rows_mark_first_unread_incoming_message():
    messages, _ = parse_history(HISTORY, ME)
    now = datetime(2026, 9, 8, 18, 0, tzinfo=TZ).timestamp()
    assert [r.unread for r in rows(messages, now, TZ, in_read=500)] == [False, False, False, True]
    assert not any(r.unread for r in rows(messages, now, TZ))
    assert not any(r.unread for r in rows(messages, now, TZ, in_read=502))
```

Fixture change in `tests/web/im_fixtures.py` — profile 22 becomes:

```python
        {"id": 22, "first_name": "Аня", "last_name": "Иванова", "photo_50": "https://cdn.example/u22.jpg", "online": 0,
         "sex": 1, "last_seen": {"platform": 7, "time": 1783059300}},
```

- [ ] **Step 2: Failing humanize and vk tests**

Append to `tests/web/test_humanize.py` (add `short_since` to the import):

```python
def test_short_since():
    tz = ZoneInfo("Europe/Moscow")
    now = 1788876240
    assert short_since(now - 30, now, tz) == "1м"
    assert short_since(now - 300, now, tz) == "5м"
    assert short_since(now - 3 * 3600, now, tz) == "3ч"
    assert short_since(now - 5 * 86400, now, tz) == "5д"
    assert short_since(1786525200, now, tz) == "12 авг"
```

Append to `tests/test_vk.py`:

```python
def test_profile_fields_include_last_seen():
    from bot.vk import PROFILE_FIELDS
    assert "last_seen" in PROFILE_FIELDS.split(",") and "sex" in PROFILE_FIELDS.split(",")
```

- [ ] **Step 3: Run them to see them fail**

Run: `.venv/bin/pytest -q tests/web/test_im_views.py tests/web/test_humanize.py tests/test_vk.py`
Expected: ImportError / AttributeError on `wave_bars`, `presence`, `short_since`, `waveform`, `last_seen`.

- [ ] **Step 4: Implement in `web/im/views.py`**

Dataclasses:

```python
@dataclass(frozen=True)
class Peer:
    id: int
    title: str
    photo: str = ""
    kind: str = "user"
    online: bool = False
    members: int = 0
    last_seen: float = 0
    sex: int = 0


@dataclass(frozen=True)
class Attachment:
    kind: str
    url: str = ""
    preview: str = ""
    title: str = ""
    duration: int = 0
    transcript: str = ""
    waveform: tuple[int, ...] = ()


@dataclass(frozen=True)
class Row:
    message: Message
    day: str | None
    head: bool
    unread: bool = False
```

`Profiles` gets:

```python
    def last_seen(self, uid: int) -> float:
        return float(((self._users.get(uid) or {}).get("last_seen") or {}).get("time", 0))

    def sex(self, uid: int) -> int:
        return int((self._users.get(uid) or {}).get("sex", 0))
```

`attachment_of`, the `audio_message` branch:

```python
    if kind == "audio_message":
        done = body.get("transcript_state") == "done"
        return Attachment("voice", url=body.get("link_mp3") or body.get("link_ogg", ""),
                          duration=int(body.get("duration", 0)),
                          transcript=body.get("transcript", "") if done else "",
                          waveform=tuple(int(v) for v in body.get("waveform") or ()))
```

`peer_of`, the user/group return:

```python
    if pid < 0:
        return Peer(pid, profiles.name(pid), profiles.photo(pid), "group")
    return Peer(pid, profiles.name(pid), profiles.photo(pid), "user", profiles.online(pid),
                last_seen=profiles.last_seen(pid), sex=profiles.sex(pid))
```

New helpers (after `day_label`):

```python
WAVE_HEIGHT = 12
WAVE_MAX = 31


def wave_bars(waveform: tuple[int, ...], duration: int) -> tuple[int, ...]:
    """Столбики как у VK: секундное сообщение — 22, длиннее 80 не бывает; значения VK 0…31."""
    n = max(21, min(80, round(duration * 2) + 20))
    if not waveform:
        return (2,) * n
    bars = []
    for i in range(n):
        lo = i * len(waveform) // n
        hi = max((i + 1) * len(waveform) // n, lo + 1)
        chunk = waveform[lo:hi]
        bars.append(max(2, round(sum(chunk) / len(chunk) / WAVE_MAX * WAVE_HEIGHT)))
    return tuple(bars)


def presence(peer: Peer, now: float, tz: ZoneInfo) -> str:
    if peer.online:
        return "онлайн"
    if not peer.last_seen:
        return ""
    was = {1: "была в сети", 2: "был в сети"}.get(peer.sex, "был(а) в сети")
    ago = now - peer.last_seen
    if ago < 60:
        return f"{was} только что"
    if ago < 3600:
        return f"{was} {int(ago // 60)} мин назад"
    at = datetime.fromtimestamp(peer.last_seen, tz)
    return f"{was} {day_label(peer.last_seen, now, tz)} в {at:%H:%M}"
```

`rows`:

```python
def rows(messages: list[Message], now: float, tz: ZoneInfo, prev: Message | None = None,
         in_read: int | None = None) -> list[Row]:
    """prev — последнее уже отрисованное сообщение: с ним склеивается серия и день первого нового.
    in_read — последнее прочитанное входящее: перед первым входящим новее него встаёт разделитель."""
    result: list[Row] = []
    prev_day = day_label(prev.ts, now, tz) if prev else None
    unread_pending = in_read is not None
    for m in messages:
        day = day_label(m.ts, now, tz)
        new_day = day != prev_day
        head = new_day or prev is None or prev.from_id != m.from_id or m.ts - prev.ts > SERIES_GAP or bool(prev.action)
        unread = unread_pending and not m.out and m.id > in_read
        unread_pending = unread_pending and not unread
        result.append(Row(m, day if new_day else None, head or bool(m.action), unread))
        prev, prev_day = m, day
    return result
```

- [ ] **Step 5: Implement `short_since` in `web/humanize.py`**

```python
MONTHS_SHORT = ("янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")


def short_since(ts: float, now: float, tz) -> str:
    ago = max(0.0, now - ts)
    if ago < 3600:
        return f"{max(1, int(ago // 60))}м"
    if ago < 86400:
        return f"{int(ago // 3600)}ч"
    if ago < 7 * 86400:
        return f"{int(ago // 86400)}д"
    at = datetime.fromtimestamp(ts, tz)
    return f"{at.day} {MONTHS_SHORT[at.month - 1]}"
```

- [ ] **Step 6: `PROFILE_FIELDS`, filters, contexts**

`bot/vk.py:8`: `PROFILE_FIELDS = "photo_50,photo_100,online,last_seen,sex,screen_name"`

`web/app.py`: import `short_since` from `web.humanize` and `presence, wave_bars` from `web.im.views`; the Renderer call becomes

```python
    render = Renderer(os.path.join(HERE, "templates"), peer_label=peer_label, peer_link=peer_link,
                      model_label=model_label, clock=clock, mmss=mmss, plural=plural, preview=preview,
                      since=short_since, presence=presence, wave_bars=wave_bars)
```

`web/im/routes.py`:

```python
    def dialogs_ctx():
        access, rt = lists(), runtime()
        dialogs = parse_conversations(vk().conversations(DIALOGS), vk().me_id, marks())
        return {"dialogs": [(d, bot_mode(d.peer.id, access, rt)) for d in dialogs], "tz": tz, "now": time.time()}
```

```python
    def chat_ctx(peer_id: int, before: int | None = None, after: int | None = None, prev: Message | None = None):
        count = POLL_WINDOW if after else PAGE
        raw = vk().history_page(peer_id, count, before_id=before)
        messages, out_read = parse_history(raw, vk().me_id, marks())
        full_page = len(messages) >= count
        if after:
            messages = [m for m in messages if m.id > after]
        convs = raw.get("conversations") or []
        peer = peer_of(convs[0], Profiles(raw)) if convs else None
        opening = convs and not after and not before and convs[0].get("unread_count")
        in_read = int(convs[0].get("in_read", 0)) if opening else None
        now = time.time()
        return {"peer": peer, "peer_id": peer_id, "rows": rows(messages, now, tz, prev, in_read),
                "out_read": out_read, "oldest": messages[0].id if messages and full_page else None,
                "mode": bot_mode(peer_id, lists(), runtime()), "tz": tz, "now": now, "page": "im"}
```

- [ ] **Step 7: Run the whole suite**

Run: `.venv/bin/pytest -q`
Expected: all pass (310 + 6 new).

- [ ] **Step 8: Commit**

```bash
git add web/im/views.py web/humanize.py bot/vk.py web/app.py web/im/routes.py tests/web/im_fixtures.py tests/web/test_im_views.py tests/web/test_humanize.py tests/test_vk.py
git commit -m "add presence, waveform bars and unread marker to messenger view models"
```

---

### Task 2: VK shell and the full stylesheet

**Files:**
- Modify: `web/render.py`, `web/templates/base.html`, `web/templates/im.html`
- Create: `web/templates/partials/im_shell.html`
- Rewrite: `web/static/im.css`
- Test: `tests/web/test_im_pages.py`, `tests/web/test_vk_icons.py`

**Interfaces:**
- Produces: `web.render.NAV` (tuple of `NavItem(href, title, key, icon)`), Jinja global `nav`; body class `page-im`; CSS classes used by later tasks: `.ico .ib .ava .a48 .a36 .a32 .dot .badge-mode .sw .vk-btn` plus every section-specific class named in the templates of Tasks 3–7 (the stylesheet is written once here, in full).

- [ ] **Step 1: Failing page test**

Append to `tests/web/test_im_pages.py`:

```python
def test_im_page_wears_the_vk_shell(client):
    r = client.get("/im", auth=AUTH)
    assert 'class="page-im"' in r.text
    nav = r.text.split('class="vk-nav"')[1].split("</nav>")[0]
    assert 'aria-current="page"' in nav.split("Мессенджер")[0]
    assert "vk-icons.svg#message_outline_20" in nav and "vk-icons.svg#robot_outline_20" in nav
    assert 'class="topnav"' not in r.text


def test_other_pages_keep_the_plain_nav(client):
    r = client.get("/", auth=AUTH)
    assert 'class="topnav"' in r.text and "vk-nav" not in r.text and 'href="/im"' in r.text
```

- [ ] **Step 2: Run to see it fail**

Run: `.venv/bin/pytest -q tests/web/test_im_pages.py -k "shell or plain_nav"`
Expected: FAIL (`page-im` absent).

- [ ] **Step 3: `NAV` in `web/render.py`**

Add after the imports:

```python
class NavItem(NamedTuple):
    href: str
    title: str
    key: str
    icon: str


NAV = (
    NavItem("/im", "Мессенджер", "im", "message_outline_20"),
    NavItem("/", "Статус", "status", "pulse_outline_20"),
    NavItem("/personas", "Персоны", "personas", "users_outline_20"),
    NavItem("/prompts", "Промпт", "prompts", "text_outline_20"),
    NavItem("/access", "Доступ", "access", "key_outline_20"),
    NavItem("/settings", "Настройки", "settings", "gear_outline_20"),
    NavItem("/replies", "Ответы", "replies", "reply_outline_20"),
    NavItem("/sandbox", "Песочница", "sandbox", "robot_outline_20"),
)
```

(`from typing import NamedTuple`.) In `Renderer.__init__` after the filters line: `self._templates.env.globals["nav"] = NAV`.

- [ ] **Step 4: `base.html`**

Replace `<body>` … `</nav>` with:

```html
<body class="{% block body_class %}{% endblock %}">
{% block nav %}<nav class="topnav" aria-label="Разделы">
  <ul>{% for item in nav %}
    <li><a href="{{ item.href }}" {% if page == item.key %}aria-current="page"{% endif %}>{{ item.title }}</a></li>{% endfor %}
  </ul>
</nav>{% endblock %}
```

- [ ] **Step 5: `im.html` and `im_shell.html`**

`web/templates/im.html`:

```jinja
{% extends "base.html" %}
{% block body_class %}page-im{% endblock %}
{% block main_class %}im-shell{% endblock %}
{% block nav %}{% include "partials/im_shell.html" %}{% endblock %}
{% block body %}{% include "partials/im.html" %}{% endblock %}
```

`web/templates/partials/im_shell.html`:

```jinja
{% from "partials/im_icons.html" import icon %}
<div class="vk-shell" x-data="{ drawer: false }" @keydown.escape.window="drawer = false">
  <header class="vk-header">
    <button type="button" class="ib vk-burger" aria-label="Меню" @click="drawer = !drawer">{{ icon('menu_outline_24') }}</button>
    <a class="vk-logo" href="/"><span class="vk-logo-mark">{{ icon('robot_outline_20') }}</span>vk-bot</a>
  </header>
  <div class="vk-scrim" x-show="drawer" x-cloak @click="drawer = false"></div>
  <nav class="vk-nav" :class="{ open: drawer }" aria-label="Разделы">
    <ul>{% for item in nav %}
      <li><a href="{{ item.href }}" {% if page == item.key %}aria-current="page"{% endif %}>{{ icon(item.icon) }}{{ item.title }}</a></li>{% endfor %}
    </ul>
  </nav>
</div>
```

- [ ] **Step 6: Rewrite `web/static/im.css`**

The whole file (sections for later tasks included — templates catch up in Tasks 3–7):

```css
/* Токены vkBase (@vkontakte/vkui-tokens 4.92), значения сняты с vk.com/im 2026-09-14 */
body.page-im {
  --vk-bg: #edeef0; --vk-content: #fff; --vk-secondary: #f0f2f5; --vk-modal: #fff; --vk-header: #fff; --vk-search: #edeef0;
  --vk-text: #000; --vk-text-2: #818c99; --vk-subhead: #626d7a; --vk-text-3: #99a2ad; --vk-link: #2a5885; --vk-accent: #447bba;
  --vk-icon: #6f7985; --vk-icon-2: #99a2ad; --vk-icon-3: #aeb7c2; --vk-sep: #dce1e6; --vk-sep-2: #e7e8ec;
  --vk-hover: rgba(0,0,0,.04); --vk-active: rgba(0,0,0,.08); --vk-row-hover: rgba(0,16,61,.02); --vk-forward-line: rgba(0,20,51,.12);
  --vk-green: #4bb34b; --vk-red: #e64646;
  --vk-shadow-2: 0 4px 8px rgba(0,0,0,.04), 0 0 4px rgba(0,0,0,.06);
  --vk-shadow-3: 0 0 2px rgba(0,0,0,.08), 0 4px 16px rgba(0,0,0,.08);
  --vk-shadow-pill: 0 8px 24px rgba(0,0,0,.08), 0 0 2px rgba(0,0,0,.08);
}
@media (prefers-color-scheme: dark) {
  body.page-im {
    --vk-bg: #141414; --vk-content: #222; --vk-secondary: #333; --vk-modal: #292929; --vk-header: #222; --vk-search: #424242;
    --vk-text: #e1e3e6; --vk-text-2: #828282; --vk-subhead: #939393; --vk-text-3: #656565; --vk-link: #71aaeb; --vk-accent: #71aaeb;
    --vk-icon: #939393; --vk-icon-2: #828282; --vk-icon-3: #656565; --vk-sep: #363738; --vk-sep-2: #292929;
    --vk-hover: rgba(255,255,255,.04); --vk-active: rgba(255,255,255,.08); --vk-row-hover: rgba(255,255,255,.02); --vk-forward-line: rgba(255,255,255,.24);
    --vk-red: #ff5c5c;
    --vk-shadow-2: 0 4px 8px rgba(0,0,0,.15), 0 0 4px rgba(0,0,0,.2);
    --vk-shadow-3: 0 0 2px rgba(0,0,0,.3), 0 4px 16px rgba(0,0,0,.3);
  }
}

body.page-im {
  margin: 0; min-height: 100vh; display: grid; column-gap: 16px;
  grid-template-columns: minmax(16px, 1fr) 164px minmax(0, 912px) minmax(16px, 1fr); grid-template-rows: 48px 1fr;
  background: var(--vk-bg); color: var(--vk-text);
  font-family: -apple-system, BlinkMacSystemFont, "Roboto", "Helvetica Neue", Geneva, arial, Tahoma, verdana, sans-serif;
  font-size: 13px; line-height: 18px;
}
.page-im a { color: var(--vk-link); text-decoration: none; }
.page-im p { margin: 0; }
.page-im .ico { display: inline-block; flex: 0 0 auto; fill: currentColor; vertical-align: middle; }
.page-im .ib { display: inline-grid; place-items: center; width: 32px; height: 32px; padding: 0; margin: 0; border: 0; border-radius: 6px;
  background: none; color: var(--vk-icon-2); box-shadow: none; cursor: pointer; text-decoration: none; }
.page-im .ib:hover { background: var(--vk-hover); }
.page-im .ib:focus-visible { outline: 2px solid var(--vk-accent); }

.vk-shell { display: contents; }
.vk-header { grid-column: 1 / -1; position: sticky; top: 0; z-index: 20; display: flex; align-items: center; gap: 8px; height: 48px;
  padding: 0 max(32px, calc((100% - 1092px) / 2)); background: var(--vk-header); border-bottom: 1px solid var(--vk-sep); }
.vk-logo { display: flex; align-items: center; gap: 8px; color: var(--vk-text); font-size: 15px; font-weight: 600; }
.vk-logo-mark { display: grid; place-items: center; width: 28px; height: 28px; border-radius: 8px; background: var(--vk-accent); color: #fff; }
.vk-burger { display: none; color: var(--vk-icon); }
.vk-scrim { position: fixed; inset: 0; z-index: 25; background: rgba(0,0,0,.4); }
.vk-nav { grid-column: 2; grid-row: 2; align-self: start; position: sticky; top: 64px; margin-top: 16px; }
.vk-nav ul { display: flex; flex-direction: column; margin: 0; padding: 0; list-style: none; }
.vk-nav li { margin: 0; padding: 0; }
.vk-nav a { display: flex; align-items: center; gap: 10px; height: 30px; padding: 0 6px; border-radius: 4px; color: var(--vk-text); font-size: 13px; line-height: 16px; }
.vk-nav a .ico { color: var(--vk-accent); }
.vk-nav a:hover { background: var(--vk-hover); }
.vk-nav a[aria-current] { background: var(--vk-active); }
main.im-shell { grid-column: 3; grid-row: 2; margin: 16px 0; padding: 0; max-width: none; min-width: 0; }
.im { display: grid; grid-template-columns: 319px minmax(0, 1fr); height: calc(100vh - 80px); background: var(--vk-content); border-radius: 12px; overflow: hidden; }

.ava { position: relative; display: inline-grid; place-items: center; flex: 0 0 auto; border-radius: 50%; background: var(--vk-secondary);
  color: var(--vk-subhead); font-weight: 500; overflow: visible; }
.ava img { width: 100%; height: 100%; border-radius: 50%; object-fit: cover; }
.ava i { font-style: normal; }
.a48 { width: 48px; height: 48px; font-size: 17px; }
.a36 { width: 36px; height: 36px; font-size: 14px; }
.a32 { width: 32px; height: 32px; font-size: 13px; }
.ava .dot { position: absolute; right: 0; bottom: 0; width: 8px; height: 8px; border-radius: 50%; background: var(--vk-green); box-shadow: 0 0 0 2px var(--vk-content); }
.ava.robot { color: var(--vk-accent); }
.badge-mode { display: inline-block; padding: 1px 6px; border-radius: 4px; background: var(--vk-secondary); color: var(--vk-subhead);
  font-size: 11px; line-height: 14px; font-weight: 500; white-space: nowrap; }
.badge-mode.ok { background: rgba(75,179,75,.15); color: var(--vk-green); }
.badge-mode.bad { background: rgba(230,70,70,.12); color: var(--vk-red); }
.page-im input.sw { appearance: none; -webkit-appearance: none; position: relative; flex: 0 0 auto; width: 34px; height: 20px; margin: 0; border: 0;
  border-radius: 10px; background: var(--vk-icon-3); box-shadow: none; cursor: pointer; transition: background .15s; }
.page-im input.sw::before { content: ""; position: absolute; top: 2px; left: 2px; width: 16px; height: 16px; border-radius: 50%; background: #fff;
  box-shadow: 0 1px 2px rgba(0,0,0,.2); transition: transform .15s; }
.page-im input.sw:checked { background: var(--vk-accent); }
.page-im input.sw:checked::before { transform: translateX(14px); }
.vk-btn { width: auto; height: 36px; margin: 0; padding: 0 16px; border: 0; border-radius: 8px; background: var(--vk-accent); color: #fff;
  font-size: 14px; line-height: 18px; font-weight: 500; box-shadow: none; cursor: pointer; }

.im-side { display: flex; flex-direction: column; min-height: 0; border-right: 1px solid var(--vk-sep); }
.im-side-head { display: flex; align-items: center; min-height: 54px; padding: 8px; font-size: 15px; line-height: 20px; font-weight: 500; }
.im-search { position: relative; display: block; margin: 0 8px 8px; }
.im-search .ico { position: absolute; left: 12px; top: 8px; color: var(--vk-icon-2); pointer-events: none; }
.im-search input { width: 100%; height: 32px; margin: 0; padding: 0 8px 0 36px; border: 0; border-radius: 8px; background: var(--vk-search);
  color: var(--vk-text); font-size: 14px; line-height: 18px; box-shadow: none; }
.im-search input::placeholder { color: var(--vk-subhead); }
.im-search input:focus { outline: none; box-shadow: none; }
.im-dialogs { flex: 1; min-height: 0; overflow-y: auto; }
#dialog-list { margin: 0; padding: 0; list-style: none; }
.dlg { margin: 0; padding: 1px 8px; }
.dlg.pinned-last::after { content: ""; display: block; height: 1px; margin: 4px 0; background: var(--vk-sep); }
.dlg a { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; grid-template-rows: 1fr 1fr; gap: 2px 0; align-items: center;
  height: 60px; padding: 6px 12px; border-radius: 8px; color: inherit; }
.dlg a:hover { background: var(--vk-hover); }
.dlg.active a { background: var(--vk-active); }
.dlg .ava { grid-row: 1 / 3; margin-right: 12px; }
.dlg-head { display: flex; align-items: center; gap: 4px; min-width: 0; font-size: 13px; line-height: 16px; font-weight: 500; }
.dlg-head .title { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.dlg-head .mute { color: var(--vk-icon-3); }
.dlg-msg { min-width: 0; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; color: var(--vk-subhead); font-size: 13px; line-height: 18px; }
.dlg-msg .who { color: var(--vk-text-2); }
.dlg-msg .att { color: var(--vk-link); }
.dlg-msg .when { color: var(--vk-text-3); }
.dlg-icons { grid-row: 1 / 3; display: flex; align-items: center; gap: 4px; height: 22px; margin-left: 8px; color: var(--vk-icon-3); }
.dlg-icons .ticks { color: var(--vk-accent); }
.unread { display: inline-grid; place-items: center; min-width: 18px; height: 18px; padding: 0 5px; border-radius: 9px; background: var(--vk-accent);
  color: #fff; font-size: 12px; line-height: 14px; font-weight: 500; }
.unread.quiet { background: var(--vk-icon-2); }
.im-side-foot { display: flex; align-items: center; gap: 12px; height: 52px; margin: 0; padding: 0 20px; border-top: 1px solid var(--vk-sep);
  color: var(--vk-text); font-size: 14px; line-height: 18px; font-weight: 400; cursor: pointer; }
.im-side-foot .ico { color: var(--vk-icon-2); }
.im-side-foot span { flex: 1; }

.im-main { position: relative; display: flex; flex-direction: column; min-height: 0; min-width: 0; }
.im-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; height: 100%; color: var(--vk-text-2);
  font-size: 14px; line-height: 18px; }
.im-empty .ico { color: var(--vk-icon-2); }
.im-messages > .im-empty { height: auto; flex: 1; }
.im-chat { display: grid; grid-template-columns: minmax(0, 1fr); height: 100%; min-height: 0; }
.im-chat.with-panel { grid-template-columns: minmax(0, 1fr) 320px; }
.im-convo { display: flex; flex-direction: column; min-height: 0; min-width: 0; }
.im-chat-head { display: flex; align-items: center; gap: 8px; height: 56px; padding: 4px 8px; border-bottom: 1px solid var(--vk-sep); }
.im-chat-head .back { display: none; }
.im-chat-head .body { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.im-chat-head .line { display: flex; align-items: center; gap: 6px; min-width: 0; font-size: 13px; line-height: 16px; }
.im-chat-head .line b { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; font-weight: 500; }
.im-chat-head small { color: var(--vk-text-2); font-size: 13px; line-height: 16px; }
.im-history { position: relative; display: flex; flex-direction: column; flex: 1; min-height: 0; }
.im-messages { position: relative; display: flex; flex-direction: column; flex: 1; min-height: 0; overflow-y: auto; padding: 0 22px 8px; letter-spacing: -.007em; }
.im-messages > :first-child { margin-top: auto; }
.im-day { position: sticky; top: 0; z-index: 2; display: flex; justify-content: center; padding: 9px 0; }
.im-day span { padding: 3px 12px 5px; border-radius: 8px; background: var(--vk-content); color: var(--vk-subhead); font-size: 13px; line-height: 16px; letter-spacing: -.004em; }
.im-day.stuck span { background: var(--vk-modal); box-shadow: var(--vk-shadow-2); }
.im-unread { display: flex; align-items: center; gap: 1ch; padding: 14px 12px; color: var(--vk-text-3); font-size: 13px; line-height: 16px; }
.im-unread::before, .im-unread::after { content: ""; flex: 1; height: 1px; background: var(--vk-sep-2); }
.im-action { padding: 8px 0; text-align: center; color: var(--vk-subhead); font-size: 13px; line-height: 16px; }
.msg { position: relative; margin: 1px 0; padding: 8px 8px 8px 54px; border-radius: 12px; background: transparent; box-shadow: none; }
.msg:hover, .msg:focus-within { background: var(--vk-row-hover); z-index: 3; }
.msg > .ava { position: absolute; left: 8px; top: 8px; }
.msg .info { float: right; display: flex; align-items: center; gap: 2px; height: 14px; margin: 0 2px 0 12px; color: var(--vk-text-2); font-size: 11px; line-height: 11px; }
.msg .ticks { display: inline-flex; color: var(--vk-accent); }
.msg .ticks .two, .msg .ticks.read .one { display: none; }
.msg .ticks.read .two { display: inline-block; }
.msg .name { display: flex; align-items: baseline; gap: 6px; margin-bottom: 2px; font-size: 12.5px; line-height: 14px; font-weight: 600; }
.msg .text { max-width: 580px; white-space: pre-wrap; word-break: break-word; }
.msg .actions { position: absolute; top: -22px; right: -5px; z-index: 4; display: flex; height: 28px; overflow: hidden; border-radius: 20px;
  background: var(--vk-modal); box-shadow: var(--vk-shadow-pill); visibility: hidden; }
.msg:hover .actions, .msg:focus-within .actions { visibility: visible; }
.msg .actions button { display: grid; place-items: center; width: 28px; height: 28px; margin: 0; padding: 0; border: 0; border-radius: 0; background: none;
  color: var(--vk-icon-2); box-shadow: none; cursor: pointer; }
.msg .actions button:hover { background: var(--vk-secondary); }
@media (hover: none) { .msg .actions { visibility: visible; opacity: .85; } }
.quote { position: relative; display: flex; flex-direction: column; min-width: 128px; max-width: 580px; margin: 0 0 4px; padding: 4px 10px; border: 0;
  background: none; font-size: 13px; line-height: 18px; }
.quote::before { content: ""; position: absolute; left: 0; top: 6px; bottom: 6px; width: 2px; border-radius: 2px; background: var(--vk-accent); }
.quote b { margin-bottom: 2px; color: var(--vk-link); font-size: 12.5px; line-height: 14px; font-weight: 600; }
.quote span { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.msg .fwd { display: inline-flex; align-items: center; gap: 4px; color: var(--vk-text-2); }
.msg .photo { display: inline-block; margin: 2px 0; }
.msg .photo img { display: block; max-width: 320px; max-height: 320px; border-radius: 13px; }
.msg .sticker { display: block; width: 168px; height: 168px; }
.msg .video { display: flex; align-items: center; gap: 8px; }
.msg .video img { width: 120px; border-radius: 8px; }
.msg .doc { display: inline-flex; align-items: center; gap: 6px; }
.msg .doc .ico { color: var(--vk-accent); }

.voice { display: flex; flex-wrap: wrap; align-items: center; margin: 2px 0; }
.voice .play { display: grid; place-items: center; width: 32px; height: 32px; margin: 0 8px 0 0; padding: 0; border: 0; background: none;
  color: var(--vk-accent); box-shadow: none; cursor: pointer; }
.wave-col { display: flex; flex-direction: column; gap: 2px; }
.wave { display: block; color: var(--vk-accent); fill: currentColor; cursor: pointer; }
.wave .base { opacity: .4; }
.voice .dur { color: var(--vk-accent); font-size: 11px; line-height: 14px; }
.voice .aa { width: 32px; height: 20px; margin: 0 0 0 8px; padding: 0; border: 0; border-radius: 8px; background: var(--vk-secondary); color: var(--vk-accent);
  font-size: 12px; line-height: 20px; font-weight: 500; box-shadow: none; cursor: pointer; }
.voice .transcript { position: relative; flex-basis: 100%; margin: 8px 0 0; padding-left: 12px; }
.voice .transcript::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 2px; border-radius: 2px; background: var(--vk-link); opacity: .24; }

.im-down { position: absolute; right: 16px; bottom: 12px; z-index: 5; display: grid; place-items: center; width: 40px; height: 40px; margin: 0; padding: 0; border: 0;
  border-radius: 50%; background: var(--vk-modal); color: var(--vk-icon-2); box-shadow: var(--vk-shadow-2); cursor: pointer; }
.im-down b { position: absolute; top: -6px; right: -6px; min-width: 18px; height: 18px; padding: 0 5px; border-radius: 9px; background: var(--vk-accent); color: #fff;
  font-size: 12px; line-height: 18px; font-weight: 500; text-align: center; }

.im-composer { margin: 0; padding: 0 16px 16px; background: var(--vk-content); }
.im-composer .box { border-radius: 12px; background: var(--vk-modal); box-shadow: var(--vk-shadow-3); }
.quote-bar, .file-chip { display: flex; align-items: center; gap: 8px; padding: 8px 6px; border-bottom: 1px solid var(--vk-sep); }
.quote-bar > .ico { margin: 0 8px; color: var(--vk-accent); }
.quote-bar .bar { align-self: stretch; width: 2px; border-radius: 2px; background: var(--vk-forward-line); }
.quote-bar .body { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.quote-bar b { color: var(--vk-link); font-size: 12.5px; line-height: 14px; font-weight: 500; }
.quote-bar .body span { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.file-chip { padding: 8px 12px; }
.file-chip > .ico { color: var(--vk-accent); }
.file-chip .muted { color: var(--vk-text-2); }
.quote-bar .ib, .file-chip .ib { width: 36px; height: 36px; margin-left: auto; color: var(--vk-icon); opacity: .72; }
.im-composer-error { display: block; padding: 8px 12px; border-bottom: 1px solid var(--vk-sep); color: var(--vk-red); font-size: 13px; line-height: 18px; }
.im-composer-error:empty { display: none; }
.row-input { display: flex; align-items: flex-end; padding: 0 6px; }
.row-input .ib { width: 36px; height: 36px; margin: 4px 0; color: var(--vk-icon); opacity: .72; }
.row-input .ib:hover { opacity: 1; background: none; }
.row-input textarea { flex: 1; min-height: 18px; max-height: 216px; margin: 12px 6px; padding: 0; border: 0; border-radius: 0; background: none; color: var(--vk-text);
  font-size: 13px; line-height: 18px; resize: none; box-shadow: none; }
.row-input textarea:focus { outline: none; box-shadow: none; }
.row-input textarea::placeholder { color: var(--vk-text-2); }
.row-input .send.ready { color: var(--vk-accent); opacity: 1; }
.row-input .send:not(.ready) { opacity: .5; }

.im-viewer { position: fixed; inset: 0; z-index: 50; display: grid; place-items: center; background: rgba(0,0,0,.9); }
.im-viewer img { max-width: 100vw; max-height: 100vh; object-fit: contain; }
.im-viewer .ib { position: absolute; top: 8px; right: 8px; width: 48px; height: 48px; color: #fff; }
.im-viewer .ib:hover { background: rgba(255,255,255,.1); }

.im-bot-slot { min-height: 0; overflow-y: auto; border-left: 1px solid var(--vk-sep); background: var(--vk-content); }
.im-bot { display: flex; flex-direction: column; padding-bottom: 16px; }
.im-bot form { margin: 0; }
.im-bot-head { display: flex; align-items: center; gap: 8px; height: 56px; padding: 4px 8px; border-bottom: 1px solid var(--vk-sep); }
.im-bot-head .body { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.im-bot-head .line { display: flex; align-items: center; gap: 6px; font-size: 13px; line-height: 16px; font-weight: 500; }
.im-bot-head small, .im-bot .switch-row small, .im-bot h4 small, .members small { color: var(--vk-text-2); font-size: 13px; line-height: 16px; font-weight: 400; }
.im-bot-head small { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.im-bot h4 { margin: 0; padding: 12px 16px 4px; color: var(--vk-text); font-size: 14px; line-height: 18px; font-weight: 500; }
.im-bot h4 small { display: block; }
.switch-row { display: flex; align-items: center; gap: 12px; min-height: 48px; margin: 0; padding: 0 16px; color: var(--vk-text); font-size: 14px; line-height: 18px; cursor: pointer; }
.switch-row > span { flex: 1; display: flex; flex-direction: column; }
.persona-list { display: flex; flex-wrap: wrap; gap: 8px; padding: 4px 16px 8px; }
.chip-p { margin: 0; cursor: pointer; }
.chip-p span { display: inline-flex; align-items: center; height: 32px; padding: 0 12px; border-radius: 8px; background: var(--vk-secondary); color: var(--vk-text); font-size: 14px; }
.chip-p input:checked + span { background: var(--vk-accent); color: #fff; }
.im-bot .prompt { display: flex; flex-direction: column; align-items: flex-start; gap: 8px; padding: 4px 16px 8px; }
.im-bot .prompt textarea { width: 100%; min-height: 72px; margin: 0; padding: 8px 12px; border: 1px solid var(--vk-sep); border-radius: 8px; background: var(--vk-modal);
  color: var(--vk-text); font-size: 13px; line-height: 18px; box-shadow: none; resize: vertical; }
.im-bot .error { margin: 8px 16px 0; padding: 8px 12px; border: 0; border-radius: 8px; background: rgba(230,70,70,.12); color: var(--vk-red); }
.members { margin: 0; padding: 0 16px; list-style: none; }
.members li { display: flex; align-items: center; gap: 12px; height: 48px; margin: 0; padding: 0; }
.members a { flex: 1; min-width: 0; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; color: var(--vk-text); font-size: 14px; }
.members label { display: flex; align-items: center; gap: 8px; margin: 0; cursor: pointer; }

@media (max-width: 767px) {
  body.page-im { grid-template-columns: minmax(0, 1fr); column-gap: 0; }
  .vk-header { grid-column: 1; padding: 0 8px; }
  .vk-burger { display: inline-grid; }
  .vk-nav { position: fixed; top: 0; left: 0; bottom: 0; z-index: 30; grid-column: auto; grid-row: auto; width: 240px; margin: 0; padding: 56px 8px 8px;
    background: var(--vk-content); transform: translateX(-100%); transition: transform .2s; }
  .vk-nav.open { transform: none; }
  main.im-shell { grid-column: 1; margin: 0; }
  .im { grid-template-columns: minmax(0, 1fr); height: calc(100dvh - 48px); border-radius: 0; }
  .im-side { border-right: 0; }
  .im-main { display: none; }
  .im.show-chat .im-side { display: none; }
  .im.show-chat .im-main { display: flex; }
  .im-chat-head .close { display: none; }
  .im-chat-head .back { display: inline-grid; }
  .im-messages { padding: 0 8px 8px; }
  .im-composer { padding: 0 8px 8px; }
  .im-down { right: 8px; }
  .msg .photo img { max-width: 100%; }
  .im-chat.with-panel { grid-template-columns: minmax(0, 1fr); }
  .im-bot-slot { position: fixed; inset: 0; z-index: 40; border: 0; }
}
```

- [ ] **Step 7: Run the suite**

Run: `.venv/bin/pytest -q`
Expected: PASS, including both `test_vk_icons.py` tests now that `NAV` exists.

- [ ] **Step 8: Commit**

```bash
git add web/render.py web/templates/base.html web/templates/im.html web/templates/partials/im_shell.html web/static/im.css tests/web/test_im_pages.py
git commit -m "wrap the messenger in a VK-style shell and rewrite its stylesheet"
```

---

### Task 3: Dialog list

**Files:**
- Modify: `web/templates/partials/im.html`, `web/templates/partials/im_dialogs.html`, `web/static/im.js` (`im` component)
- Create: `web/templates/partials/im_empty.html`
- Test: `tests/web/test_im_pages.py`

**Interfaces:**
- Consumes: filter `since`, `now` in the dialogs context (Task 1); macro `icon` (Task 0).
- Produces: `<template id="im-empty">` with the empty state; `im.close()` handling `im-close` (used by Task 4's close button).

- [ ] **Step 1: Failing tests**

In `tests/web/test_im_pages.py` change the assertion in `test_im_page_lists_dialogs_with_modes` from `'class="unread">2<'` to `'class="unread quiet">2<'` (the fixture chat is muted) and append:

```python
def test_dialog_rows_show_mute_icon_ticks_and_short_age(client):
    r = client.get("/im/dialogs", auth=AUTH, headers={"HX-Request": "true"})
    chat, user = r.text.split("<li")[1:]
    assert "vk-icons.svg#mute_cross_16" in chat and "vk-icons.svg#pin_16" in chat
    assert 'class="att">Стикер' in chat and "Вася:" in chat
    assert "vk-icons.svg#check_outline_16" in user and "Вы:" in user     # своё, непрочитанное — одна галочка
    assert '<span class="when"> · ' in user and "pinned-last" in chat and "pinned-last" not in user


def test_empty_state_template_is_on_the_page(client):
    r = client.get("/im", auth=AUTH)
    assert r.text.count("Выберите чат") == 2 and '<template id="im-empty">' in r.text
```

- [ ] **Step 2: Run to see them fail**

Run: `.venv/bin/pytest -q tests/web/test_im_pages.py -k "dialog_rows or empty_state or lists_dialogs"`
Expected: FAIL.

- [ ] **Step 3: Templates**

`web/templates/partials/im_empty.html`:

```jinja
{% from "partials/im_icons.html" import icon %}
<div class="im-empty">{{ icon('messages_outline_56') }}<span>Выберите чат</span></div>
```

`web/templates/partials/im.html`:

```jinja
{% from "partials/im_icons.html" import icon %}
<div class="im" x-data="im({{ sel or 'null' }})" :class="{ 'show-chat': pane === 'chat' }" @keydown.window="hotkey($event)">
  <aside class="im-side">
    <header class="im-side-head">Мессенджер</header>
    <label class="im-search">{{ icon('search_outline_16') }}<input type="search" placeholder="Поиск" x-model="filter" x-ref="search" aria-label="Поиск по диалогам"></label>
    <div id="dialogs" class="im-dialogs">
      <ul id="dialog-list" hx-get="/im/dialogs" hx-trigger="every 10s [document.visibilityState === 'visible']"
          hx-target="#dialog-list" hx-swap="innerHTML">{% include "partials/im_dialogs.html" %}</ul>
    </div>
    <label class="im-side-foot">{{ icon('message_outline_20') }}<span>Только непрочитанные</span><input type="checkbox" role="switch" class="sw" x-model="unreadOnly"></label>
  </aside>
  <section id="chat" class="im-main">
    {% if chat %}{% include "partials/im_chat.html" %}{% else %}{% include "partials/im_empty.html" %}{% endif %}
  </section>
  <template id="im-empty">{% include "partials/im_empty.html" %}</template>
</div>
```

`web/templates/partials/im_dialogs.html`:

```jinja
{% from "partials/im_icons.html" import icon %}
{# только <li>, вставляется в #dialog-list #}
{% for d, mode in dialogs %}<li class="dlg{{ ' pinned-last' if d.pinned and not (loop.nextitem and loop.nextitem[0].pinned) }}" data-title="{{ d.peer.title|lower }}" data-unread="{{ d.unread }}"
    x-show="matches($el)" :class="{ active: sel === {{ d.peer.id }} }">
  <a hx-get="/im/{{ d.peer.id }}" hx-target="#chat" hx-swap="innerHTML" href="/im?sel={{ d.peer.id }}" @click="open({{ d.peer.id }})">
    <span class="ava a48">{% if d.peer.photo %}<img src="{{ d.peer.photo }}" alt="">{% else %}<i>{{ d.peer.title[:1] }}</i>{% endif %}{% if d.peer.online %}<b class="dot"></b>{% endif %}</span>
    <span class="dlg-head"><span class="title">{{ d.peer.title }}</span>{% if d.muted %}{{ icon('mute_cross_16', 'mute') }}{% endif %}{% with m = mode %}{% include "partials/im_badge.html" %}{% endwith %}</span>
    <span class="dlg-msg">{% if d.last %}<span class="who">{% if d.last.out %}Вы{% else %}{{ d.last.author.split(' ')[0] }}{% endif %}:</span> {% if d.last.text or d.last.action %}{{ d.last|preview }}{% else %}<span class="att">{{ d.last|preview }}</span>{% endif %}<span class="when"> · {{ d.last.ts|since(now, tz) }}</span>{% endif %}</span>
    <span class="dlg-icons">{% if d.unread %}<span class="unread{{ ' quiet' if d.muted }}">{{ d.unread if d.unread < 100 else '99+' }}</span>{% elif d.last and d.last.out %}{{ icon('check_double_outline_16' if d.last.read else 'check_outline_16', 'ticks') }}{% endif %}{% if d.pinned %}{{ icon('pin_16') }}{% endif %}</span>
  </a>
</li>{% endfor %}
```

- [ ] **Step 4: `im` component in `web/static/im.js`**

```js
  Alpine.data("im", (sel) => ({
    sel, pane: sel ? "chat" : "list", filter: "", unreadOnly: false,
    init() {
      this.$el.addEventListener("im-back", () => { this.pane = "list"; });
      this.$el.addEventListener("im-close", () => this.close());
    },
    open(id) { this.sel = id; this.pane = "chat"; },
    close() {
      this.sel = null;
      this.pane = "list";
      document.getElementById("chat").innerHTML = document.getElementById("im-empty").innerHTML;
      history.pushState({}, "", "/im");
    },
    hotkey(e) {
      // code, а не key: в русской раскладке key — «л»
      if (!(e.ctrlKey || e.metaKey) || e.code !== "KeyK") return;
      e.preventDefault();
      this.pane = "list";
      this.$nextTick(() => this.$refs.search.focus());
    },
    matches(li) {
      const byTitle = !this.filter || li.dataset.title.includes(this.filter.toLowerCase());
      const byUnread = !this.unreadOnly || Number(li.dataset.unread) > 0;
      return byTitle && byUnread;
    },
  }));
```

- [ ] **Step 5: Run the suite**

Run: `.venv/bin/pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/templates/partials/im.html web/templates/partials/im_dialogs.html web/templates/partials/im_empty.html web/static/im.js tests/web/test_im_pages.py
git commit -m "restyle the dialog list after vk.com"
```

---

### Task 4: Chat header, message rows, photo viewer

**Files:**
- Modify: `web/templates/partials/im_chat.html`, `web/templates/partials/im_rows.html`, `web/static/im.js` (`chat` component: `viewer`)
- Test: `tests/web/test_im_pages.py`

**Interfaces:**
- Consumes: `Row.unread`, filter `presence`, `c.now`/`c.tz` (Task 1); `im-close` (Task 3).
- Produces: `.im-history` wrapper with `#messages` inside, `.im-convo` column, `#bot-slot` as the second grid column, `chat.viewer` state; `im_rows.html` includes `partials/im_voice.html` for voice attachments (written in Task 5 — until then keep the `<audio>` fallback inline, see Step 3).

- [ ] **Step 1: Failing tests**

In `tests/web/test_im_pages.py`, `test_im_page_with_sel_renders_chat`: replace the `'src="https://cdn.example/v.mp3"'` assertion with `'voice("https://cdn.example/v.mp3", 20)' in r.text` (kept green in Task 5 too). Append:

```python
def test_chat_opening_puts_unread_separator_before_first_unread_incoming(client):
    r = client.get(f"/im?sel={PEER_CHAT}", auth=AUTH)
    assert r.text.index('data-id="501"') < r.text.index('class="im-unread"') < r.text.index('data-id="502"')
    poll = client.get(f"/im/{PEER_CHAT}/messages?after=500", auth=AUTH, headers={"HX-Request": "true"})
    assert "im-unread" not in poll.text


def test_chat_header_shows_presence_for_users(client):
    client.app.state.vk = FakeVk("t")
    client.app.state.vk.history_page = lambda *a, **k: {**HISTORY, "conversations": [CONVERSATIONS["items"][1]["conversation"]]}
    r = client.get(f"/im?sel={PEER_USER}", auth=AUTH)
    assert "была в сети 3 июля" in r.text and "в 09:15" in r.text
    assert "vk-icons.svg#cancel_24" in r.text and "vk-icons.svg#chevron_left_24" in r.text


def test_only_own_messages_get_a_delete_button(client):
    r = client.get(f"/im?sel={PEER_CHAT}", auth=AUTH)
    own = r.text.split('data-id="501"')[1].split("</article>")[0]
    other = r.text.split('data-id="500"')[1].split("</article>")[0]
    assert "/messages/501/delete" in own and "vk-icons.svg#delete_outline_24" in own
    assert "delete" not in other and "vk-icons.svg#reply_24" in other
    assert 'class="info"' in own and "vk-icons.svg#check_double_outline_16" in own


def test_photo_opens_in_viewer(client):
    photo = {"id": 600, "date": 1788876300, "peer_id": PEER_CHAT, "from_id": 11, "out": 0, "text": "",
             "attachments": [{"type": "photo", "photo": {"sizes": [{"url": "https://cdn.example/p_x.jpg", "width": 604},
                                                                    {"url": "https://cdn.example/p_w.jpg", "width": 1280}]}}]}
    client.app.state.vk = FakeVk("t")
    client.app.state.vk.history_page = lambda *a, **k: {**HISTORY, "items": [photo] + HISTORY["items"]}
    r = client.get(f"/im?sel={PEER_CHAT}", auth=AUTH)
    assert """@click.prevent='viewer = "https://cdn.example/p_w.jpg"'""" in r.text
    assert 'class="im-viewer"' in r.text
```

Add `PEER_USER` to the fixtures import of the test module.

- [ ] **Step 2: Run to see them fail**

Run: `.venv/bin/pytest -q tests/web/test_im_pages.py -k "unread_separator or presence or delete_button or viewer or sel_renders"`
Expected: FAIL.

- [ ] **Step 3: `im_chat.html`**

```jinja
{% from "partials/im_icons.html" import icon %}
{# ожидает chat: dict из chat_ctx #}
{% set c = chat %}
<div class="im-chat" x-data="chat({{ c.peer_id }}, {{ c.out_read }})" :class="{ 'with-panel': panel }">
  <div class="im-convo">
    <header class="im-chat-head">
      <button type="button" class="ib close" @click="$dispatch('im-close')" aria-label="Закрыть">{{ icon('cancel_24') }}</button>
      <button type="button" class="ib back" @click="$dispatch('im-back')" aria-label="Назад">{{ icon('chevron_left_24') }}</button>
      <span class="ava a32">{% if c.peer and c.peer.photo %}<img src="{{ c.peer.photo }}" alt="">{% elif c.peer %}<i>{{ c.peer.title[:1] }}</i>{% endif %}</span>
      <span class="body">
        <span class="line"><b>{{ c.peer.title if c.peer else c.peer_id|peer_label }}</b><span id="chat-badge">{% with m = c.mode %}{% include "partials/im_badge.html" %}{% endwith %}</span></span>
        <small>{% if c.peer and c.peer.kind == 'chat' %}{{ c.peer.members|plural('участник', 'участника', 'участников') }}{% elif c.peer and c.peer.kind == 'group' %}сообщество{% elif c.peer %}{{ c.peer|presence(c.now, c.tz) }}{% endif %}</small>
      </span>
      <a class="ib" href="{{ c.peer_id|peer_link }}" title="Открыть в VK" aria-label="Открыть в VK" target="_blank" rel="noopener">{{ icon('logo_vk_outline_24') }}</a>
      <button type="button" class="ib" title="Бот в этом чате" aria-label="Бот в этом чате" @click="panel = !panel"
              hx-get="/im/{{ c.peer_id }}/bot" hx-target="#bot-slot" hx-swap="innerHTML" hx-trigger="click once">{{ icon('robot_outline_24') }}</button>
    </header>
    <div class="im-history">
      <div id="messages" class="im-messages" x-ref="list" @scroll.passive="onScroll()">
        {% if c.oldest %}<div class="im-more" hx-get="/im/{{ c.peer_id }}/messages?before={{ c.oldest }}" hx-trigger="intersect once delay:500ms" hx-swap="outerHTML"></div>{% endif %}
        {% with rows = c.rows, tz = c.tz %}{% include "partials/im_rows.html" %}{% endwith %}
        {% if not c.rows %}<div class="im-empty">Сообщений пока нет</div>{% endif %}
      </div>
      <button type="button" class="im-down" x-show="!atBottom" x-cloak @click="scrollBottom(true)" aria-label="К последним сообщениям">{{ icon('chevron_down_24') }}<b x-show="pending" x-text="pending"></b></button>
    </div>
    <form class="im-composer" x-data="composer()" method="post" action="/im/{{ c.peer_id }}/send" enctype="multipart/form-data"
          hx-post="/im/{{ c.peer_id }}/send" hx-target="#messages" hx-swap="beforeend" hx-disabled-elt="find button[type=submit]"
          hx-vals='js:{...lastRendered()}'
          @htmx:after-request="if ($event.detail.elt === $el && $event.detail.xhr.status < 300) reset()" @im-reply.window="quote($event.detail)">
      <div class="quote-bar" x-show="reply" x-cloak><b x-text="reply?.author"></b><span x-text="reply?.text"></span>
        <button type="button" @click="reply = null" aria-label="Убрать цитату">×</button></div>
      <small id="composer-error" class="im-composer-error"></small>
      <input type="hidden" name="reply_to" :value="reply?.id || ''">
      <div class="file-chip" x-show="file" x-cloak><span x-text="file?.name"></span><span class="muted" x-text="size"></span>
        <button type="button" @click="clearFile()" aria-label="Убрать файл">×</button></div>
      <div class="row-input">
        <label class="attach" title="Голосовое из .ogg/.mp3"><input type="file" name="voice" accept=".ogg,.mp3,audio/ogg,audio/mpeg" x-ref="f" @change="pick()" hidden><svg viewBox="0 0 24 24"><path d="M12 2a10 10 0 100 20 10 10 0 000-20zm5 11h-4v4h-2v-4H7v-2h4V7h2v4h4z"/></svg></label>
        <textarea name="text" rows="1" placeholder="Сообщение" x-ref="t" x-model="text" @input="grow()"
                  @keydown.enter="if (!$event.shiftKey && !$event.isComposing) { $event.preventDefault(); $el.form.requestSubmit() }" @keydown.escape="reply = null"></textarea>
        <button type="button" class="draft" title="Черновик от бота" hx-post="/im/{{ c.peer_id }}/draft" hx-params="none" hx-swap="none"
                hx-disabled-elt="this" @htmx:after-request="if ($event.detail.xhr.status === 200) draft($event.detail.xhr.responseText)">✨</button>
        <button type="submit" class="send" aria-label="Отправить"><svg viewBox="0 0 24 24"><path d="M2 21l21-9L2 3v7l15 2-15 2z"/></svg></button>
      </div>
    </form>
  </div>
  <div id="bot-slot" class="im-bot-slot" x-show="panel" x-cloak></div>
  <div class="im-viewer" x-show="viewer" x-cloak @click="viewer = null" @keydown.escape.window="viewer = null">
    <button type="button" class="ib" aria-label="Закрыть">{{ icon('cancel_24') }}</button>
    <img :src="viewer" alt="">
  </div>
  <div id="chat-state" data-out-read="{{ c.out_read }}" hidden></div>
  <div id="chat-poll" hx-get="/im/{{ c.peer_id }}/messages"
       hx-trigger="every 3s [document.visibilityState === 'visible']" hx-target="#messages" hx-swap="beforeend"
       hx-vals='js:{...lastRendered()}'></div>
</div>
```

(The composer keeps its old markup until Task 6; the `im-down` button references `atBottom`/`pending`/`scrollBottom` which exist after Task 6 — until then Alpine evaluates `atBottom` as `undefined` → the button shows; acceptable inside the branch, fixed two tasks later.)

`im_rows.html`:

```jinja
{% from "partials/im_icons.html" import icon %}
{# ожидает rows, tz и c (peer_id для удаления) #}
{% for r in rows %}{% set m = r.message %}
{% if r.day %}<div class="im-day"><span>{{ r.day }}</span></div>{% endif %}
{% if r.unread %}<div class="im-unread"><span>Непрочитанные сообщения</span></div>{% endif %}
{% if m.action %}<div class="im-action" data-id="{{ m.id }}" data-from="0" data-ts="{{ m.ts }}">{{ m.action }}</div>{% else %}
<article class="msg {{ 'head' if r.head }} {{ 'out' if m.out }}" data-id="{{ m.id }}" data-from="{{ m.from_id }}" data-ts="{{ m.ts }}">
  {% if r.head %}<a class="ava a36" href="https://vk.com/id{{ m.from_id }}">{% if m.photo %}<img src="{{ m.photo }}" alt="">{% else %}<i>{{ m.author[:1] }}</i>{% endif %}</a>{% endif %}
  <span class="info">{% if m.out %}<span class="ticks" :class="{ read: {{ m.id }} <= outRead }">{{ icon('check_outline_16', 'one') }}{{ icon('check_double_outline_16', 'two') }}</span>{% endif %}<time>{{ m.ts|clock(tz) }}</time></span>
  {% if r.head %}<div class="name"><a href="https://vk.com/id{{ m.from_id }}">{{ m.author }}</a>{% if m.bot %}<span class="badge-mode">бот · {{ m.bot.persona }}{% if m.bot.model %} · {{ m.bot.model }}{% endif %}</span>{% endif %}</div>
  {% elif m.bot %}<div class="name"><span class="badge-mode">бот · {{ m.bot.persona }}</span></div>{% endif %}
  {% if m.reply %}<blockquote class="quote"><b>{{ m.reply.author }}</b><span>{{ m.reply.text }}</span></blockquote>{% endif %}
  {% if m.text %}<p class="text">{{ m.text }}</p>{% endif %}
  {% for a in m.attachments %}
    {% if a.kind == 'photo' %}<a class="photo" href="{{ a.url }}" target="_blank" rel="noopener" @click.prevent='viewer = {{ a.url|tojson }}'><img src="{{ a.preview }}" alt="фото" loading="lazy"></a>
    {% elif a.kind == 'sticker' %}<img class="sticker" src="{{ a.url }}" alt="стикер" loading="lazy">
    {% elif a.kind == 'voice' %}{% set wid = 'w' ~ m.id ~ '-' ~ loop.index %}{% include "partials/im_voice.html" %}
    {% elif a.kind == 'video' %}<div class="video">{% if a.preview %}<img src="{{ a.preview }}" alt="" loading="lazy">{% endif %}<span>{{ a.title }}</span></div>
    {% elif a.kind in ('doc', 'link') %}<a class="doc" href="{{ a.url }}" target="_blank" rel="noopener">{{ icon('document_outline_24') }}{{ a.title }}</a>
    {% else %}<span class="badge-mode">{{ a.title }}</span>{% endif %}
  {% endfor %}
  {% if m.fwd_count %}<span class="fwd">{{ icon('message_forward_outline_16') }}{{ m.fwd_count }} пересланных</span>{% endif %}
  <span class="actions">
    {# одинарные кавычки: tojson не экранирует двойные #}
    <button type="button" title="Ответить" aria-label="Ответить" @click='$dispatch("im-reply", { id: {{ m.id }}, author: {{ m.author|tojson }}, text: {{ (m.text or (m|preview))[:80]|tojson }} })'>{{ icon('reply_24') }}</button>
    {% if m.out %}<button type="button" title="Удалить" aria-label="Удалить" hx-post="/im/{{ c.peer_id }}/messages/{{ m.id }}/delete" hx-confirm="Удалить сообщение у всех?" hx-target="closest article" hx-swap="delete">{{ icon('delete_outline_24') }}</button>{% endif %}
  </span>
</article>{% endif %}
{% endfor %}
```

Temporary `web/templates/partials/im_voice.html` for this task (replaced in Task 5):

```jinja
<div class="voice" x-data='voice({{ a.url|tojson }}, {{ a.duration }})'><audio controls preload="none" src="{{ a.url }}"></audio><span class="dur">{{ a.duration|mmss }}</span>
  {% if a.transcript %}<p class="transcript">{{ a.transcript }}</p>{% endif %}</div>
```

- [ ] **Step 4: `chat` component gets `viewer` and stubs used by the header**

In `web/static/im.js`, `Alpine.data("chat", …)` state line becomes:

```js
    peerId, outRead, fromBottom: 0, stick: true, readUpTo: 0, settling: false, panel: false, viewer: null, atBottom: true, pending: 0,
```

and add a no-op `onScroll() {}` after `nearBottom()` (filled in Task 6). Also add a placeholder `Alpine.data("voice", () => ({}))` next to `readMark` (filled in Task 5).

- [ ] **Step 5: Run the suite**

Run: `.venv/bin/pytest -q`
Expected: PASS (`test_reply_button_payload_survives_attribute_quoting`, `test_poll_continues_series_of_same_author`, `test_sent_message_continues_own_series` still match the class string).

- [ ] **Step 6: Commit**

```bash
git add web/templates/partials/im_chat.html web/templates/partials/im_rows.html web/templates/partials/im_voice.html web/static/im.js tests/web/test_im_pages.py
git commit -m "render chat header and message rows the vk.com way"
```

---

### Task 5: Voice player

**Files:**
- Rewrite: `web/templates/partials/im_voice.html`
- Modify: `web/static/im.js` (`voice` component, `mmss` helper)
- Test: `tests/web/test_im_pages.py`

**Interfaces:**
- Consumes: filter `wave_bars` (Task 1), `wid` set by `im_rows.html` (Task 4), `toast()` from `app.js`.
- Produces: Alpine component `voice(url, duration)` with `playing`, `pos`, `pct`, `time`, `open`, `toggle()`, `pause()`, `seek(e)`; window event `im-voice-play` (detail = the player element).

- [ ] **Step 1: Failing test**

```python
def test_voice_player_renders_wave_bars_and_transcript_toggle(client):
    r = client.get(f"/im?sel={PEER_CHAT}", auth=AUTH)
    voice = r.text.split('class="voice"')[1].split("</article>")[0]
    assert voice.count('rx="1"') == 60                       # 20 с → 60 столбиков
    assert 'id="w500-1"' in voice and 'clip-path="url(#w500-1c)"' in voice
    assert "vk-icons.svg#play_circle_32" in voice and "vk-icons.svg#pause_circle_32" in voice
    assert 'class="aa"' in voice and "после смены выкину</p>" in voice
    assert "<audio" not in voice and "0:20" in voice
```

- [ ] **Step 2: Run to see it fail**

Run: `.venv/bin/pytest -q tests/web/test_im_pages.py -k voice_player`
Expected: FAIL (`<audio` present, no rects).

- [ ] **Step 3: `im_voice.html`**

```jinja
{# ожидает a: Attachment(kind='voice'), wid: уникальный id волны в документе #}
{% set bars = a.waveform|wave_bars(a.duration) %}{% set w = bars|length * 3 - 1 %}
<div class="voice" x-data='voice({{ a.url|tojson }}, {{ a.duration }})' @im-voice-play.window="if ($event.detail !== $el) pause()">
  <button type="button" class="play" :aria-label="playing ? 'Пауза' : 'Слушать'" @click="toggle()">
    <svg class="ico" width="32" height="32" x-show="!playing"><use href="/static/vk-icons.svg#play_circle_32"/></svg>
    <svg class="ico" width="32" height="32" x-show="playing" x-cloak><use href="/static/vk-icons.svg#pause_circle_32"/></svg>
  </button>
  <span class="wave-col">
    <svg class="wave" width="{{ w }}" height="12" viewBox="0 0 {{ w }} 12" @click="seek($event)">
      <defs><g id="{{ wid }}">{% for h in bars %}<rect x="{{ loop.index0 * 3 }}" y="{{ (12 - h) / 2 }}" width="2" height="{{ h }}" rx="1"/>{% endfor %}</g>
        <clipPath id="{{ wid }}c"><rect x="0" y="0" height="12" :width="{{ w }} * pct / 100"/></clipPath></defs>
      <use href="#{{ wid }}" class="base"/><use href="#{{ wid }}" clip-path="url(#{{ wid }}c)"/>
    </svg>
    <span class="dur" x-text="time">{{ a.duration|mmss }}</span>
  </span>
  {% if a.transcript %}<button type="button" class="aa" @click="open = !open" aria-label="Расшифровка">Aa</button>
  <p class="transcript" x-show="open" x-cloak>{{ a.transcript }}</p>{% endif %}
</div>
```

- [ ] **Step 4: `voice` component and `mmss` in `web/static/im.js`**

Top-level helper (next to `lastRendered`):

```js
function mmss(seconds) {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
```

Replace the placeholder with:

```js
  Alpine.data("voice", (url, duration) => ({
    playing: false, pos: 0, open: false, audio: null,
    get pct() { return duration ? Math.min(100, (this.pos / duration) * 100) : 0; },
    get time() { return mmss(this.playing || this.pos ? this.pos : duration); },
    ensure() {
      if (this.audio) return;
      this.audio = new Audio(url);
      this.audio.preload = "none";
      this.audio.addEventListener("timeupdate", () => { this.pos = this.audio.currentTime; });
      this.audio.addEventListener("ended", () => { this.playing = false; this.pos = 0; });
      this.audio.addEventListener("error", () => { this.playing = false; toast("Не удалось загрузить голосовое", "bad"); });
    },
    toggle() { this.playing ? this.pause() : this.play(); },
    play() {
      this.ensure();
      window.dispatchEvent(new CustomEvent("im-voice-play", { detail: this.$el }));
      this.audio.play();
      this.playing = true;
    },
    pause() { this.audio?.pause(); this.playing = false; },
    seek(e) {
      const box = e.currentTarget.getBoundingClientRect();
      this.ensure();
      this.audio.currentTime = this.pos = ((e.clientX - box.left) / box.width) * duration;
      if (!this.playing) this.play();
    },
  }));
```

- [ ] **Step 5: Run the suite**

Run: `.venv/bin/pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/templates/partials/im_voice.html web/static/im.js tests/web/test_im_pages.py
git commit -m "draw voice messages with a VK-style waveform player"
```

---

### Task 6: Composer and chat chrome behaviour

**Files:**
- Modify: `web/templates/partials/im_chat.html` (composer block), `web/static/im.js` (`chat`, `composer`)
- Test: `tests/web/test_im_pages.py`

**Interfaces:**
- Consumes: `.im-history`, `.im-down`, `onScroll()` hook (Task 4).
- Produces: `chat.atBottom`, `chat.pending`, `chat.onScroll()`, `chat.markStuck()`, `chat.scrollBottom(smooth)`; `composer.ready`.

- [ ] **Step 1: Failing test**

```python
def test_composer_is_a_vk_card_with_icon_buttons(client):
    r = client.get(f"/im?sel={PEER_CHAT}", auth=AUTH)
    form = r.text.split('class="im-composer"')[1].split("</form>")[0]
    assert 'class="box"' in form and "vk-icons.svg#send_24" in form and "vk-icons.svg#magic_wand_outline_24" in form
    assert "vk-icons.svg#add_circle_outline_24" in form and 'placeholder="Сообщение"' in form
    assert ':class="{ ready }"' in form and "✨" not in form
    assert 'class="im-down"' in r.text
```

- [ ] **Step 2: Run to see it fail**

Run: `.venv/bin/pytest -q tests/web/test_im_pages.py -k composer_is`
Expected: FAIL.

- [ ] **Step 3: Composer markup in `im_chat.html`**

Replace the `<form class="im-composer" …>…</form>` block with:

```jinja
    <form class="im-composer" x-data="composer()" method="post" action="/im/{{ c.peer_id }}/send" enctype="multipart/form-data"
          hx-post="/im/{{ c.peer_id }}/send" hx-target="#messages" hx-swap="beforeend" hx-disabled-elt="find button[type=submit]"
          hx-vals='js:{...lastRendered()}'
          @htmx:after-request="if ($event.detail.elt === $el && $event.detail.xhr.status < 300) reset()" @im-reply.window="quote($event.detail)">
      <div class="box">
        <div class="quote-bar" x-show="reply" x-cloak>{{ icon('reply_24') }}<span class="bar"></span>
          <span class="body"><b x-text="reply?.author"></b><span x-text="reply?.text"></span></span>
          <button type="button" class="ib" @click="reply = null" aria-label="Убрать цитату">{{ icon('cancel_20') }}</button></div>
        <div class="file-chip" x-show="file" x-cloak>{{ icon('document_outline_24') }}<span x-text="file?.name"></span><span class="muted" x-text="size"></span>
          <button type="button" class="ib" @click="clearFile()" aria-label="Убрать файл">{{ icon('cancel_20') }}</button></div>
        <small id="composer-error" class="im-composer-error"></small>
        <input type="hidden" name="reply_to" :value="reply?.id || ''">
        <div class="row-input">
          <label class="ib attach" title="Голосовое из .ogg/.mp3"><input type="file" name="voice" accept=".ogg,.mp3,audio/ogg,audio/mpeg" x-ref="f" @change="pick()" hidden>{{ icon('add_circle_outline_24') }}</label>
          <textarea name="text" rows="1" placeholder="Сообщение" x-ref="t" x-model="text" @input="grow()"
                    @keydown.enter="if (!$event.shiftKey && !$event.isComposing) { $event.preventDefault(); if (ready) $el.form.requestSubmit() }" @keydown.escape="reply = null"></textarea>
          <button type="button" class="ib draft" title="Черновик от бота" aria-label="Черновик от бота" hx-post="/im/{{ c.peer_id }}/draft" hx-params="none" hx-swap="none"
                  hx-disabled-elt="this" @htmx:after-request="if ($event.detail.xhr.status === 200) draft($event.detail.xhr.responseText)">{{ icon('magic_wand_outline_24') }}</button>
          <button type="submit" class="ib send" :class="{ ready }" @click="if (!ready) $event.preventDefault()" aria-label="Отправить">{{ icon('send_24') }}</button>
        </div>
      </div>
    </form>
```

- [ ] **Step 4: `chat` and `composer` in `web/static/im.js`**

`chat` — full component:

```js
  Alpine.data("chat", (peerId, outRead) => ({
    peerId, outRead, fromBottom: 0, stick: true, readUpTo: 0, settling: false, panel: false, viewer: null,
    atBottom: true, pending: 0, before: 0, raf: 0,
    init() {
      // синхронно, а не в $nextTick: иначе IntersectionObserver успевает увидеть сентинел
      // вверху ещё не прокрученного списка и зря грузит страницу старых
      const list = this.$el.querySelector(".im-messages");
      list.scrollTop = list.scrollHeight;
      // измеряем до свопа: после вставки старых рядов над экраном браузер оставляет scrollTop
      // (у верхнего края scroll anchoring не срабатывает), и видимый сентинел тянул бы всю историю
      this.$el.addEventListener("htmx:beforeSwap", () => {
        const el = this.$refs.list;
        this.fromBottom = el.scrollHeight - el.scrollTop;
        this.stick = this.nearBottom();
        this.before = Number(lastRendered().after);
      });
      this.$el.addEventListener("htmx:afterSwap", (e) => {
        const state = document.getElementById("chat-state");
        if (state) this.outRead = Number(state.dataset.outRead);
        const target = e.detail.target;
        if (target.id === "messages") this.settleMessages();
        if (target.classList.contains("im-more")) {
          this.dedupeDays();
          this.$refs.list.scrollTop = this.$refs.list.scrollHeight - this.fromBottom;
          this.markStuck();
        }
      });
      this.$nextTick(() => this.markRead());
    },
    // afterSwap приходит на каждый вставленный элемент — разбираем ленту один раз за своп
    settleMessages() {
      if (this.settling) return;
      this.settling = true;
      queueMicrotask(() => {
        this.settling = false;
        this.dedupe();
        if (this.$refs.list.querySelector("[data-id]")) this.$refs.list.querySelector(".im-empty")?.remove();
        if (this.stick) this.scrollBottom();
        else this.pending += this.arrived();
        this.markRead();
        this.markStuck();
      });
    },
    // счётчик на кнопке «вниз»: входящие, вставленные поллингом, пока лента отмотана вверх
    arrived() {
      return [...this.$refs.list.querySelectorAll(".msg:not(.out)")].filter((el) => Number(el.dataset.id) > this.before).length;
    },
    // поллинг, ушедший до отправки, может вернуть уже вставленное отправкой сообщение
    dedupe() {
      const seen = new Set();
      this.$refs.list.querySelectorAll("[data-id]").forEach((el) => {
        if (seen.has(el.dataset.id)) el.remove();
        else seen.add(el.dataset.id);
      });
    },
    // страница старых заканчивается чипом того же дня, с которого начиналась лента
    dedupeDays() {
      let prev = null;
      this.$refs.list.querySelectorAll(".im-day").forEach((chip) => {
        if (chip.textContent === prev) chip.remove();
        else prev = chip.textContent;
      });
    },
    markRead() {
      const incoming = [...this.$refs.list.querySelectorAll(".msg:not(.out)")].map((el) => Number(el.dataset.id));
      const last = Math.max(0, ...incoming);
      if (last <= this.readUpTo || document.visibilityState !== "visible" || !readOnOpen()) return;
      this.readUpTo = last;
      fetch(`/im/${this.peerId}/read`, { method: "POST", headers: { "HX-Request": "true" } });
    },
    onScroll() {
      if (this.raf) return;
      this.raf = requestAnimationFrame(() => {
        this.raf = 0;
        this.atBottom = this.nearBottom();
        if (this.atBottom) this.pending = 0;
        this.markStuck();
      });
    },
    // sticky сам не сообщает, что упёрся в край: подложку получает последний чип выше кромки прокрутки
    markStuck() {
      const list = this.$refs.list;
      let stuck = null;
      list.querySelectorAll(".im-day").forEach((chip) => {
        chip.classList.remove("stuck");
        if (list.scrollTop > 0 && chip.offsetTop <= list.scrollTop) stuck = chip;
      });
      stuck?.classList.add("stuck");
    },
    nearBottom() {
      const el = this.$refs.list;
      return el.scrollHeight - el.scrollTop - el.clientHeight < 120;
    },
    scrollBottom(smooth = false) {
      this.$refs.list.scrollTo({ top: this.$refs.list.scrollHeight, behavior: smooth ? "smooth" : "auto" });
    },
  }));
```

`composer` — add the getter and the 12-line cap:

```js
  Alpine.data("composer", () => ({
    text: "", reply: null, file: null,
    get ready() { return this.text.trim().length > 0 || !!this.file; },
    get size() {
      if (!this.file) return "";
      const kb = this.file.size / 1024;
      return kb < 1024 ? Math.ceil(kb) + " КБ" : (kb / 1024).toFixed(1) + " МБ";
    },
    pick() {
      const f = this.$refs.f.files[0];
      this.file = f || null;
      if (f && !/\.(ogg|mp3)$/i.test(f.name)) {
        toast("Нужен .ogg или .mp3", "bad");
        this.clearFile();
      }
    },
    clearFile() { this.file = null; this.$refs.f.value = ""; },
    draft(t) {
      this.text = t;
      this.$nextTick(() => { this.grow(); this.$refs.t.focus(); });
    },
    grow() { const t = this.$refs.t; t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 216) + "px"; },
    quote(d) { this.reply = d; this.$refs.t.focus(); },
    reset() {
      this.text = "";
      this.reply = null;
      this.clearFile();
      document.getElementById("composer-error").textContent = "";
      this.$nextTick(() => this.grow());
    },
  }));
```

- [ ] **Step 5: Run the suite**

Run: `.venv/bin/pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/templates/partials/im_chat.html web/static/im.js tests/web/test_im_pages.py
git commit -m "rebuild the composer as a VK card and add scroll-down and sticky day chips"
```

---

### Task 7: Bot panel as a side column

**Files:**
- Modify: `web/templates/partials/im_bot.html`
- Test: `tests/web/test_im_bot.py`

**Interfaces:**
- Consumes: `.im-chat.with-panel` grid, `#bot-slot` (Task 4), `chat.panel` state, CSS classes `.im-bot-head .switch-row .sw .persona-list .chip-p .prompt .vk-btn .members` (Task 2).

- [ ] **Step 1: Failing test**

Append to `tests/web/test_im_bot.py`:

```python
def test_panel_has_vk_header_switches_and_persona_chips(client):
    r = client.get(f"/im/{PEER_CHAT}/bot", auth=AUTH, headers=HX)
    assert 'class="im-bot-head"' in r.text and "vk-icons.svg#cancel_24" in r.text and '@click="panel = false"' in r.text
    assert r.text.count('role="switch" class="sw"') >= 5          # 4 режима + «читать без отметки» + участники
    assert 'class="chip-p"' in r.text and 'name="slug" value="rina"' in r.text
    assert 'class="vk-btn"' in r.text and ">Сохранить<" in r.text
```

- [ ] **Step 2: Run to see it fail**

Run: `.venv/bin/pytest -q tests/web/test_im_bot.py -k vk_header`
Expected: FAIL.

- [ ] **Step 3: `im_bot.html`**

```jinja
{% from "partials/im_icons.html" import icon %}
<div id="bot-panel" class="im-bot">
  <span id="chat-badge" hx-swap-oob="true">{% with m = mode %}{% include "partials/im_badge.html" %}{% endwith %}</span>
  <header class="im-bot-head">
    <span class="ava a32 robot">{{ icon('robot_outline_24') }}</span>
    <span class="body"><span class="line"><b>Бот в этом чате</b>{% with m = mode %}{% include "partials/im_badge.html" %}{% endwith %}</span><small title="{{ mode.reason }}">{{ mode.reason }}</small></span>
    <button type="button" class="ib" @click="panel = false" aria-label="Закрыть">{{ icon('cancel_24') }}</button>
  </header>
  {% if error %}<div class="error">{{ error }}</div>{% endif %}
  <h4>Режим</h4>
  {% for switch, title, hint, value, show in [
      ("auto", "Отвечать без тега", "на каждое сообщение" if c.private else "всем участникам, как в личке", c.auto, True),
      ("onboarding", "Знакомиться с новичками", "вопросы вошедшим", c.onboarding, not c.private),
      ("paused", "Пауза в этом чате", "runtime.paused_peers", c.paused, True),
      ("blocked", "Заблокировать", "бот молчит здесь всегда", c.blocked, True)] %}
  {% if show %}<form hx-post="/im/{{ peer_id }}/bot/{{ switch }}" hx-target="#bot-panel" hx-swap="outerHTML" hx-trigger="change">
    <label class="switch-row"><span>{{ title }}<small>{{ hint }}</small></span><input type="checkbox" role="switch" class="sw" name="on" value="1" {{ 'checked' if value }}></label>
  </form>{% endif %}{% endfor %}
  <label class="switch-row" x-data="readMark"><span>Читать без отметки<small>VK не увидит, что сообщения прочитаны; во всех чатах этого браузера</small></span>
    <input type="checkbox" role="switch" class="sw" :checked="silent" @change="toggle($event.target.checked)"></label>
  <h4>Персоны <small>пусто — активная «{{ active or 'по умолчанию' }}»; несколько — случайная на каждый ответ</small></h4>
  <form class="persona-list" hx-post="/im/{{ peer_id }}/bot/personas" hx-target="#bot-panel" hx-swap="outerHTML" hx-trigger="change">
    {% for p in personas %}<label class="chip-p"><input type="checkbox" name="slug" value="{{ p.slug }}" {{ 'checked' if p.slug in c.personas }} hidden><span>{{ p.name }}</span></label>{% endfor %}
  </form>
  <h4>{{ "Про этого собеседника" if c.private else "Про эту беседу" }} <small>слой {{ "user_prompts" if c.private else "peer_prompts" }}</small></h4>
  <form class="prompt" hx-post="/im/{{ peer_id }}/bot/prompt" hx-target="#bot-panel" hx-swap="outerHTML">
    <textarea name="text" x-data="autogrow" @input="grow()">{{ c.prompt }}</textarea>
    <button class="vk-btn">Сохранить</button>
  </form>
  {% if members %}<h4>Участники <small>{{ members|length }}</small></h4>
  <ul class="members">{% for uid, name, photo in members %}<li>
    <span class="ava a32">{% if photo %}<img src="{{ photo }}" alt="">{% else %}<i>{{ name[:1] }}</i>{% endif %}</span>
    <a href="https://vk.com/id{{ uid }}">{{ name }}</a>
    <form hx-post="/im/{{ peer_id }}/bot/members/{{ uid }}" hx-target="#bot-panel" hx-swap="outerHTML" hx-trigger="change">
      <label title="Не отвечать этому участнику в этой беседе"><small>игнор</small><input type="checkbox" role="switch" class="sw" name="on" value="1" {{ 'checked' if uid in c.blocked_members }}></label>
    </form></li>{% endfor %}</ul>{% endif %}
</div>
```

- [ ] **Step 4: Run the suite**

Run: `.venv/bin/pytest -q`
Expected: PASS (`test_panel_shows_mode_members_and_switches` still finds «Участники» once and the member checkbox after «Вася Пупкин»).

- [ ] **Step 5: Commit**

```bash
git add web/templates/partials/im_bot.html tests/web/test_im_bot.py
git commit -m "lay out the bot panel as a VK side column"
```

---

### Task 8: Visual verification, fixes, docs

**Files:**
- Modify as needed: `web/static/im.css`, `web/static/im.js`, templates; `README.md` (messenger section)
- Scratchpad: `$S/im_demo.py` (exists), screenshots to `$S/shots/`

**Interfaces:**
- Consumes: everything above; reference screenshots `$S/vk-ref/screenshot-1789322888039-0.jpg` (light) and `…920298-2.jpg` (dark).

- [ ] **Step 1: Start the demo server**

```bash
cd /Users/aklimoff/Documents/ComputerScience/PetProjects/vk-mcp && mkdir -p $S/im-demo/config/personas $S/im-demo/state
printf '# Рина\nперсона\n' > $S/im-demo/config/personas/rina.md
.venv/bin/python -m uvicorn --app-dir $S im_demo:app --port 8765 --log-level warning
```

(run in background; stop it at the end).

- [ ] **Step 2: Playwright pass, desktop light**

With the Playwright MCP tools: `browser_navigate` → `http://localhost:8765/im?sel=2000000001`, `browser_resize` 1440×900, `browser_take_screenshot` → `.playwright-mcp/desk-light.png`. Check against the spec: header 48, nav 164 with blue icons, card r12, list 319, row hover shows the pill (use `browser_hover` on a `.msg`), sticky chip gains the shadow after scrolling up (`browser_run_code_unsafe`: `page.locator('#messages').evaluate(el => el.scrollTop -= 600)`), the «вниз» button appears, the voice wave draws 60 bars, the composer is a shadowed card, «Открыть в VK» and the robot buttons are 32×32.

- [ ] **Step 3: Desktop dark**

`browser_run_code_unsafe`: `await page.emulateMedia({ colorScheme: 'dark' })`, screenshot `desk-dark.png`; confirm page bg `#141414`, card `#222`, composer `#292929`, text `#e1e3e6`, accents `#71aaeb` (`getComputedStyle` via `browser_evaluate`).

- [ ] **Step 4: Bot panel, viewer, empty state**

Click the robot button → the panel is the 320px right column, switches are VK toggles, persona chips highlight when checked; press the × → panel hides. Click the × in the chat header → empty state «Выберите чат» with the 56px icon, URL `/im`. Open a chat with a photo (the demo has none — verify the viewer by `browser_run_code_unsafe` setting `Alpine.$data(document.querySelector('.im-chat')).viewer = 'https://cdn.example/st256.png'` and checking `.im-viewer` is visible, then Esc closes it).

- [ ] **Step 5: Phone 390×844**

Resize to 390×844: list full-width with the footer toggle; burger opens the drawer with the nav, scrim closes it; open a chat: back chevron, rows padded 8/54, composer padding 8, action pill always visible (`page.emulateMedia({ media: null })` cannot fake `hover: none` — check the rule in CSS instead), bot panel full screen. Screenshots `phone-list.png`, `phone-chat.png`, `phone-panel.png`.

- [ ] **Step 6: Fix what differs, re-run the suite, commit**

Apply CSS/JS fixes found in Steps 2–5 (typical: Pico leftovers on `label`, `small`, `button`; `.im-messages > :first-child` on the unread separator; z-order of the pill vs. the sticky chip). Then:

```bash
mv .playwright-mcp/*.png $S/shots/ 2>/dev/null; trash .playwright-mcp 2>/dev/null
.venv/bin/pytest -q
git add -A web/static web/templates && git commit -m "polish the VK look after browser checks"
```

- [ ] **Step 7: README**

In `README.md`, section `### Мессенджер`, add after the layout sentence:

```markdown
Внешний вид повторяет vk.com/im без пузырей: шапка и левое меню как у VK, тёмная тема по системной настройке,
голосовые играют во встроенном плеере с волной, фото открываются в просмотрщике, при открытии чата показывается
разделитель «Непрочитанные сообщения».
```

```bash
git add README.md && git commit -m "describe the VK look of the messenger"
```

- [ ] **Step 8: Finish**

Stop the demo server. Run `.venv/bin/pytest -q` one last time, then use `superpowers:finishing-a-development-branch` (merge to `main` is Aktan's call; deploy only on request).
