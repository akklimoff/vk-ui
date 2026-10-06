import json
from typing import NamedTuple

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from web.humanize import ago, duration


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
    NavItem("/access", "Доверие", "access", "key_outline_20"),
    NavItem("/settings", "Настройки", "settings", "gear_outline_20"),
    NavItem("/journal", "Журнал", "journal", "reply_outline_20"),
    NavItem("/sandbox", "Песочница", "sandbox", "robot_outline_20"),
)


def is_hx(request: Request) -> bool:
    """При промахе кэша истории htmx просит полную страницу, хотя шлёт HX-Request."""
    return (request.headers.get("HX-Request") == "true"
            and request.headers.get("HX-History-Restore-Request") != "true")


class Renderer:
    """Одна страница — два представления: полный HTML для обычного запроса и partial для htmx.

    Роуты не знают, кто их дёрнул: `page` сам выбирает шаблон, `saved`/`invalid` — редирект
    или partial с тостом/ошибкой.
    """

    def __init__(self, templates_dir: str, **filters):
        self._templates = Jinja2Templates(directory=templates_dir)
        self._templates.env.filters.update({"ago": ago, "duration": duration, **filters})
        self._templates.env.globals["nav"] = NAV

    def page(self, request: Request, name: str, ctx: dict, status: int = 200) -> Response:
        template = f"partials/{name}.html" if is_hx(request) else f"{name}.html"
        return self._templates.TemplateResponse(request, template, ctx, status_code=status)

    def partial(self, request: Request, name: str, ctx: dict, *, toast: str | dict | None = None,
                status: int = 200, push_url: str | None = None) -> Response:
        headers = {}
        if toast:
            headers["HX-Trigger"] = json.dumps({"toast": toast})
        if push_url:
            headers["HX-Push-Url"] = push_url
        return self._templates.TemplateResponse(request, f"partials/{name}.html", ctx,
                                                status_code=status, headers=headers)

    def saved(self, request: Request, name: str, ctx: dict, *, toast: str, redirect: str,
              push_url: str | None = None) -> Response:
        if is_hx(request):
            return self.partial(request, name, ctx, toast=toast, push_url=push_url)
        return RedirectResponse(redirect, status_code=303)

    def invalid(self, request: Request, name: str, ctx: dict, error: str) -> Response:
        if is_hx(request):
            return self.partial(request, name, {**ctx, "error": error}, status=422,
                                toast={"text": error, "kind": "bad"})
        raise HTTPException(400, error)
