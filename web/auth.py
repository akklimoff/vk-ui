import secrets
import time
from collections import defaultdict

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

_basic = HTTPBasic()


class LoginLimiter:
    """Блокирует IP после серии неверных паролей: Basic Auth сам по себе перебирается бесконечно."""

    def __init__(self, max_failures: int = 5, block_seconds: float = 900, now=time.time):
        self._max = max_failures
        self._block = block_seconds
        self._now = now
        self._failures: dict[str, list[float]] = defaultdict(list)

    def _recent(self, ip: str) -> list[float]:
        cutoff = self._now() - self._block
        self._failures[ip] = [t for t in self._failures[ip] if t > cutoff]
        return self._failures[ip]

    def blocked(self, ip: str) -> bool:
        return len(self._recent(ip)) >= self._max

    def failed(self, ip: str) -> None:
        self._recent(ip).append(self._now())

    def succeeded(self, ip: str) -> None:
        self._failures.pop(ip, None)


def make_guard(password: str, limiter: LoginLimiter | None = None):
    limiter = limiter or LoginLimiter()

    def guard(request: Request, creds: HTTPBasicCredentials = Depends(_basic)) -> None:
        ip = request.client.host if request.client else "?"
        if limiter.blocked(ip):
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Слишком много неверных попыток, подожди")
        if not secrets.compare_digest(creds.password.encode(), password.encode()):
            limiter.failed(ip)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Basic"})
        limiter.succeeded(ip)
    return guard
