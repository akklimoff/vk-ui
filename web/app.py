import os
import time

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from bot.config import Settings, parse_ids
from bot.runtime import dump_runtime, parse_runtime, runtime_defaults
from bot.status import write_json_atomic
from web.auth import make_guard
from bot.personas import list_personas, load_persona
from web.services import (access_raw, load_runtime_dict, prompt_view, save_persona,
                          save_runtime_patch, status_view)

HERE = os.path.dirname(__file__)


def create_app(settings: Settings) -> FastAPI:
    if not settings.web_password:
        raise RuntimeError("WEB_PASSWORD не задан")
    guard = make_guard(settings.web_password)
    app = FastAPI(dependencies=[Depends(guard)])
    app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")
    templates = Jinja2Templates(directory=os.path.join(HERE, "templates"))

    @app.get("/")
    def status_page(request: Request):
        view = status_view(settings.state_dir, now=time.time())
        return templates.TemplateResponse(request, "status.html", {"s": view, "page": "status"})

    @app.get("/personas")
    def personas_page(request: Request):
        active = load_runtime_dict(settings.runtime_file).get("active_persona", "")
        return templates.TemplateResponse(request, "personas.html",
            {"personas": list_personas(settings.personas_dir), "active": active, "page": "personas"})

    @app.post("/personas/{slug}/activate")
    def activate_persona(slug: str):
        if load_persona(settings.personas_dir, slug) is None:
            raise HTTPException(404)
        save_runtime_patch(settings.runtime_file, active_persona=slug)
        return RedirectResponse("/personas", status_code=303)

    @app.get("/personas/new")
    def new_persona_form(request: Request):
        return templates.TemplateResponse(request, "persona_edit.html",
            {"persona": None, "page": "personas"})

    @app.post("/personas")
    def create_persona(slug: str = Form(), name: str = Form(), prompt: str = Form()):
        try:
            save_persona(settings.personas_dir, slug.strip(), name, prompt)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return RedirectResponse("/personas", status_code=303)

    @app.get("/personas/{slug}/edit")
    def edit_persona_form(request: Request, slug: str):
        persona = load_persona(settings.personas_dir, slug)
        if persona is None:
            raise HTTPException(404)
        return templates.TemplateResponse(request, "persona_edit.html",
            {"persona": persona, "page": "personas"})

    @app.post("/personas/{slug}")
    def update_persona(slug: str, name: str = Form(), prompt: str = Form()):
        if load_persona(settings.personas_dir, slug) is None:
            raise HTTPException(404)
        save_persona(settings.personas_dir, slug, name, prompt)
        return RedirectResponse("/personas", status_code=303)

    @app.get("/prompts")
    def prompts_page(request: Request, user: str | None = None):
        view = prompt_view(settings, user or None)
        keys = sorted((access_raw(settings.access_file).get("user_prompts") or {}).keys())
        return templates.TemplateResponse(request, "prompts.html",
            {"v": view, "user_keys": keys, "page": "prompts"})

    @app.get("/settings")
    def settings_page(request: Request):
        rt = parse_runtime(load_runtime_dict(settings.runtime_file), runtime_defaults(settings))
        return templates.TemplateResponse(request, "settings.html", {"rt": rt, "page": "settings"})

    @app.post("/settings")
    def save_settings(temperature: str = Form(), reply_delay_min: str = Form(), reply_delay_max: str = Form(),
                      context_messages: str = Form(), paused_peers: str = Form("")):
        current = load_runtime_dict(settings.runtime_file)
        try:
            rt = parse_runtime({**current, "temperature": temperature, "reply_delay_min": reply_delay_min,
                                "reply_delay_max": reply_delay_max, "context_messages": context_messages,
                                "paused_peers": sorted(parse_ids(paused_peers))},
                               runtime_defaults(settings))
        except ValueError as e:
            raise HTTPException(400, str(e))
        write_json_atomic(settings.runtime_file, {**current, **dump_runtime(rt)})
        return RedirectResponse("/settings", status_code=303)

    @app.post("/settings/pause")
    def toggle_pause():
        current = load_runtime_dict(settings.runtime_file)
        save_runtime_patch(settings.runtime_file, paused=not bool(current.get("paused")))
        return RedirectResponse("/", status_code=303)

    return app


def main() -> None:
    import uvicorn

    uvicorn.run(create_app(Settings()), host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()
