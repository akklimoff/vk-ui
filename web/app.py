import os
import time

from fastapi import Depends, FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from bot.config import Settings
from web.auth import make_guard
from web.services import status_view

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

    return app


def main() -> None:
    import uvicorn

    uvicorn.run(create_app(Settings()), host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()
