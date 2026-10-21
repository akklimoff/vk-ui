import hashlib
import json
import threading
import time
from zoneinfo import ZoneInfo

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response, StreamingResponse

from web.im.events import inbox_events
from web.im.uploads import MAX_PHOTO_BYTES, MAX_PHOTOS, prepare_photos
from web.im.views import (Message, Profiles, parse_conversations, parse_history, parse_media, parse_search, peer_of,
                          rows)
from web.im.voice import MAX_VOICE_BYTES, prepare_voice
from web.render import is_hx

DIALOGS = 60
MAX_DIALOGS = 200
SEARCH = 20
PAGE = 40
POLL_WINDOW = 50
MEDIA_PAGE = 60
MEDIA_TABS = {"photo": "Фото", "video": "Видео", "doc": "Файлы", "link": "Ссылки", "audio_message": "Голосовые"}
WARM_TTL = 10.0


def create_router(settings, vk, render, safe_error, inbox) -> APIRouter:
    router = APIRouter()
    tz = ZoneInfo(settings.web_timezone)
    # ответ VK на открытие чата, запрошенный при наведении на диалог: клик забирает его, не дожидаясь VK;
    # версия переписки — на момент запроса: если с тех пор переписка менялась, ответ устарел
    warmed: dict[int, tuple[float, int, dict]] = {}
    warmed_lock = threading.Lock()

    def dialogs_ctx(count: int = DIALOGS, offset: int = 0):
        raw = vk().conversations(count, offset)
        dialogs = parse_conversations(raw, vk().me_id)
        loaded = offset + len(dialogs)
        more = loaded if dialogs and loaded < min(int(raw.get("count", 0)), MAX_DIALOGS) else None
        return {"dialogs": dialogs, "tz": tz, "now": time.time(), "more": more}

    def history(peer_id: int, count: int, before: int | None):
        if before is None and count == PAGE:
            with warmed_lock:
                at, mark, raw = warmed.pop(peer_id, (0.0, 0, None))
            if raw is not None and time.monotonic() - at < WARM_TTL and mark == inbox.version():
                return raw
        return vk().history_page(peer_id, count, before_id=before)

    def rendered_tail(last_from: int | None, last_ts: float | None) -> Message | None:
        if last_from is None or last_ts is None:
            return None
        return Message(0, last_ts, last_from, "", "", "", False, False)

    def chat_ctx(peer_id: int, before: int | None = None, after: int | None = None, prev: Message | None = None):
        count = POLL_WINDOW if after else PAGE
        raw = history(peer_id, count, before) if not after else vk().history_page(peer_id, count)
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
        response = render.partial(request, "im_dialogs", {"page": "im", **guard(lambda: dialogs_ctx(count))})
        version = hashlib.sha1(response.body).hexdigest()[:16]
        if version == v:
            return Response(status_code=204)
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
        return render.partial(request, "im_search", {"page": "im", "q": q, "tz": tz, "now": time.time(),
                                                     "dialogs": found})

    @router.get("/im/events")
    async def inbox_stream(request: Request):
        inbox.start()
        return StreamingResponse(inbox_events(inbox.version, request.is_disconnected, healthy=inbox.healthy),
                                 media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @router.get("/im/{peer_id}/messages")
    def messages_partial(request: Request, peer_id: int, after: int | None = None, before: int | None = None,
                         last_from: int | None = None, last_ts: float | None = None):
        prev = rendered_tail(last_from, last_ts) if after is not None else None
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
            ctx = chat_ctx(peer_id, after=after, prev=rendered_tail(last_from, last_ts))
        except Exception:
            # сообщение уже ушло: композер очищается, чтобы его не отправили повторно, дорисует поллинг
            return Response(headers={"HX-Trigger": json.dumps({"toast": "Отправлено"})})
        return render.partial(request, "im_rows_page", {"chat": ctx, "after": after, "before": None, "page": "im"},
                              toast="Отправлено")

    @router.post("/im/{peer_id}/warm")
    def warm_chat(peer_id: int):
        now, mark = time.monotonic(), inbox.version()
        with warmed_lock:
            for stale in [p for p, (at, _, _) in warmed.items() if now - at >= WARM_TTL]:
                del warmed[stale]
            if peer_id in warmed:
                return Response(status_code=204)
        raw = guard(lambda: vk().history_page(peer_id, PAGE))
        with warmed_lock:
            warmed[peer_id] = (now, mark, raw)
        return Response(status_code=204)

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

    @router.post("/im/{peer_id}/read")
    def mark_read(peer_id: int):
        guard(lambda: vk().mark_read(peer_id))
        return Response(status_code=204)

    @router.post("/im/{peer_id}/messages/{message_id}/delete")
    def delete_message(request: Request, peer_id: int, message_id: int):
        guard(lambda: vk().delete_message(message_id))
        return Response(status_code=200) if is_hx(request) else RedirectResponse(f"/im?sel={peer_id}", status_code=303)

    return router
