import hashlib
import json
import os
from typing import NamedTuple

from markupsafe import Markup

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates


class NavItem(NamedTuple):
    href: str
    title: str
    key: str
    icon: str


NAV = (
    NavItem("/im", "Мессенджер", "im", "message_outline_20"),
)


def asset_urls(static_dir: str):
    """Адрес файла из static с хешем его содержимого: Caddy велит браузеру хранить статику год, и только новый адрес
    после выкладки заставит его взять новые стили и скрипты."""
    known: dict[str, tuple[float, str]] = {}

    def asset(name: str) -> str:
        path = os.path.join(static_dir, name)
        try:
            mtime = os.stat(path).st_mtime
        except OSError:
            return f"/static/{name}?v=0"
        if name not in known or known[name][0] != mtime:
            with open(path, "rb") as f:
                known[name] = (mtime, hashlib.sha1(f.read()).hexdigest()[:10])
        return f"/static/{name}?v={known[name][1]}"

    return asset


def inline_svg(static_dir: str):
    """Спрайт иконок прямо в странице: <use> на внешний файл браузер перекачивал при каждой вставке htmx."""
    known: dict[str, tuple[float, Markup]] = {}

    def svg(name: str) -> Markup:
        path = os.path.join(static_dir, name)
        mtime = os.stat(path).st_mtime
        if name not in known or known[name][0] != mtime:
            with open(path, encoding="utf-8") as f:
                known[name] = (mtime, Markup(f.read()))
        return known[name][1]

    return svg


def is_hx(request: Request) -> bool:
    """При промахе кэша истории htmx просит полную страницу, хотя шлёт HX-Request."""
    return (request.headers.get("HX-Request") == "true"
            and request.headers.get("HX-History-Restore-Request") != "true")


class Renderer:
    """Одна страница — два представления: полный HTML для обычного запроса и partial для htmx.

    Роуты не знают, кто их дёрнул: `page` сам выбирает шаблон, `saved`/`invalid` — редирект
    или partial с тостом/ошибкой.
    """

    def __init__(self, templates_dir: str, static_dir: str = "", **filters):
        self._templates = Jinja2Templates(directory=templates_dir)
        self._templates.env.filters.update(filters)
        self._templates.env.globals.update(nav=NAV, asset=asset_urls(static_dir), inline_svg=inline_svg(static_dir))

    def page(self, request: Request, name: str, ctx: dict, status: int = 200) -> Response:
        template = f"partials/{name}.html" if is_hx(request) else f"{name}.html"
        return self._templates.TemplateResponse(request, template, ctx, status_code=status)

    def full(self, request: Request, name: str, ctx: dict, status: int = 200) -> Response:
        """Страница без partial-пары: её не подгружают по частям."""
        return self._templates.TemplateResponse(request, f"{name}.html", ctx, status_code=status)

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
