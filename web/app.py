import os
import time

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from bot.access import AccessFile
from bot.config import Settings
from bot.runtime import dump_runtime, parse_runtime, runtime_defaults
from ai.client import AiError, ai_backend
from bot.vk import VkClient
from web.auth import BLOCKED, LOGIN_PATH, WRONG_PASSWORD, Auth, NotLoggedIn, same_site, safe_next, to_login
from web.humanize import clock, mmss, plural, short_since
from web.im.routes import create_router
from web.im.views import presence, preview, wave_bars, when
from ai.personas import list_personas, load_persona
from common.redact import sanitize_reply
from web import dryrun, journal, state, trust
from web.render import Renderer, is_hx
from web.prompts import PromptView, prompt_peers, prompt_view
from web.services import (BrokenConfig, ceilings, load_runtime_dict, model_groups, model_label, new_persona,
                          parse_runtime_form, peer_label, peer_link,
                          runtime_form_values, save_persona, save_runtime_patch, stored_runtime, temperature_of,
                          update_config)

HERE = os.path.dirname(__file__)


def create_app(settings: Settings, vk_factory=VkClient, ai_factory=ai_backend) -> FastAPI:
    if not settings.web_password:
        raise RuntimeError("WEB_PASSWORD не задан")
    auth = Auth(settings.web_password)
    app = FastAPI(dependencies=[Depends(auth.guard)])

    @app.exception_handler(NotLoggedIn)
    async def not_logged_in(request: Request, exc: NotLoggedIn):
        return to_login(request)

    @app.middleware("http")
    async def keep_session(request: Request, call_next):
        response = await call_next(request)
        if getattr(request.state, "session", False) and request.url.path != "/logout":
            auth.remember(request, response)
        return response

    app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")
    render = Renderer(os.path.join(HERE, "templates"), os.path.join(HERE, "static"), peer_label=peer_label, peer_link=peer_link,
                      model_label=model_label, clock=clock, mmss=mmss, plural=plural, preview=preview,
                      since=short_since, presence=presence, wave_bars=wave_bars, when=when)
    app.state.vk = None
    app.state.ai = None

    def vk():
        if app.state.vk is None:
            app.state.vk = vk_factory(settings.vk_token)
        return app.state.vk

    def ai():
        if app.state.ai is None:
            app.state.ai = ai_factory(settings)
        return app.state.ai

    def safe_error(e: Exception) -> str:
        text = str(e) if app.state.ai is None else app.state.ai.scrub(str(e))
        return sanitize_reply(text, (settings.vk_token,))

    app.include_router(create_router(settings, vk, render, safe_error))

    def login_page(request: Request, target: str, error: str = "", status: int = 200) -> Response:
        return render.full(request, "login", {"next": safe_next(target), "error": error, "page": "login"}, status)

    @app.get(LOGIN_PATH)
    def login_form(request: Request, next: str = "/"):
        if auth.has_session(request):
            return RedirectResponse(safe_next(next), status_code=303)
        return login_page(request, next)

    @app.post(LOGIN_PATH)
    def login(request: Request, password: str = Form(""), next: str = Form("/")):
        if not same_site(request):
            raise HTTPException(403, "Запрос с чужого сайта")
        try:
            passed = auth.check(request, password)
        except HTTPException:
            return login_page(request, next, BLOCKED, 429)
        if not passed:
            return login_page(request, next, WRONG_PASSWORD, 401)
        return auth.remember(request, RedirectResponse(safe_next(next), status_code=303))

    @app.post("/logout")
    def logout():
        return auth.forget(RedirectResponse(LOGIN_PATH, status_code=303))

    def models_ctx() -> dict:
        try:
            return {"model_groups": model_groups(ai().models()), "default_model": ai().model_id("")}
        except (AiError, ValueError) as e:
            return {"model_groups": [], "default_model": safe_error(e)}

    def settings_ctx(form: dict) -> dict:
        return {"form": form, "ceilings": ceilings(settings), "page": "settings", **models_ctx()}

    def available_model_ids() -> set[str]:
        try:
            return {m.id for m in ai().models()}
        except (AiError, ValueError):
            return set()

    def trusted_now() -> trust.TrustLists:
        try:
            return trust.load(settings.access_file)
        except ValueError:
            return trust.TrustLists()

    # ники из agent_users разрешаются в id тем же кодом, что у бота, и только при смене файла:
    # статус перерисовывается сам и не должен ходить в VK на каждый опрос
    resolved_access = AccessFile(settings.access_file, lambda names: vk().resolve_screen_names(names))

    def status_ctx():
        view = state.status_view(settings.state_dir, now=time.time(),
                                 runtime=load_runtime_dict(settings.runtime_file), lists=trusted_now(),
                                 trusted_ids=resolved_access.current().agent_users)
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
        try:
            save_runtime_patch(settings.runtime_file, active_persona=slug)
        except BrokenConfig as e:
            return render.invalid(request, "personas", personas_ctx(), str(e))
        return render.saved(request, "personas", personas_ctx(),
                            toast=f"Активна персона «{persona.name}»", redirect="/personas")

    @app.get("/personas/new")
    def new_persona_form(request: Request):
        return render.page(request, "persona_edit", {"persona": None, "form": {}, "page": "personas"})

    @app.post("/personas")
    def create_persona(request: Request, slug: str = Form(), name: str = Form(), prompt: str = Form()):
        slug = slug.strip()
        try:
            new_persona(settings.personas_dir, slug, name, prompt)
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
    def prompts_page(request: Request, peer: str = ""):
        asked = peer.strip()
        peer_id = int(asked) if asked.isascii() and asked.isdigit() else None
        try:
            view = prompt_view(settings, ai(), peer_id)
        except (AiError, ValueError) as e:
            view = PromptView("", "", peer_id, "", safe_error(e), [])
        return render.page(request, "prompts", {"v": view, "peers": prompt_peers(settings), "page": "prompts"})

    @app.get("/settings")
    def settings_page(request: Request):
        defaults = runtime_defaults(settings)
        try:
            rt = stored_runtime(load_runtime_dict(settings.runtime_file), defaults, settings.runtime_file)
        except BrokenConfig as e:
            return render.page(request, "settings", {**settings_ctx(runtime_form_values(defaults)), "error": str(e)})
        return render.page(request, "settings", settings_ctx(runtime_form_values(rt)))

    @app.post("/settings")
    async def save_settings(request: Request):
        form = {k: str(v) for k, v in (await request.form()).items()}
        offered = available_model_ids()

        def change(current: dict) -> dict:
            allowed = offered
            if not allowed:
                # без списка моделей в форме нет выбора, и пустое поле затёрло бы выбранную модель
                form["active_model"] = current.get("active_model", "")
                allowed = {form["active_model"]} - {""}
            entered = parse_runtime_form(form, allowed)
            rt = stored_runtime({**current, **entered}, runtime_defaults(settings), settings.runtime_file)
            return {**current, **dump_runtime(rt)}

        try:
            stored = update_config(settings.runtime_file, change)
        except ValueError as e:
            return render.invalid(request, "settings", settings_ctx(form), str(e))
        rt = parse_runtime(stored, runtime_defaults(settings))
        return render.saved(request, "settings", settings_ctx(runtime_form_values(rt)),
                            toast="Сохранено", redirect="/settings")

    @app.post("/settings/pause")
    def toggle_pause(request: Request):
        paused = not bool(load_runtime_dict(settings.runtime_file).get("paused"))
        try:
            save_runtime_patch(settings.runtime_file, paused=paused)
        except BrokenConfig as e:
            return render.invalid(request, "status", status_ctx(), str(e))
        return render.saved(request, "status", status_ctx(),
                            toast="Агент на паузе" if paused else "Агент снова слушает", redirect="/")

    def trust_ctx(form: dict | None = None, candidate: int | None = None):
        try:
            lists = trust.load(settings.access_file)
        except ValueError as e:
            return {"t": None, "broken": str(e), "form": form or {}, "page": "access"}
        return {"t": trust.trust_view(lists, vk, candidate), "broken": "", "form": form or {}, "page": "access"}

    def trust_change(request: Request, change, toast: str, form: dict | None = None):
        try:
            trust.save(settings.access_file, change)
        except ValueError as e:
            return render.invalid(request, "access", trust_ctx(form), str(e))
        return render.saved(request, "access", trust_ctx(), toast=toast, redirect="/access")

    @app.get("/access")
    def access_page(request: Request, asked: str = Query("", alias="trust")):
        candidate = int(asked) if trust.WHOLE_NUMBER.fullmatch(asked) else None
        return render.page(request, "access", trust_ctx(candidate=candidate))

    @app.post("/access/users")
    def trust_person(request: Request, ref: str = Form("")):
        form = {"user_ref": ref}
        try:
            user_id = trust.user_ref(ref, lambda names: vk().resolve_screen_names(names))
        except ValueError as e:
            return render.invalid(request, "access", trust_ctx(form), str(e))
        return trust_change(request, lambda lists: trust.trust_user(lists, user_id), "Добавлен в доверенные", form)

    @app.post("/access/users/remove")
    def untrust_person(request: Request, ref: str = Form("")):
        def resolve(names):
            return vk().resolve_screen_names(names)

        return trust_change(request, lambda lists: trust.untrust_ref(lists, ref, resolve), "Убран из доверенных")

    @app.post("/access/peers")
    def trust_chat(request: Request, ref: str = Form("")):
        form = {"peer_ref": ref}
        try:
            peer_id = trust.peer_ref(ref)
        except ValueError as e:
            return render.invalid(request, "access", trust_ctx(form), str(e))
        return trust_change(request, lambda lists: trust.trust_peer(lists, peer_id), "Беседа в доверенных", form)

    @app.post("/access/peers/{peer_id}/remove")
    def untrust_chat(request: Request, peer_id: int):
        return trust_change(request, lambda lists: trust.untrust_peer(lists, peer_id), "Беседа убрана из доверенных")

    @app.post("/access/peers/{peer_id}/note")
    def chat_note(request: Request, peer_id: int, text: str = Form("")):
        return trust_change(request, lambda lists: trust.set_note(lists, peer_id, text), "Заметка сохранена")

    @app.get("/journal")
    def journal_page(request: Request, peer: int | None = None, after: float = 0.0):
        everything = journal.read_entries(settings.state_dir)
        entries = [e for e in everything if e.record.ts > after and (peer is None or e.record.peer_id == peer)]
        newest = max((e.record.ts for e in entries), default=after)
        return render.page(request, "journal", {
            "entries": entries, "newest": newest, "now": time.time(), "peer": peer,
            "peers": sorted({e.record.peer_id for e in everything}), "page": "journal"})

    @app.post("/journal/replies/{message_id}/delete")
    def delete_reply(request: Request, message_id: int):
        # удаляется только то, что журнал знает как ответ агента: иначе адрес удалял бы любое сообщение аккаунта
        ids = journal.reply_ids(settings.state_dir, message_id)
        if not ids:
            raise HTTPException(404, "В журнале нет такого ответа")
        try:
            for part in ids:
                vk().delete_message(part)
        except Exception as e:
            raise HTTPException(502, f"VK не удалил сообщение: {safe_error(e)}")
        if is_hx(request):
            return Response('<span class="muted">Ответ удалён в VK</span>', media_type="text/html")
        return RedirectResponse("/journal", status_code=303)

    def sandbox_ctx(**extra):
        runtime = load_runtime_dict(settings.runtime_file)
        return {"personas": list_personas(settings.personas_dir),
                "active": runtime.get("active_persona", ""),
                "active_model": runtime.get("active_model", ""),
                "temperature": runtime.get("temperature", settings.llm_temperature),
                "peers": trusted_now().peers,
                "page": "sandbox", "result": None, "form": {},
                **models_ctx(), **extra}

    @app.get("/sandbox")
    def sandbox_page(request: Request):
        return render.page(request, "sandbox", sandbox_ctx())

    @app.post("/sandbox")
    def sandbox_run(request: Request, text: str = Form(""), peer: str = Form(dryrun.SAVED_PEER),
                    role: str = Form("owner"), persona: str = Form(""), temperature: str = Form(""),
                    model: str = Form("")):
        shown = {"form": {"text": text, "peer": peer.strip(), "role": role, "temperature": temperature},
                 "active": persona, "active_model": model}
        if not text.strip():
            return render.invalid(request, "sandbox", sandbox_ctx(**shown), "Напишите просьбу")
        try:
            temp = temperature_of(temperature.strip()) if temperature.strip() else None
        except ValueError as e:
            return render.invalid(request, "sandbox", sandbox_ctx(**shown), str(e))
        try:
            result = dryrun.dry_run(settings, ai(), vk(), text=text, peer=peer, role=role, persona=persona,
                                    model=model, temperature=temp, safe_error=safe_error)
        except ValueError as e:
            return render.invalid(request, "sandbox", sandbox_ctx(**shown), str(e))
        except Exception as e:
            return render.invalid(request, "sandbox", sandbox_ctx(**shown),
                                  f"Пробный прогон не удался: {safe_error(e)}")
        return render.page(request, "sandbox", sandbox_ctx(result=result, **shown))

    return app


def main() -> None:
    import uvicorn

    # порт наружу не публикуется, до uvicorn доходит только Caddy — его X-Forwarded-For можно доверять
    settings = Settings()
    uvicorn.run(create_app(settings), host=settings.web_host, port=8080,
                proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
