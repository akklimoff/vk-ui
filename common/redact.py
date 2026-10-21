from typing import Iterable

REDACTED = "[скрыто]"


def sanitize_reply(text: str, secrets: Iterable[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTED)
    return text
