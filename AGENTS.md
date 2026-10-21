# vk-ui

Веб-панель агента ВКонтакте [vk-mcp](https://github.com/akklimoff/vk_mcp): статус бота, персоны, промпты, настройки,
доверие, журнал действий, песочница и мессенджер `/im`. Вынесена из vk-mcp 2026-10-21 вместе с историей `web/`.
Пока не выполнен план `docs/superpowers/plans/2026-10-21-vk-ui-split.md`, репозиторий не автономен: пакеты `ai`,
`bot`, `common` берутся из соседнего checkout'а vk-mcp (`../vk-mcp`), в нём же живёт venv.

## Архитектура

- FastAPI + Jinja2 + htmx + Alpine.js + Pico.css, библиотеки вендорятся в `web/static`, сборки фронта нет.
  Отдельный процесс: с ботом общается только через файлы — правит `config/` (`access.json`, `runtime.json`,
  `personas/`), читает `state/` (`status.json`, `actions.jsonl`, `pending.json`, `rejections.json`, `inbox.json`);
  в VK ходит сам через `bot.vk.VkClient`, в LLM — через `ai.client` по `AI_URL`. Любая новая настройка идёт через
  `config/`, а не через общую память с ботом.
- Из ядра vk-mcp панель берёт ровно три группы модулей, и этот список только сокращается:
  форматы файлов (`bot.access`, `bot.runtime`, `bot.status`, `bot.agent.journal`, `bot.agent.rejections`,
  `ai.personas`); решения агента — чистые функции (`bot.agent.gate`, `bot.limits.mention_of`,
  `bot.agent.loop.Limits`); исполнение (`bot.vk`, `bot.agent.loop.run` с `request`, `pictures`, `reply` для
  песочницы, `ai.client`, `ai.catalog`, `bot.config.Settings`, `common.redact`). Из `ai/` — только `contract`,
  `catalog`, `personas`, `client`; `openai` и `vk_api` в `web/` не импортируются.
- Страница = `templates/<page>.html` (обёртка) + `templates/partials/<page>.html` (тело); роут отвечает через
  `render.Renderer`: без заголовка `HX-Request` — полная страница, POST → 303, ошибка → 400; с ним — partial,
  успех с тостом в `HX-Trigger`, ошибка валидации — 422 с баннером и введёнными значениями. Новая страница или
  форма обязана следовать этой схеме.
- `web/trust.py` — единственная запись списков доверия (`agent_users`, `agent_peers`, `peer_prompts`): файл читается
  строго и при чужой форме не перезаписывается. Любая запись в `access.json` и `runtime.json` идёт через
  `web.services.update_config`: чтение, правка и запись под одной блокировкой, иначе две правки подряд теряют
  друг друга. Прав агента в панели нет: они правятся только кодом в `bot/agent/methods.py` vk-mcp.
- `web/dryrun.py` — песочница: цикл агента с `dry_run`, чтения из VK настоящие, записи не выполняются, в журнал
  ничего не попадает. `web/journal.py` — модели журнала, `web/state.py` — статус, ожидающие «да» и причины молчания.
- `web/im/` — мессенджер: `views.py` превращает ответы VK в неизменяемые view-модели (шаблоны знают только их),
  `modes.py` — бейдж «слушает ли агент этот чат» (тот же `gate.rejection`, что в боте) и панель чата,
  `controls.py` — правки `runtime.json` для чата, `voice.py` и `uploads.py` — проверка голосовых и фото по
  сигнатуре, `events.py` — SSE по mtime `state/inbox.json`. Отметка «прочитано» — только кнопкой, открытие чата
  прочитанным его не делает. Ничего из VK не пишется на диск.
- Вход — форма `/login`: cookie сессии (HMAC от пароля, состояния на сервере нет) живёт до «Выйти» или смены
  пароля; Basic Auth с тем же паролем принимается для скриптов; после 5 неверных паролей IP блокируется на 15 минут.
  Без `WEB_PASSWORD` панель не стартует. Наружу видна только через Caddy (HTTPS на `WEB_DOMAIN`).
- Тексты сообщений не попадают в логи; токен VK и ключи вырезаются из всего исходящего (`safe_error`).

## Команды

Пока свой venv не заведён (фаза 1 плана), всё запускается из venv vk-mcp с его пакетами в `PYTHONPATH`:

- Тесты: `PYTHONPATH=../vk-mcp ../vk-mcp/.venv/bin/pytest`
- Локальный запуск: `PYTHONPATH=../vk-mcp WEB_PASSWORD=… ../vk-mcp/.venv/bin/python -m web.app`
  → http://127.0.0.1:8080; пути `ACCESS_FILE`, `RUNTIME_FILE`, `PERSONAS_DIR`, `STATE_DIR` задаются в `.env`
  (по умолчанию относительно текущей папки); для голосовых нужен `ffmpeg` с `libopus`
- Деплой: пока из vk-mcp (`docker compose up -d --build` там, образ `Dockerfile.web`); свой образ — фаза 2 плана

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
