# Вынос веб-панели из vk-mcp в репозиторий vk-ui — план

Дата: 2026-10-21. Статус: решения приняты, выполняется.

> Правка 2026-10-21 (решение Актана): vk-ui должен быть полностью отдельным и никак не связан с vk-mcp. Решение 1
> отменено: вместо зависимости — своя копия ядра (`bot/`, `ai/`, `common/`, снимок 4e0382a) с его тестами;
> `../vk-mcp` нигде не используется, compose берёт данные бота по переменным `.env` (`BOT_CONFIG_DIR`,
> `BOT_STATE_VOLUME`, `BOT_NETWORK`). Фаза 1 без `pyproject.toml` в vk-mcp: у vk-ui свои `requirements.txt` и venv.
> Фаза 2 без второго build-контекста: образ собирается из своего дерева. Фаза 4 снимается: web-настройки, версия
> ядра и список импортов — внутреннее дело vk-ui; остаётся правило из «Рисков»: форматы файлов и `gate` меняются
> парой коммитов в обоих репозиториях.

> Правка 2026-10-21, вторая (решение Актана): vk-ui работает совсем без бота. Убраны страницы «Статус» и «Журнал»,
> ожидающие «да», причины молчания и метки ответов агента в `/im`; мессенджер получает новое по своему long poll VK
> (`web/im/live.py`), LLM — только в процессе панели (`AI_URL` и HTTP-клиент удалены), `state/` не читается.
> Compose — `web` + `caddy` со своим volume `config`, без внешних volume и сетей; Caddy отдаёт HTTPS на порту 8080.
> Фазы 2–3 ниже и раздел «Риски» про общие форматы файлов больше не действуют.

> Правка 2026-10-21, третья (решение Актана): vk-ui — голый мессенджер VK без агента и ИИ. Ядро (`bot/`, `ai/`,
> `common/`), страницы персон, промпта, доверия, настроек и песочницы, бейдж и панель агента в `/im` удалены;
> клиент VK — `web/vk.py`, настройки — только `.env`, volume `config` снят. Весь план ниже — история.

## Что уже сделано (фаза 0)

- `web/`, `tests/web/` и четыре документа по панели (планы web-admin, web-messenger, vk-im-redesign и спека редизайна)
  вырезаны из vk-mcp (`agent` = `origin/main`, 4e0382a от 2026-10-18) с полной историей через `git filter-repo`:
  88 коммитов начиная с 2026-08-26.
- Репозиторий на GitHub публичный, исходный vk-mcp — приватный, поэтому история вычищена: IP сервера заменён на
  `SERVER_IP`, id и имя аккаунта в примере `status.json` старого плана — на `100000001` и «Валентина Тестова»;
  план `2026-10-06-agent-admin.md` не перенесён (в нём команды деплоя на сервер). Email автора во всех коммитах
  заменён на GitHub-noreply.
- Все 475 тестов `tests/web` проходят из нового репо при `PYTHONPATH=../vk-mcp`: вырезано всё, что нужно панели.

## Исходная картина

- Размер: ~2,5 тыс. строк Python (`web/`, `web/im/`), ~650 строк шаблонов, ~1 тыс. строк JS/CSS плюс вендоренные
  htmx, Alpine.js, Pico.css.
- Панель импортирует из vk-mcp 20 модулей, они делятся на три группы:
  - форматы файлов `config/` и `state/`: `bot.access`, `bot.runtime`, `bot.status`, `bot.agent.journal`,
    `bot.agent.rejections`, `ai.personas`;
  - решения агента (чистые функции): `bot.agent.gate`, `bot.limits.mention_of`, `bot.agent.loop.Limits`;
  - исполнение: `bot.vk.VkClient` (мессенджер, «Доверие», удаление ответа), `bot.agent.loop.run` вместе с
    `bot.agent.request`, `bot.agent.pictures`, `bot.reply` (песочница — dry-run цикла агента в процессе панели),
    `ai.client`, `ai.catalog`, `bot.config.Settings`, `common.redact`.
  Транзитивно это почти весь `bot/` (кроме `main`, `worker`, `names`, `privacy`), весь `common/` и
  `ai/{client,catalog,personas,contract}`. Тесты дополнительно поднимают `ai.service` с фейковой моделью.
- Деплой сейчас: образ `web` собирается из дерева vk-mcp (`Dockerfile.web` копирует `bot`, `ai`, `common`, `web`),
  перед ним `caddy`; `config/` — bind mount на запись, `state` — named volume только на чтение,
  `AI_URL=http://ai:8090`, общий `.env`. На сервере нет доступа к GitHub: деплой идёт git-bundle'ами в `/root/vk_mcp`.
- vk-mcp ссылается на панель в `tests/test_boundaries.py`, `tests/test_docs.py`, README, CLAUDE.md/AGENTS.md,
  `.env.example`, `docker-compose.yml`, `Dockerfile.web`, `Caddyfile`.

## Решения

Пункты 1–3 — мой выбор, их легко отменить до фазы 1. Пункт 4 — решение Актана.

### 1. Общий код: vk-mcp как библиотека, а не копия и не HTTP API

| Вариант | За | Против |
|---|---|---|
| **A. vk-mcp — зависимость vk-ui** (выбран) | один источник правды для форматов файлов, фильтра и цикла агента; изменения ядра не дублируются; переписывать нечего | нужны два checkout'а рядом (локально и на сервере); версия ядра фиксируется неявно — тем, что лежит в `../vk-mcp` |
| B. Скопировать нужные модули в vk-ui | репозиторий автономен сразу | ~3,5 тыс. строк дублей; `gate`, `policy`, форматы `access.json`, `runtime.json` и журнала разъедутся при первом же изменении |
| C. HTTP API между ботом и панелью | честная граница; панель можно переписать на SPA | боту нужен API-сервер: статус, журнал, ожидающие «да», правки `config/`, прокси VK для мессенджера, dry-run; ломает инвариант «панель общается с ботом только через файлы»; недели работы |

Выбран **A**; **C** — направление на случай, если панель станет самостоятельным фронтендом. Чтобы A не выродился
в «панель знает всё о боте», в vk-ui живёт тест границы с явным списком модулей ядра, которые ей можно
импортировать (три группы выше); список только сокращается.

### 2. Пакет остаётся `web`

Переименование в `vkui` — правка 95 файлов без выгоды; внутри репозитория vk-ui имя `web` ни с чем не конфликтует.

### 3. Caddy переезжает в vk-ui

Caddy нужен только панели. Compose vk-ui поднимает `web` и `caddy` и подключается к сети и volume `state` проекта
`vk_mcp` как к внешним. Compose vk-mcp остаётся с `ai` и `bot`.

### 4. Публичность репозитория

Репозиторий создан публичным. История вычищена (см. фазу 0), в фикстурах и доках — только вымышленные имена и id.
Если панель должна остаться непубличной: `gh repo edit akklimoff/vk-ui --visibility private`.

## Фазы

### Фаза 1 — vk-ui тестируется и запускается локально

В vk-mcp одно изменение, код не переносится:

1. `pyproject.toml`: `name = "vk-mcp"`, `dependencies` — то же, что `requirements.txt`,
   `[tool.setuptools.packages.find] include = ["ai*", "bot*", "common*"]`. Проверка: в чистом venv
   `pip install -e .` и `python -c "import bot.vk, ai.client"`; тесты vk-mcp по-прежнему зелёные.

В vk-ui:

2. `requirements.txt`: `-e ../vk-mcp`, `fastapi`, `uvicorn`, `jinja2`, `python-multipart`, `httpx`;
   `requirements-dev.txt`: `-r requirements.txt`, `pytest`. Свой `.venv`.
3. `tests/test_boundaries.py` для vk-ui: разрешённые импорты из ядра — явный список из «Исходной картины»;
   `ai/` — только `contract`, `catalog`, `personas`, `client`; `openai` и `vk_api` в `web/` не импортируются.
   Сюда же переезжает проверка «панель слушает loopback локально и `0.0.0.0` в образе» из `tests/test_docs.py`
   vk-mcp (после фазы 2, когда появятся свой Dockerfile и Caddyfile).
4. Прогон: `.venv/bin/pytest` — 475 зелёных; `WEB_PASSWORD=… .venv/bin/python -m web.app` открывает страницы
   на данных соседнего checkout'а: в `.env` vk-ui пути `ACCESS_FILE`, `RUNTIME_FILE`, `PERSONAS_DIR`, `STATE_DIR`
   указывают в `../vk-mcp/…`.
5. README vk-ui: разделы «Веб-панель» и «Мессенджер» из README vk-mcp переезжают сюда; команды из п. 4.
   CLAUDE.md/AGENTS.md: команды меняются с `PYTHONPATH=../vk-mcp` на свой venv.

### Фаза 2 — образ и деплой из vk-ui

6. `Dockerfile` (из `Dockerfile.web`): ядро берётся из второго build-контекста —
   `COPY --from=core ai ./ai`, `bot`, `common`, `requirements.txt`; `pip install` обоих requirements.
   Нужны BuildKit и Compose ≥ 2.17 (`build.additional_contexts`) — до начала проверить на сервере
   `docker compose version`. Запасной путь, если старше: скрипт `build.sh`, копирующий ядро в `core/`
   (в `.gitignore`) перед `docker compose build`.
7. `docker-compose.yml` vk-ui: `web` (`env_file: ../vk_mcp/.env` — потолки `AGENT_*` на странице настроек
   должны совпадать с ботом, поэтому `.env` общий; `AI_URL=http://ai:8090`; volumes `../vk_mcp/config:/app/config`
   и `vk_mcp_state:/app/state:ro`; network `vk_mcp_default`, оба `external: true`) и `caddy` из compose vk-mcp;
   `Caddyfile` переезжает. Имя проекта на сервере — `vk-ui`.
8. Деплой: bundle vk-ui → `/root/vk-ui`. В `/root/vk_mcp`: `docker compose stop caddy web` (освобождается 443).
   В `/root/vk-ui`: `docker compose up -d --build`. Проверка `https://<WEB_DOMAIN>`: вход, статус, `/im` получает
   SSE от бота, песочница делает dry-run. Откат — `docker compose up -d` в `/root/vk_mcp`. Локально Docker не
   поднимается (решение Актана), образ проверяется только на сервере.
9. Порядок при изменениях ядра: сначала bundle vk-mcp и `up -d --build` там, затем `up -d --build` в vk-ui —
   образ панели пересобирается из нового ядра.

### Фаза 3 — vk-mcp без панели

10. Удалить `web/`, `tests/web/`, `Dockerfile.web`, `Caddyfile`, сервисы `web` и `caddy` из compose;
    на сервере `docker compose up -d --remove-orphans`.
11. Тесты vk-mcp: `test_boundaries` — убрать `web` из списков пакетов (правило для `evals` остаётся),
    в `test_old_evals_and_the_bot_side_of_the_old_reply_path_are_gone` заменить импорт `web.im.views`;
    `test_docs` — убрать `test_panel_listens_on_loopback…` (переехал в vk-ui);
    `test_readme_names_only_settings_that_exist` — `WEB_DOMAIN` остаётся, пока `WEB_*` живут в `Settings`.
12. README vk-mcp: раздел «Веб-панель» → ссылка на vk-ui. `.env.example`: `WEB_*` остаются (их читает
    `bot.config.Settings`) с пометкой, что панель живёт в vk-ui. CLAUDE.md/AGENTS.md: убрать `web/` из слоёв и
    описания, добавить абзац про vk-ui и общий контракт (файлы `config/`, `state/` и список модулей ядра, на которые
    опирается панель) — это смена границ модулей, порог правила 1 пройден.
13. Bundle → сервер → `docker compose up -d --build` в `/root/vk_mcp`.

### Фаза 4 — сужение контракта (по желанию, по одному шагу)

- `web_password` и `web_host` из `bot.config.Settings` → `web.config.WebSettings(Settings)` в vk-ui
  (`web_timezone` остаётся в ядре: бот берёт из него «сейчас» для фактов просьбы).
- Явная фиксация версии ядра: `core` как git submodule на vk_mcp (на сервере
  `git config submodule.core.url /root/vk_mcp`) или метка `CORE_SHA` в образе — когда захочется деплоить vk-ui
  без одновременного обновления vk-mcp.
- Список разрешённых импортов из ядра сокращается: форматы файлов (`access`, `runtime`, `status`, `journal`,
  `rejections`, `personas`) собираются в один модуль-контракт в vk-mcp.
- Если панель пойдёт в сторону SPA — вариант C: API бота, `/im` через прокси VK в боте.

## Что не меняется

- Панель общается с ботом только через `config/` (правит) и `state/` (читает); в VK и LLM ходит сама
  (`VkClient`, `AiClient`). Инварианты про `update_config`, `trust.py` и `Renderer` переезжают в CLAUDE.md vk-ui.
- Права агента правятся только в `bot/agent/methods.py` vk-mcp; у панели их нет и не будет.

## Риски

- Одно изменение формата (`runtime.json`, журнал, `gate`) — два репозитория. Пока ядро не версионировано,
  правило: `main` vk-ui тестируется против `main` vk-mcp того же дня; правки формата идут парой коммитов,
  деплой — ядро первым.
- Compose на сервере может не знать `additional_contexts` — проверить до фазы 2 (п. 6, запасной путь назван).
- Простой панели при переключении Caddy — минуты; бот не затрагивается.
- Публичный репозиторий: в будущих коммитах не класть реальные id, ники, имена и адреса сервера.

## Проверка готовности

- Фаза 1: `pytest` в vk-ui зелёный; панель открывается локально на данных из `../vk-mcp`.
- Фаза 2: `https://<WEB_DOMAIN>` обслуживается контейнером из `/root/vk-ui`; `/im` получает SSE; песочница работает.
- Фаза 3: `pytest` в vk-mcp зелёный без `web/`; `docker compose ps` в `vk_mcp` показывает только `ai` и `bot`;
  CLAUDE.md и AGENTS.md в обоих репозиториях совпадают.
