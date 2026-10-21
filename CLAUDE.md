# vk-ui

Веб-панель агента ВКонтакте [vk-mcp](https://github.com/akklimoff/vk_mcp): статус бота, персоны, промпт, настройки,
доверие, журнал действий, песочница и мессенджер `/im`. Отдельный сервис со своим образом и своим репозиторием;
от vk-mcp не зависит ни кодом, ни сборкой: нужное панели ядро агента лежит здесь. С ботом делит только данные —
его `config/` (панель правит), `state/` (панель читает) и docker-сеть, где виден сервис `ai`.

Репозиторий публичный: в коммиты не попадают реальные id, ники, имена, адреса серверов и секреты.

## Архитектура

- Три слоя с однонаправленными зависимостями: `web/` → `ai/`, `bot/` → `common/`. Граница проверяется
  `tests/test_boundaries.py`.
- `bot/`, `ai/`, `common/` — ядро агента, снимок vk-mcp 4e0382a (2026-10-18), с его тестами в `tests/`; теперь это код
  vk-ui, но форматы файлов и решения в нём — контракт с ботом: `config/access.json` (`bot/access.py`),
  `config/runtime.json` (`bot/runtime.py`), `config/personas/*.md` (`ai/personas.py`), `state/status.json`,
  `inbox.json`, `pending.json` (`bot/status.py`), `state/actions.jsonl` (`bot/agent/journal.py`),
  `state/rejections.json` (`bot/agent/rejections.py`) и фильтр `bot/agent/gate.py`, по которому панель судит, слушает
  ли агент чат. Менять их можно только вместе с ботом, иначе панель прочитает его файлы неверно.
  Самого бота здесь нет и быть не должно: ни long poll (`bot/main.py`), ни очереди просьб (`bot/agent/worker.py`),
  ни HTTP-сервиса ИИ (`ai/http.py`) — тест границ это проверяет.
- Что панель берёт из ядра — явный список `CORE_FOR_PANEL` в `tests/test_boundaries.py`: форматы файлов, решения
  агента (`gate`, `limits.mention_of`, `loop.Limits`) и исполнение (`bot.vk.VkClient`, цикл `bot.agent.loop.run`
  с `request`, `pictures`, `reply` для песочницы, `ai.client`, `ai.catalog`, `bot.config.Settings`, `common.redact`).
  Из `ai/` панель и ядро берут только `contract`, `catalog`, `personas`, `client`; `ai.service`, `ai.llm`, `ai.claude`
  нужны, чтобы без `AI_URL` LLM работал в процессе (так же работают тесты). Ключи и промпты LLM — только
  в `ai.config.AiSettings`; `bot.config.Settings` их не знает. `openai` импортируется только в `ai/llm.py`,
  `vk_api` — только в `bot/vk.py`.
- FastAPI + Jinja2 + htmx + Alpine.js + Pico.css, библиотеки вендорятся в `web/static`, сборки фронта нет. Любая
  новая настройка идёт через `config/`, а не через общую память с ботом.
- Страница = `templates/<page>.html` (обёртка) + `templates/partials/<page>.html` (тело); роут отвечает через
  `render.Renderer`: без заголовка `HX-Request` — полная страница, POST → 303, ошибка → 400; с ним — partial,
  успех с тостом в `HX-Trigger`, ошибка валидации — 422 с баннером и введёнными значениями. Новая страница или
  форма обязана следовать этой схеме.
- `web/trust.py` — единственная запись списков доверия (`agent_users`, `agent_peers`, `peer_prompts`): файл читается
  строго и при чужой форме не перезаписывается. Любая запись в `access.json` и `runtime.json` идёт через
  `web.services.update_config`: чтение, правка и запись под одной блокировкой, иначе две правки подряд теряют
  друг друга. Прав агента в панели нет: они живут в `bot/agent/methods.py` бота и правятся только там.
- `web/dryrun.py` — песочница: цикл агента с `dry_run`, чтения из VK настоящие, записи не выполняются, в журнал
  ничего не попадает. `web/journal.py` — модели журнала, `web/state.py` — статус, ожидающие «да» и причины молчания.
- `web/im/` — мессенджер: `views.py` превращает ответы VK в неизменяемые view-модели (шаблоны знают только их),
  `modes.py` — бейдж «слушает ли агент этот чат» (тот же `gate.rejection`, что в боте) и панель чата,
  `controls.py` — правки `runtime.json` для чата, `voice.py` и `uploads.py` — проверка голосовых и фото по
  сигнатуре, `events.py` — SSE по mtime `state/inbox.json`. Отметка «прочитано» — только кнопкой, открытие чата
  прочитанным его не делает. Ничего из VK не пишется на диск.
- Вход — форма `/login`: cookie сессии (HMAC от пароля, состояния на сервере нет) живёт до «Выйти» или смены
  пароля; Basic Auth с тем же паролем принимается для скриптов; после 5 неверных паролей IP блокируется на 15 минут.
  Без `WEB_PASSWORD` панель не стартует. Наружу видна только через Caddy (HTTPS на `WEB_DOMAIN`, `tls internal`,
  порт 443); сама панель порт не публикует, образ задаёт `WEB_HOST=0.0.0.0`, локальный запуск слушает loopback.
- Деплой — свой `docker-compose.yml`: сервисы `web` и `caddy`; `config/` бота, volume со `state/` и сеть с `ai`
  подключаются как внешние по переменным `.env` (`BOT_CONFIG_DIR`, `BOT_STATE_VOLUME`, `BOT_NETWORK`); пути вида `../`
  в compose и Dockerfile запрещены (`tests/test_docs.py`). Контейнер работает от uid 1000 и пишет в `config/` бота.
  Потолки агента (`AGENT_*`, лимиты частоты) панель показывает из своего `.env`: они должны совпадать с `.env` бота.
- Тексты сообщений не попадают в логи; токен VK и ключи вырезаются из всего исходящего (`safe_error`).

## Команды

- Тесты: `.venv/bin/pytest`
- Локальный запуск: `WEB_PASSWORD=… .venv/bin/python -m web.app` → http://127.0.0.1:8080; пути к данным бота
  (`ACCESS_FILE`, `RUNTIME_FILE`, `PERSONAS_DIR`, `STATE_DIR`) и `AI_URL` — в `.env`; для голосовых нужен `ffmpeg`
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
