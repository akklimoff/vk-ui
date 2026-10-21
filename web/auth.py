import base64
import binascii
import hashlib
import hmac
import secrets
import threading
import time
from urllib.parse import quote

from fastapi import HTTPException, Request, status
from fastapi.responses import RedirectResponse, Response
from fastapi.security.utils import get_authorization_scheme_param

SESSION_COOKIE = "vk_ui_session"
# браузеры не хранят cookie дольше 400 дней, поэтому срок продлевается при каждом заходе
SESSION_SECONDS = 400 * 24 * 3600
LOGIN_PATH = "/login"
PUBLIC_PATHS = frozenset({LOGIN_PATH})
BLOCKED = "Слишком много неверных попыток, подожди 15 минут"
WRONG_PASSWORD = "Неверный пароль"


class NotLoggedIn(Exception):
    pass


class LoginLimiter:
    """Блокирует IP после серии неверных паролей: иначе пароль перебирается бесконечно."""

    def __init__(self, max_failures: int = 5, block_seconds: float = 900, now=time.time):
        self._max = max_failures
        self._block = block_seconds
        self._now = now
        self._failures: dict[str, list[float]] = {}
        # маршруты идут в пуле потоков: без блокировки пачка одновременных попыток вся проходит проверку
        self._lock = threading.Lock()

    def _recent(self, ip: str) -> list[float]:
        cutoff = self._now() - self._block
        recent = [t for t in self._failures.get(ip, ()) if t > cutoff]
        if recent:
            self._failures[ip] = recent
        else:
            self._failures.pop(ip, None)
        return recent

    def attempt(self, ip: str, right: bool) -> bool | None:
        """Одна попытка входа целиком: None — адрес заблокирован, иначе верен ли пароль."""
        with self._lock:
            recent = self._recent(ip)
            if len(recent) >= self._max:
                return None
            if right:
                self._failures.pop(ip, None)
            else:
                self._failures[ip] = [*recent, self._now()]
            return right


def session_token(password: str) -> str:
    """Значение cookie входа: выводится из пароля, поэтому переживает перезапуск и гаснет при смене пароля."""
    key = hashlib.sha256(password.encode()).digest()
    return hmac.new(key, b"vk-ui session v1", hashlib.sha256).hexdigest()


def client_ip(request: Request) -> str:
    # за Caddy адрес соединения — сам прокси; последний элемент X-Forwarded-For дописывает он, подделать его нельзя
    forwarded = request.headers.get("X-Forwarded-For", "").rpartition(",")[2].strip()
    return forwarded or (request.client.host if request.client else "?")


def same_site(request: Request) -> bool:
    return request.headers.get("Sec-Fetch-Site", "same-origin") in ("same-origin", "none")


def safe_next(target: str | None) -> str:
    """Куда вернуть после входа: только путь этого же сайта."""
    if target and target.startswith("/") and not target.startswith(("//", "/\\")) and "\n" not in target:
        return target
    return "/"


def basic_password(request: Request) -> str | None:
    scheme, param = get_authorization_scheme_param(request.headers.get("Authorization"))
    if scheme.lower() != "basic":
        return None
    try:
        return base64.b64decode(param, validate=True).decode().partition(":")[2]
    except (binascii.Error, UnicodeDecodeError):
        return ""


class Auth:
    """Вход в панель: форма с паролем выдаёт бессрочную cookie; Basic Auth остаётся для скриптов."""

    def __init__(self, password: str, limiter: LoginLimiter | None = None):
        self._password = password
        self._token = session_token(password)
        self._limiter = limiter or LoginLimiter()

    def guard(self, request: Request) -> None:
        if request.url.path in PUBLIC_PATHS:
            return
        # браузер сам прикладывает cookie и Basic Auth к чужим form-POST'ам — отсекаем их по Sec-Fetch-Site
        if request.method != "GET" and not same_site(request):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Запрос с чужого сайта")
        if self.has_session(request):
            request.state.session = True
            return
        typed = basic_password(request)
        if typed is None:
            raise NotLoggedIn()
        if not self.check(request, typed):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Basic"})

    def has_session(self, request: Request) -> bool:
        given = request.cookies.get(SESSION_COOKIE, "")
        return secrets.compare_digest(given.encode(), self._token.encode())

    def check(self, request: Request, typed: str) -> bool:
        right = secrets.compare_digest(typed.encode(), self._password.encode())
        allowed = self._limiter.attempt(client_ip(request), right)
        if allowed is None:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, BLOCKED)
        return allowed

    def remember(self, request: Request, response: Response) -> Response:
        secure = request.headers.get("X-Forwarded-Proto", request.url.scheme) == "https"
        response.set_cookie(SESSION_COOKIE, self._token, max_age=SESSION_SECONDS, httponly=True, secure=secure,
                            samesite="lax", path="/")
        return response

    @staticmethod
    def forget(response: Response) -> Response:
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response


def to_login(request: Request) -> Response:
    """Ответ незалогиненному: страница уходит на форму входа, htmx — туда же, остальным 401 без окна Basic Auth."""
    target = LOGIN_PATH
    if request.method == "GET" and request.headers.get("HX-Request") != "true":
        asked = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        if asked != "/":
            target += f"?next={quote(asked, safe='')}"
        return RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)
    return Response(status_code=status.HTTP_401_UNAUTHORIZED, headers={"HX-Redirect": target})
