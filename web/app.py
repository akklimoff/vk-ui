import os
import time

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from bot.config import Settings
from bot.runtime import dump_runtime, parse_runtime, runtime_defaults
from bot.llm import LlmClient
from bot.status import ReplyLog, write_json_atomic
from bot.vk import VkClient
from web.auth import make_guard
from bot.personas import list_personas, load_persona
from bot.privacy import sanitize_reply
from web.render import Renderer, is_hx
from web.services import (access_form_values, access_raw, load_runtime_dict, parse_access_form,
                          parse_runtime_form, peer_label, peer_link, prompt_view, runtime_form_values,
                          sandbox_reply, save_persona, save_runtime_patch, status_view)

HERE = os.path.dirname(__file__)


def create_app(settings: Settings, vk_factory=VkClient, llm_factory=LlmClient) -> FastAPI:
    if not settings.web_password:
        raise RuntimeError("WEB_PASSWORD не задан")
    guard = make_guard(settings.web_password)
    app = FastAPI(dependencies=[Depends(guard)])
    app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")
    render = Renderer(os.path.join(HERE, "templates"), peer_label=peer_label, peer_link=peer_link)
    app.state.vk = None
    app.state.llm = None

    def vk():
        if app.state.vk is None:
            app.state.vk = vk_factory(settings.vk_token)
        return app.state.vk

    def llm():
        if app.state.llm is None:
            app.state.llm = llm_factory(settings)
        return app.state.llm

    def safe_error(e: Exception) -> str:
        return sanitize_reply(str(e), (settings.vk_token, settings.llm_api_key))

    def status_ctx():
        view = status_view(settings.state_dir, now=time.time(), runtime=load_runtime_dict(settings.runtime_file))
        return {"s": view, "page": "status"}

    @app.get("/")
    def status_page(request: Request):
        return render.page(request, "status", status_ctx())

    def personas_ctx():
        active = load_runtime_dict(settings.runtime_file).get("active_persona", "")
        return {"personas": list_personas(settings.personas_dir), "active": active, "page": "personas"}

    @app.get("/personas")
    def personas_page(request: Request):
        return render.page(request, "personas", personas_ctx())

    @app.post("/personas/{slug}/activate")
    def activate_persona(request: Request, slug: str):
        persona = load_persona(settings.personas_dir, slug)
        if persona is None:
            raise HTTPException(404)
        save_runtime_patch(settings.runtime_file, active_persona=slug)
        return render.saved(request, "personas", personas_ctx(),
                            toast=f"Активна персона «{persona.name}»", redirect="/personas")

    @app.get("/personas/new")
    def new_persona_form(request: Request):
        return render.page(request, "persona_edit", {"persona": None, "form": {}, "page": "personas"})

    @app.post("/personas")
    def create_persona(request: Request, slug: str = Form(), name: str = Form(), prompt: str = Form()):
        slug = slug.strip()
        try:
            save_persona(settings.personas_dir, slug, name, prompt)
        except ValueError as e:
            form = {"slug": slug, "name": name, "prompt": prompt}
            return render.invalid(request, "persona_edit", {"persona": None, "form": form, "page": "personas"}, str(e))
        persona = load_persona(settings.personas_dir, slug)
        return render.saved(request, "persona_edit", {"persona": persona, "page": "personas"},
                            toast=f"Персона «{persona.name}» создана", redirect="/personas",
                            push_url=f"/personas/{slug}/edit")

    @app.get("/personas/{slug}/edit")
    def edit_persona_form(request: Request, slug: str):
        persona = load_persona(settings.personas_dir, slug)
        if persona is None:
            raise HTTPException(404)
        return render.page(request, "persona_edit", {"persona": persona, "page": "personas"})

    @app.post("/personas/{slug}")
    def update_persona(request: Request, slug: str, name: str = Form(), prompt: str = Form()):
        if load_persona(settings.personas_dir, slug) is None:
            raise HTTPException(404)
        save_persona(settings.personas_dir, slug, name, prompt)
        persona = load_persona(settings.personas_dir, slug)
        return render.saved(request, "persona_edit", {"persona": persona, "page": "personas"},
                            toast="Сохранено", redirect="/personas")

    @app.get("/prompts")
    def prompts_page(request: Request, user: str | None = None):
        view = prompt_view(settings, user or None)
        keys = sorted((access_raw(settings.access_file).get("user_prompts") or {}).keys())
        return render.page(request, "prompts", {"v": view, "user_keys": keys, "page": "prompts"})

    @app.get("/settings")
    def settings_page(request: Request):
        rt = parse_runtime(load_runtime_dict(settings.runtime_file), runtime_defaults(settings))
        return render.page(request, "settings", {"form": runtime_form_values(rt), "page": "settings"})

    @app.post("/settings")
    async def save_settings(request: Request):
        form = {k: str(v) for k, v in (await request.form()).items()}
        current = load_runtime_dict(settings.runtime_file)
        try:
            rt = parse_runtime({**current, **parse_runtime_form(form)}, runtime_defaults(settings))
        except ValueError as e:
            return render.invalid(request, "settings", {"form": form, "page": "settings"}, str(e))
        write_json_atomic(settings.runtime_file, {**current, **dump_runtime(rt)})
        return render.saved(request, "settings", {"form": runtime_form_values(rt), "page": "settings"},
                            toast="Сохранено", redirect="/settings")

    @app.post("/settings/pause")
    def toggle_pause(request: Request):
        paused = not bool(load_runtime_dict(settings.runtime_file).get("paused"))
        save_runtime_patch(settings.runtime_file, paused=paused)
        return render.saved(request, "status", status_ctx(),
                            toast="Бот на паузе" if paused else "Бот снова отвечает", redirect="/")

    @app.get("/access")
    def access_page(request: Request):
        return render.page(request, "access", {"v": access_form_values(settings.access_file), "page": "access"})

    @app.post("/access")
    async def save_access(request: Request):
        form = {k: str(v) for k, v in (await request.form()).items()}
        try:
            data = parse_access_form(form)
        except ValueError as e:
            return render.invalid(request, "access", {"v": form, "page": "access"}, str(e))
        write_json_atomic(settings.access_file, data)
        return render.saved(request, "access", {"v": access_form_values(settings.access_file), "page": "access"},
                            toast="Сохранено", redirect="/access")

    @app.get("/replies")
    def replies_page(request: Request, peer: int | None = None, after: float = 0.0):
        all_records = ReplyLog(f"{settings.state_dir}/replies.jsonl").read()
        records = [r for r in all_records if r.ts > after and (peer is None or r.peer_id == peer)]
        newest = max((r.ts for r in records), default=after)
        return render.page(request, "replies", {
            "records": records, "newest": newest, "now": time.time(), "peer": peer,
            "peers": sorted({r.peer_id for r in all_records}), "page": "replies"})

    @app.post("/replies/{reply_message_id}/delete")
    def delete_reply(request: Request, reply_message_id: int):
        try:
            vk().delete_message(reply_message_id)
        except Exception as e:
            raise HTTPException(502, f"VK не удалил сообщение: {safe_error(e)}")
        if is_hx(request):
            return Response(status_code=200)
        return RedirectResponse("/replies", status_code=303)

    def sandbox_ctx(**extra):
        active = load_runtime_dict(settings.runtime_file).get("active_persona", "")
        return {"personas": list_personas(settings.personas_dir), "active": active,
                "page": "sandbox", "result": None, "context": "", "form": None, **extra}

    @app.get("/sandbox")
    def sandbox_page(request: Request):
        return render.page(request, "sandbox", sandbox_ctx())

    @app.post("/sandbox")
    def sandbox_run(request: Request, persona: str = Form(""), conversation: str = Form(""),
                    peer_id: str = Form(""), count: str = Form("40"), asker: str = Form("Собеседник"),
                    temperature: str = Form("0.8")):
        form = {"conversation": conversation, "peer_id": peer_id, "count": count,
                "asker": asker, "temperature": temperature}
        try:
            pid = int(peer_id) if peer_id.strip() else None
            temp = float(temperature)
            n = int(count)
        except ValueError:
            return render.invalid(request, "sandbox", sandbox_ctx(), "peer_id, count и temperature должны быть числами")
        try:
            context, reply = sandbox_reply(settings, llm(), vk() if pid is not None else None,
                                           persona_slug=persona, conversation=conversation, peer_id=pid,
                                           count=n, asker=asker, temperature=temp)
        except Exception as e:
            return render.invalid(request, "sandbox", sandbox_ctx(), f"Не удалось получить ответ: {safe_error(e)}")
        return render.page(request, "sandbox", sandbox_ctx(result=reply, context=context, active=persona, form=form))

    return app


def main() -> None:
    import uvicorn

    # порт наружу не публикуется, до uvicorn доходит только Caddy — его X-Forwarded-For можно доверять
    uvicorn.run(create_app(Settings()), host="0.0.0.0", port=8080,
                proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
