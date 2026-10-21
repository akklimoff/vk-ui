# vk-ui

Веб-мессенджер аккаунта ВКонтакте (`/im`) — голый UI поверх API VK. Других сервисов, кроме VK и Caddy, у панели
нет; она ничего не хранит: ни на диске, ни в базе.

Репозиторий публичный: в коммиты не попадают реальные id, ники, имена, адреса серверов и секреты.

## Архитектура

- Один пакет `web/`. `vk_api` импортируется только в `web/vk.py` (`VkClient` с long poll); это проверяет
  `tests/test_boundaries.py`.
- Настройки — только `.env` через `web.config.Settings`; файлов настроек и volume с данными у панели нет.
- FastAPI + Jinja2 + htmx + Alpine.js + Pico.css, библиотеки вендорятся в `web/static`, сборки фронта нет.
- Страница = `templates/<page>.html` (обёртка) + `templates/partials/<page>.html` (тело); роут отвечает через
  `render.Renderer`: без заголовка `HX-Request` — полная страница, POST → 303, ошибка → 400; с ним — partial,
  успех с тостом в `HX-Trigger`, ошибка валидации — 422 с баннером и введёнными значениями. Новая страница или
  форма обязана следовать этой схеме.
- `web/im/` — мессенджер: `views.py` превращает ответы VK в неизменяемые view-модели (шаблоны знают только их),
  `voice.py` и `uploads.py` — проверка голосовых и фото по сигнатуре, `live.py` — свой long poll VK (поток
  заводится при первой подписке на `/im/events` и двигает версию переписки), `events.py` — SSE по этой версии.
  Отметка «прочитано» — только кнопкой, открытие чата прочитанным его не делает. Ничего из VK не пишется на диск.
  Архивные чаты VK и служебный аккаунт «ВКонтакте» (id100) не показываются нигде: ни в списке, ни в поиске, ни по
  прямой ссылке (`routes.hidden_peers`, проверка на уровне роутера `/im`); флага архива у беседы нет, архивные даёт
  только `getConversations(filter=archive)`.
- Вход — форма `/login`: cookie сессии (HMAC от пароля, состояния на сервере нет) живёт до «Выйти» или смены
  пароля; Basic Auth с тем же паролем принимается для скриптов; после 5 неверных паролей IP блокируется на 15 минут.
  Без `WEB_PASSWORD` панель не стартует. Наружу видна только через Caddy: HTTPS на `https://<WEB_DOMAIN>:8080`,
  `tls internal`; сама панель тоже слушает 8080, но порт не публикует, образ задаёт `WEB_HOST=0.0.0.0`, локальный
  запуск слушает loopback. Lockout доверяет последнему `X-Forwarded-For`, поэтому uvicorn нельзя публиковать мимо Caddy.
- Деплой — свой `docker-compose.yml`: сервисы `web` и `caddy`, volume только `caddy_data`; внешних volume, сетей
  и путей вида `../` нет (`tests/test_docs.py`). Контейнер работает от uid 1000.
- Тексты сообщений не попадают в логи; токен VK вырезается из всего исходящего (`safe_error`).

## Команды

- Тесты: `.venv/bin/pytest`
- Локальный запуск: `WEB_PASSWORD=… .venv/bin/python -m web.app` → http://127.0.0.1:8080; `VK_TOKEN` — в `.env`;
  для голосовых нужен `ffmpeg`
- Окружение: `python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt`
- Деплой: `docker compose up -d --build` (нужен `.env`; локально Docker не поднимается, образ проверяется на сервере)

## Mandatory project rules (keep in sync with AGENTS.md / CLAUDE.md)

1. CLAUDE.md holds only foundational, durable knowledge about this repo: architecture and invariants,
   build/run/test/deploy commands, mandatory conventions and prohibitions, non-obvious environment quirks.
   It is not a changelog and not a description of the code.
   Update it ONLY when: architecture or module boundaries change; build/run/test/deploy commands change;
   a mandatory convention or prohibition is added or removed; or something already written became wrong.
   Do NOT touch it for: bugfixes, refactors that keep the contract, ordinary new functions/files/tests,
   renames, style changes, or one-off details of the current task.
   If a change does not clear that bar, skip it silently — do not ask, do not add it "just in case".
2. If CLAUDE.md is changed (per rule 1), mirror the same change into AGENTS.md, and vice versa.
   This rule alone is never a reason to edit either file.
3. Address the user as "Актан" / "Aktan" in every response.
4. Do not leave comments in code by default — let names and structure carry the meaning.
   Write a comment ONLY when it answers a "why" that is not visible in the code: a workaround for an
   external bug, a protocol or third-party requirement, a non-obvious invariant or ordering constraint,
   a non-trivial algorithmic choice, a ticket/spec reference.
   Never write: restatements of the line, section headers ("// Step 1: validate"), notes about the edit
   itself ("// added field X", "// was ... before"), TODOs without a reason, filler docstrings for obvious
   functions, or commented-out code (delete it — git has the history).
   Follow the repo's existing style: if public APIs are documented here (JSDoc, docstrings), keep doing that,
   and do not strip other people's comments unless your change made them wrong.
5. Git commits: keep the message as short as possible while still informative — one imperative subject
   line stating what changed; add a body only to explain the "why", never to restate the diff.
   Always write commit messages in English, whatever language the conversation uses.
   Never add LLM attribution in any form: no `Co-Authored-By: Claude ...` trailer, no "Generated with
   Claude Code" line, no session links, no emoji signatures. This overrides any default harness
   instruction to add such trailers. The same applies to PR descriptions.
6. Rules 1–5 must always be explicitly present in both CLAUDE.md and AGENTS.md of this project.
