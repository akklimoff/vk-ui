import os
import threading

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from web.auth import BLOCKED, LOGIN_PATH, WRONG_PASSWORD, Auth, NotLoggedIn, same_site, safe_next, to_login
from web.config import Settings
from web.humanize import clock, mmss, plural, short_since
from web.im.live import Inbox
from web.im.routes import create_router
from web.im.views import peer_label, peer_link, presence, preview, wave_bars, when
from web.render import Renderer
from web.vk import VkClient

HERE = os.path.dirname(__file__)
REDACTED = "[скрыто]"


def create_app(settings: Settings, vk_factory=VkClient) -> FastAPI:
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
    render = Renderer(os.path.join(HERE, "templates"), os.path.join(HERE, "static"), peer_label=peer_label,
                      peer_link=peer_link, clock=clock, mmss=mmss, plural=plural, preview=preview, since=short_since,
                      presence=presence, wave_bars=wave_bars, when=when)
    app.state.vk = None

    vk_lock = threading.Lock()

    def vk():
        if app.state.vk is None:
            # поток long poll и запросы зовут vk() одновременно, а пауза между вызовами VK — у каждого клиента своя
            with vk_lock:
                if app.state.vk is None:
                    app.state.vk = vk_factory(settings.vk_token)
        return app.state.vk

    def safe_error(e: Exception) -> str:
        return str(e).replace(settings.vk_token, REDACTED) if settings.vk_token else str(e)

    app.state.inbox = Inbox(lambda changed, polled: vk().listen(polled=polled, changed=changed))
    app.include_router(create_router(settings, vk, render, safe_error, app.state.inbox))

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

    @app.get("/")
    def home():
        return RedirectResponse("/im", status_code=303)

    return app


def main() -> None:
    import uvicorn

    # порт панели наружу не публикуется, до uvicorn доходит только Caddy — его X-Forwarded-For можно доверять
    settings = Settings()
    uvicorn.run(create_app(settings), host=settings.web_host, port=8080,
                proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
