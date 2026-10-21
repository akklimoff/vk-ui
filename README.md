# vk-ui

Веб-панель агента ВКонтакте [vk-mcp](https://github.com/akklimoff/vk_mcp): статус бота, персоны, промпты, настройки,
доверенные люди и беседы, журнал действий агента, песочница (пробный прогон просьбы без записей в VK) и мессенджер
`/im` в облике vk.com — диалоги, история, отправка текста, фото и голосовых, поиск, вложения по типам.

Пакет `web/` вынесен из vk-mcp 2026-10-21 вместе с историей коммитов. Репозиторий пока не автономен: панели нужны
пакеты `ai`, `bot`, `common` из соседнего checkout'а vk-mcp. Как сделать его самостоятельным и развернуть отдельно —
в плане [`docs/superpowers/plans/2026-10-21-vk-ui-split.md`](docs/superpowers/plans/2026-10-21-vk-ui-split.md).

## Запуск сейчас

Рядом должен лежать vk-mcp с заполненным venv (`../vk-mcp/.venv`):

```bash
PYTHONPATH=../vk-mcp ../vk-mcp/.venv/bin/pytest
PYTHONPATH=../vk-mcp WEB_PASSWORD=… ../vk-mcp/.venv/bin/python -m web.app   # http://127.0.0.1:8080
```

Пути к `config/` и `state/` бота задаются в `.env` (`ACCESS_FILE`, `RUNTIME_FILE`, `PERSONAS_DIR`, `STATE_DIR`),
по умолчанию они относительно текущей папки. Для голосовых нужен `ffmpeg` с `libopus`.

В проде панель пока собирается и поднимается из vk-mcp (`Dockerfile.web`, сервисы `web` и `caddy`).
