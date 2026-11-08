import re
import threading
from collections import OrderedDict
from urllib.parse import quote, urlsplit

import requests
from urllib3.util import parse_url

# только CDN VK: прокси не должен ходить по адресам, которые ему подсунули
HOSTS = ("vkuserphoto.ru", "userapi.com", "vk-cdn.net", "vkuseraudio.net", "vkuservideo.net")
MAX_BYTES = 25 * 1024 * 1024
CACHE_BYTES = 48 * 1024 * 1024
TIMEOUT = (5.0, 30.0)
RANGE = re.compile(r"bytes=(\d*)-(\d*)$")
SAFE_TYPES = ("image/jpeg", "image/png", "image/gif", "image/webp", "audio/", "video/")


class Refused(ValueError):
    pass


class Unsatisfiable(ValueError):
    pass


def allowed(url: str) -> bool:
    # requests соединяется по разбору urllib3, а он читает «\» и «@» иначе, чем urlsplit: такие адреса не пускаем
    # вовсе, а хост обоих разборов сверяем
    if not isinstance(url, str) or any(c in url for c in "\\@") or any(ord(c) <= 32 or ord(c) == 127 for c in url):
        return False
    try:
        parts, real = urlsplit(url), parse_url(url)
        if parts.port is not None or real.port is not None:
            return False
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or real.scheme != "https" or (real.host or "").lower() != host:
        return False
    return any(host == h or host.endswith("." + h) for h in HOSTS)


def safe_type(kind: str) -> str:
    kind = (kind or "").split(";")[0].strip().lower()
    return kind if kind.startswith(SAFE_TYPES) else "application/octet-stream"


def media_url(url: str, name: str = "") -> str:
    """Адрес файла CDN VK через панель: голосовые так перематываются (CDN отдаёт mp3 без Range), а файлы скачиваются
    под своим именем — атрибут download у ссылки на чужой домен браузер не исполняет."""
    if not url:
        return ""
    return f"/im/media?u={quote(url, safe='')}" + (f"&name={quote(name, safe='')}" if name else "")


def byte_range(header: str | None, size: int) -> tuple[int, int] | None:
    """(start, end) включительно из одного диапазона Range; None — отдать файл целиком."""
    m = RANGE.match((header or "").strip())
    if not m or not size:
        return None
    start, end = m.groups()
    if not start:
        if not end or not int(end):
            raise Unsatisfiable(size)
        return max(0, size - int(end)), size - 1
    first = int(start)
    last = min(int(end), size - 1) if end else size - 1
    if first > last:
        raise Unsatisfiable(size)
    return first, last


class MediaCache:
    """Файлы CDN VK в памяти процесса, не на диске; вытесняются самые давние, пока не уложатся в limit байт."""

    def __init__(self, fetch=None, limit: int = CACHE_BYTES):
        self._fetch = fetch or self._download
        self._limit = limit
        self._items: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
        self._size = 0
        self._lock = threading.Lock()
        self._loading: dict[str, threading.Lock] = {}
        self._http = requests.Session()

    def get(self, url: str) -> tuple[bytes, str]:
        if not allowed(url):
            raise Refused("не CDN VK")
        # плеер шлёт несколько запросов Range разом: файл качается один раз, остальные ждут его
        with self._lock:
            loading = self._loading.setdefault(url, threading.Lock())
        with loading:
            try:
                with self._lock:
                    if url in self._items:
                        self._items.move_to_end(url)
                        return self._items[url]
                body, kind = self._fetch(url)
                kind = safe_type(kind)
                with self._lock:
                    if url not in self._items:
                        self._items[url] = (body, kind)
                        self._size += len(body)
                    while self._size > self._limit and len(self._items) > 1:
                        _, (gone, _) = self._items.popitem(last=False)
                        self._size -= len(gone)
                return body, kind
            finally:
                with self._lock:
                    if self._loading.get(url) is loading:
                        del self._loading[url]

    def _download(self, url: str) -> tuple[bytes, str]:
        # без редиректов: следующий адрес мог бы вести мимо CDN VK
        with self._http.get(url, timeout=TIMEOUT, stream=True, allow_redirects=False) as r:
            if r.status_code != 200:
                raise Refused(f"CDN VK ответил {r.status_code}")
            chunks, size = [], 0
            for chunk in r.iter_content(64 * 1024):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise Refused("файл больше 25 МБ")
                chunks.append(chunk)
            return b"".join(chunks), r.headers.get("Content-Type", "application/octet-stream")
