from typing import Sequence

from bot.limits import strip_self_mention
from common.commands import looks_like_command
from common.redact import sanitize_reply

# бот пишет от имени владельца: ответ LLM, похожий на команду, исполнил бы модератор на этом же аккаунте
DEFUSE = "\u200b"


def defused(part: str) -> str:
    return DEFUSE + part if looks_like_command(part) else part


def deliverable(parts: Sequence[str], secrets: Sequence[str], me_id: int | None) -> list[str]:
    """Части ответа ИИ, готовые к отправке в VK: без токена, без разметки своего тега и без видимости команды."""
    cleaned = (scrubbed(part, secrets, me_id).strip() for part in parts)
    return [defused(part) for part in cleaned if part]


def scrubbed(part: str, secrets: Sequence[str], me_id: int | None) -> str:
    # токен скрывается и после снятия тега: «ток[id1|]ен» без тега снова собирается в целый токен
    return sanitize_reply(strip_self_mention(sanitize_reply(part, secrets), me_id), secrets)
