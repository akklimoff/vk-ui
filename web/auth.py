import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

_basic = HTTPBasic()


def make_guard(password: str):
    def guard(creds: HTTPBasicCredentials = Depends(_basic)) -> None:
        if not secrets.compare_digest(creds.password.encode(), password.encode()):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Basic"})
    return guard
