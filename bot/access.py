import json
import logging
import re
from dataclasses import dataclass, field

from bot.config import parse_user_refs
from common.hotfile import PartialRead, WatchedFile

log = logging.getLogger("vk-bot")

# str.isdigit пропускает «²» и «٣», а int() на «²» и на числе длиннее 4300 цифр бросает ValueError
WHOLE_NUMBER = re.compile(r"[0-9]{1,18}")
NICK = re.compile(r"[a-z0-9_.]+")
# так VK отвечает на users.get с единственным ником, которого нет
NO_SUCH_USER_CODE = 113


@dataclass(frozen=True)
class AccessLists:
    agent_users: frozenset[int] = frozenset()
    agent_peers: frozenset[int] = frozenset()
    peer_prompts: dict[int, str] = field(default_factory=dict)


class Nicks:
    """Чьи ники. Каждый спрашивается у VK отдельно: users.get на несуществующий ник отвечает ошибкой
    на весь запрос, и один мёртвый ник лишил бы ответа остальные.

    Ник, которого нет, не даёт доверия никому. Ник, про который VK не ответил, значит то же, что при
    последнем ответе, а раньше не спрошенный — никого: так сбой сети не выдаёт новых прав и не мешает
    вступить в силу тому, что из файла убрано."""

    def __init__(self, resolve_screen_names):
        self._resolve = resolve_screen_names
        self._answers: dict[str, frozenset[int]] = {}

    def owners(self, names) -> tuple[frozenset[int], bool]:
        answers: dict[str, frozenset[int]] = {}
        all_answered = True
        for name in sorted(names):
            try:
                answers[name] = frozenset(self._resolve(frozenset({name})))
            except Exception as error:
                if getattr(error, "code", None) == NO_SUCH_USER_CODE:
                    answers[name] = frozenset()
                else:
                    all_answered = False
                    if name in self._answers:
                        answers[name] = self._answers[name]
                    # текст ошибки VK может содержать адрес запроса с токеном
                    log.warning("VK не ответил про ник @%s (%s): новых прав он пока не даёт",
                                name, type(error).__name__)
                    continue
            if not answers[name]:
                log.warning("Ник @%s из agent_users не найден в VK и доверия никому не даёт", name)
        self._answers = answers
        return frozenset().union(*answers.values()), all_answered


def join_lines(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "\n".join(str(item) for item in value).strip()
    return str(value).strip()


def listed(data: dict, key: str) -> list:
    value = data.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        log.warning("В списках доступа %s должен быть списком, пропущен", key)
        return []
    return value


def agent_user_ids(data: dict, nicks: Nicks) -> tuple[frozenset[int], bool]:
    refs = [str(item) for item in listed(data, "agent_users")
            if isinstance(item, (int, str)) and not isinstance(item, bool)]
    ids, names = parse_user_refs(" ".join(refs))
    usable = frozenset(name for name in names if NICK.fullmatch(name))
    if len(usable) < len(names):
        log.warning("В agent_users пропущена запись, которая не является ни id, ни ником")
    owners, all_answered = nicks.owners(usable)
    return ids | owners, all_answered


def agent_peer_ids(data: dict) -> frozenset[int]:
    found = set()
    for item in listed(data, "agent_peers"):
        if (isinstance(item, bool) or not isinstance(item, (int, str))
                or not WHOLE_NUMBER.fullmatch(str(item).strip())):
            log.warning("В agent_peers пропущена запись, которая не является номером беседы")
            continue
        found.add(int(str(item).strip()))
    return frozenset(found)


def peer_notes(data: dict) -> dict[int, str]:
    raw = data.get("peer_prompts")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        log.warning("В списках доступа peer_prompts должен быть объектом, пропущен")
        return {}
    notes: dict[int, str] = {}
    for ref, value in raw.items():
        if not WHOLE_NUMBER.fullmatch(str(ref).strip()):
            log.warning("В peer_prompts пропущен ключ, который не является номером беседы")
            continue
        text = join_lines(value)
        if text:
            notes[int(str(ref).strip())] = text
    return notes


def read_access(data: dict, nicks: Nicks) -> tuple[AccessLists, bool]:
    if not isinstance(data, dict):
        raise ValueError("access.json должен быть объектом")
    users, all_answered = agent_user_ids(data, nicks)
    return AccessLists(agent_users=users, agent_peers=agent_peer_ids(data), peer_prompts=peer_notes(data)), all_answered


def parse_access(data: dict, resolve_screen_names) -> AccessLists:
    return read_access(data, Nicks(resolve_screen_names))[0]


class AccessFile:
    """Единственный источник списков доверия; перечитывается по mtime
    без перезапуска бота. Нет файла — списки пустые."""

    def __init__(self, path: str, resolve_screen_names):
        self._nicks = Nicks(resolve_screen_names)
        self._file = WatchedFile(path, parse=self._parse, default=AccessLists(), log_label="Списки доступа")

    def _parse(self, text: str) -> AccessLists:
        lists, all_answered = read_access(json.loads(text), self._nicks)
        if not all_answered:
            raise PartialRead(lists)
        return lists

    def current(self) -> AccessLists:
        return self._file.current()
