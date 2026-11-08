import hashlib
import json
import re
import time
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response, StreamingResponse

from web.im.archive import Archive
from web.im.cache import Dialogs, Histories, peer_of_item
from web.im.events import inbox_events
from web.auth import same_site
from web.im.media import MediaCache, Refused, Unsatisfiable, byte_range
from web.im.uploads import MAX_PHOTO_BYTES, MAX_PHOTOS, prepare_photos
from web.im.views import (Message, Profiles, parse_conversations, parse_history, parse_media, parse_search, peer_of,
                          preview, rows, web_link)
from web.im.voice import MAX_VOICE_BYTES, prepare_voice
from web.pace import background
from web.render import is_hx

DIALOGS = 60
MAX_DIALOGS = 200
SEARCH = 20
PAGE = 40
# голова переписки: её отдаёт открытие чата и в ней же поллинг ищет новое — одна загрузка на оба
HEAD = 50
MEDIA_PAGE = 60
MEDIA_TABS = {"photo": "Фото", "video": "Видео", "doc": "Файлы", "link": "Ссылки", "audio_message": "Голосовые"}
VIDEO_REF = re.compile(r"(-?\d+)_(\d+)(?:_([0-9a-f]+))?$")
PLAYER_HOSTS = ("vkvideo.ru", "vk.com", "vk.ru")
PLAYER_TTL = 3600.0
PLAYERS_KEPT = 500
# служебный аккаунт «ВКонтакте» (id100): уведомления о входах и безопасности
NEVER_SHOWN = frozenset({100})


def create_router(settings, vk, render, safe_error, inbox) -> APIRouter:
    tz = ZoneInfo(settings.web_timezone)
    archive = Archive(lambda: vk().archived_peers())
    dialogs = Dialogs(vk, inbox)
    histories = Histories(inbox)
    media = MediaCache()
    players: dict[str, tuple[float, str]] = {}

    def hidden_peers(fresh: bool = False) -> frozenset[int]:
        return archive.peers(fresh=fresh) | NEVER_SHOWN

    def dialogs_ctx(count: int = DIALOGS, offset: int = 0):
        """count — сколько диалогов показать, offset — с какой беседы VK начать. Скрытые пропускаются, и список
        дочитывается, пока не наберётся count: иначе каждое обновление списка с count с экрана укорачивало бы его."""
        hidden = hidden_peers()
        want = offset + count + len(hidden)
        while True:
            raw = dialogs.snapshot(want)
            items, total = raw["items"], raw["count"]
            shown = sum(1 for i in items[offset:] if peer_of_item(i) not in hidden)
            if shown >= count or len(items) >= total or len(items) < want or want >= MAX_DIALOGS + len(hidden):
                break
            want += count - shown
        picked, at = [], offset
        for item in items[offset:]:
            at += 1
            if peer_of_item(item) not in hidden:
                picked.append(item)
                if len(picked) == count:
                    break
        page = parse_conversations({**raw, "items": picked}, vk().me_id)
        more = at if page and at < min(total, MAX_DIALOGS) else None
        return {"dialogs": page, "tz": tz, "now": time.time(), "more": more}

    def dialogs_version(ctx) -> str:
        # время «5м» в строке не входит в версию: его пересчитывает браузер, а данные — неизменные view-модели
        return hashlib.sha1(repr((ctx["dialogs"], ctx["more"])).encode()).hexdigest()[:16]

    def head(peer_id: int, fresh: bool = False) -> dict:
        return histories.get(peer_id, lambda: vk().history_page(peer_id, HEAD), fresh=fresh)

    def history(peer_id: int, before: int) -> dict:
        return vk().history_page(peer_id, PAGE, before_id=before)

    def rendered_tail(last_from: int | None, last_ts: float | None) -> Message | None:
        if last_from is None or last_ts is None:
            return None
        return Message(0, last_ts, last_from, "", "", "", False, False)

    def chat_ctx(peer_id: int, before: int | None = None, after: int | None = None, prev: Message | None = None,
                 fresh: bool = False):
        count = PAGE if before else HEAD
        raw = head(peer_id, fresh=fresh) if before is None else history(peer_id, before)
        messages, out_read = parse_history(raw, vk().me_id)
        full_page = len(messages) >= count
        if after:
            messages = [m for m in messages if m.id > after]
        convs = raw.get("conversations") or []
        peer = peer_of(convs[0], Profiles(raw)) if convs else None
        unread = int(convs[0].get("unread_count", 0)) if convs else 0
        opening = convs and not after and not before and unread
        in_read = int(convs[0].get("in_read", 0)) if opening else None
        now = time.time()
        return {"peer": peer, "peer_id": peer_id, "rows": rows(messages, now, tz, prev, in_read), "unread": unread,
                "out_read": out_read, "oldest": messages[0].id if messages and full_page else None,
                "tz": tz, "now": now, "page": "im"}

    def guard(call):
        try:
            return call()
        except Exception as e:
            raise HTTPException(502, f"VK: {safe_error(e)}")

    def refuse_hidden(request: Request):
        asked = request.path_params.get("peer_id", request.query_params.get("sel"))
        if asked is None or not str(asked).lstrip("-").isdecimal():
            return
        if int(asked) in guard(hidden_peers):
            raise HTTPException(404, "Чат скрыт")

    router = APIRouter(dependencies=[Depends(refuse_hidden)])

    def send_form_error(request: Request, error: str):
        return render.invalid(request, "im_error", {"page": "im"}, error)

    @router.get("/im")
    def im_page(request: Request, sel: int | None = None):
        ctx = {"page": "im", "sel": sel, **guard(dialogs_ctx)}
        if sel is not None:
            ctx["chat"] = guard(lambda: chat_ctx(sel))
        return render.page(request, "im", ctx)

    @router.get("/im/dialogs")
    def dialogs_partial(request: Request, count: int = DIALOGS, v: str = ""):
        """Тот же список, что уже на экране, отвечает 204: перерисовка без изменений сбивала бы наведение и прокрутку."""
        count = max(1, min(count, MAX_DIALOGS))
        with background():
            ctx = guard(lambda: dialogs_ctx(count))
        version = dialogs_version(ctx)
        if version == v:
            return Response(status_code=204)
        response = render.partial(request, "im_dialogs", {"page": "im", **ctx})
        response.headers["X-Dialogs-Version"] = version
        return response

    @router.get("/im/dialogs/more")
    def dialogs_more(request: Request, offset: int):
        count = min(DIALOGS, MAX_DIALOGS - offset)
        if count <= 0:
            return render.partial(request, "im_dialogs", {"page": "im", "dialogs": [], "more": None})
        return render.partial(request, "im_dialogs", {"page": "im", **guard(lambda: dialogs_ctx(count, offset))})

    @router.get("/im/dialogs/search")
    def dialogs_search(request: Request, q: str = ""):
        q = q.strip()
        if not q:
            return render.partial(request, "im_search", {"page": "im", "dialogs": [], "q": ""})
        found = parse_search(guard(lambda: vk().search_conversations(q, SEARCH)), vk().me_id)
        hidden = guard(hidden_peers)
        found = [d for d in found if d.peer.id not in hidden]
        return render.partial(request, "im_search", {"page": "im", "q": q, "tz": tz, "now": time.time(),
                                                     "dialogs": found})

    @router.get("/im/events")
    async def inbox_stream(request: Request):
        inbox.start()
        return StreamingResponse(inbox_events(inbox.changes_since, request.is_disconnected, healthy=inbox.healthy,
                                              version=inbox.version),
                                 media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @router.get("/im/media")
    def media_file(request: Request, u: str, name: str = ""):
        """Файл CDN VK через панель: с Range — для перемотки голосовых, с именем — для «Сохранить»."""
        # плеер и ссылки «Сохранить» — с этой же страницы; чужая страница не заставит панель ходить по адресам
        if not same_site(request):
            raise HTTPException(403, "Запрос с чужого сайта")
        try:
            body, kind = media.get(u)
            span = byte_range(request.headers.get("Range"), len(body))
        except Unsatisfiable:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{len(body)}"})
        except Refused as e:
            raise HTTPException(404, str(e))
        except Exception as e:
            raise HTTPException(502, f"VK: {safe_error(e)}")
        # файл с CDN VK отдаётся с адреса панели: даже загруженный кем-то HTML не исполнится в её origin
        headers = {"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=86400",
                   "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox; default-src 'none'"}
        if name:
            headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(name, safe='')}"
        if span is None:
            return Response(body, media_type=kind, headers=headers)
        first, last = span
        headers["Content-Range"] = f"bytes {first}-{last}/{len(body)}"
        return Response(body[first:last + 1], status_code=206, media_type=kind, headers=headers)

    @router.get("/im/video/{ref}")
    def video_player(request: Request, ref: str, back: str = ""):
        """Плеер VK для видео и кружка: прямых файлов VK этому токену не отдаёт, только встраиваемый плеер."""
        found = VIDEO_REF.match(ref)
        if not found or not is_hx(request):
            raise HTTPException(404, "нет такого видео")
        at, player = players.get(ref, (0.0, ""))
        if not player or time.monotonic() - at >= PLAYER_TTL:
            owner, vid, key = found.groups()
            player = web_link(guard(lambda: vk().video_player(int(owner), int(vid), key or "")))
            host = player.split("/")[2] if player else ""
            if not any(host == h or host.endswith("." + h) for h in PLAYER_HOSTS):
                player = ""
            if len(players) >= PLAYERS_KEPT:
                players.clear()
            players[ref] = (time.monotonic(), player)
        return render.partial(request, "im_player", {"page": "im", "player": player, "back": web_link(back)})

    @router.get("/im/{peer_id}/media")
    def media_partial(request: Request, peer_id: int, type: str = "photo", start_from: str = "", tab: str = ""):
        """tab — сменили вкладку: только её содержимое; start_from — следующая страница: только плитки."""
        if not is_hx(request):
            return RedirectResponse(f"/im?sel={peer_id}", status_code=303)
        if type not in MEDIA_TABS:
            raise HTTPException(404, "нет такого вида вложений")
        items, next_from = parse_media(guard(lambda: vk().history_media(peer_id, type, MEDIA_PAGE, start_from)), type)
        return render.partial(request, "im_media_panel", {
            "peer_id": peer_id, "type": type, "tabs": MEDIA_TABS, "items": items, "next_from": next_from,
            "part": "page" if start_from else "tab" if tab else "panel", "start": start_from, "tz": tz, "now": time.time(), "page": "im"})

    @router.get("/im/{peer_id}/messages")
    def messages_partial(request: Request, peer_id: int, after: int | None = None, before: int | None = None,
                         last_from: int | None = None, last_ts: float | None = None):
        prev = rendered_tail(last_from, last_ts) if after is not None else None
        if after is None:
            ctx = guard(lambda: chat_ctx(peer_id, before=before, after=after, prev=prev))
        else:
            with background():
                ctx = guard(lambda: chat_ctx(peer_id, before=before, after=after, prev=prev))
        return render.partial(request, "im_rows_page", {"chat": ctx, "after": after, "before": before, "page": "im"})

    @router.get("/im/{peer_id}")
    def chat_partial(request: Request, peer_id: int):
        ctx = guard(lambda: chat_ctx(peer_id))
        if not is_hx(request):
            return render.page(request, "im", {"page": "im", "sel": peer_id, "chat": ctx, **guard(dialogs_ctx)})
        return render.partial(request, "im_chat", {"chat": ctx, "page": "im"}, push_url=f"/im?sel={peer_id}")

    @router.post("/im/{peer_id}/send")
    def send_message(request: Request, peer_id: int, text: str = Form(""), reply_to: str = Form(""),
                     voice: UploadFile | None = File(None), photos: list[UploadFile] = File([]),
                     after: int = Form(0), last_from: int | None = Form(None), last_ts: float | None = Form(None)):
        text = text.strip()
        # на байт больше лимита — чтобы sniff_voice увидел превышение, не читая гигабайты
        data = voice.file.read(MAX_VOICE_BYTES + 1) if voice is not None and voice.filename else b""
        picked = [f for f in photos if f.filename][:MAX_PHOTOS + 1]
        pictures = [(f.file.read(MAX_PHOTO_BYTES + 1), f.filename) for f in picked]
        if not text and not data and not pictures:
            return send_form_error(request, "Пустое сообщение")
        if reply_to.strip() and not reply_to.strip().isdecimal():
            return send_form_error(request, "Непонятно, на какое сообщение ответ")
        reply_id = int(reply_to) if reply_to.strip() else None
        try:
            ogg = prepare_voice(data, voice.filename) if data else b""
            images = prepare_photos(pictures)
        except ValueError as e:
            return send_form_error(request, str(e))
        if ogg and images:
            # VK кладёт голосовое в сообщение только одно, без других вложений
            return send_form_error(request, "Голосовое отправляется без фото: убери одно из двух")
        try:
            attachments = vk().upload_photos(peer_id, images) if images else []
        except Exception as e:
            return send_form_error(request, f"VK не принял фото: {safe_error(e)}")
        try:
            attachments += [vk().upload_voice(peer_id, ogg, "ogg")] if ogg else []
        except Exception as e:
            return send_form_error(request, f"VK не принял голосовое: {safe_error(e)}")
        try:
            vk().send(peer_id, text, reply_to=reply_id, attachment=",".join(attachments))
        except Exception as e:
            return send_form_error(request, f"VK не отправил: {safe_error(e)}")
        if not is_hx(request):
            return RedirectResponse(f"/im?sel={peer_id}", status_code=303)
        # всё новое после отрисованного, а не только своё: иначе пришедшее перед отправкой
        # оказалось бы выше курсора и не дорисовалось
        try:
            ctx = chat_ctx(peer_id, after=after, prev=rendered_tail(last_from, last_ts), fresh=True)
        except Exception:
            # сообщение уже ушло: композер очищается, чтобы его не отправили повторно, дорисует поллинг
            return Response(headers={"HX-Trigger": json.dumps({"toast": "Отправлено"})})
        return render.partial(request, "im_rows_page", {"chat": ctx, "after": after, "before": None, "page": "im"},
                              toast="Отправлено")

    @router.post("/im/{peer_id}/warm")
    def warm_chat(peer_id: int):
        with background():
            guard(lambda: head(peer_id))
        return Response(status_code=204)

    @router.post("/im/{peer_id}/read")
    def mark_read(peer_id: int):
        guard(lambda: vk().mark_read(peer_id))
        # long poll сообщит о прочтении позже: без отметки список успел бы перерисоваться со старым счётчиком
        inbox.changed([peer_id])
        return Response(status_code=204)

    @router.post("/im/{peer_id}/messages/{message_id}/delete")
    def delete_message(request: Request, peer_id: int, message_id: int):
        guard(lambda: vk().delete_message(message_id))
        inbox.changed([peer_id])
        return Response(status_code=200) if is_hx(request) else RedirectResponse(f"/im?sel={peer_id}", status_code=303)

    return router
