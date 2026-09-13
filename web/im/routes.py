import time
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from bot.access import AccessFile
from bot.runtime import RuntimeFile, runtime_defaults
from bot.status import ReplyLog
from web.im.marks import bot_marks
from web.im.modes import bot_mode
from web.im.views import Profiles, parse_conversations, parse_history, peer_of, rows
from web.render import is_hx

DIALOGS = 60
PAGE = 40
POLL_WINDOW = 50


def create_router(settings, vk, llm, render, safe_error) -> APIRouter:
    router = APIRouter()
    tz = ZoneInfo(settings.web_timezone)
    # один WatchedFile на процесс: перечитывание и разрешение @ников только при смене mtime,
    # иначе каждый тик поллинга ходил бы в users.get
    access_file = AccessFile(settings.access_file, lambda names: vk().resolve_screen_names(names))
    runtime_file = RuntimeFile(settings.runtime_file, runtime_defaults(settings))

    def lists():
        return access_file.current()

    def runtime():
        return runtime_file.current()

    def marks():
        return bot_marks(ReplyLog(f"{settings.state_dir}/replies.jsonl").read())

    def dialogs_ctx():
        access, rt = lists(), runtime()
        dialogs = parse_conversations(vk().conversations(DIALOGS), vk().me_id, marks())
        return {"dialogs": [(d, bot_mode(d.peer.id, access, rt)) for d in dialogs], "tz": tz}

    def chat_ctx(peer_id: int, before: int | None = None, after: int | None = None):
        raw = vk().history_page(peer_id, POLL_WINDOW if after else PAGE, before_id=before)
        messages, out_read = parse_history(raw, vk().me_id, marks())
        if after:
            messages = [m for m in messages if m.id > after]
        convs = raw.get("conversations") or []
        peer = peer_of(convs[0], Profiles(raw)) if convs else None
        return {"peer": peer, "peer_id": peer_id, "rows": rows(messages, time.time(), tz),
                "out_read": out_read, "oldest": messages[0].id if messages else None,
                "newest": messages[-1].id if messages else (after or 0),
                "mode": bot_mode(peer_id, lists(), runtime()), "tz": tz, "page": "im"}

    def guard(call):
        try:
            return call()
        except Exception as e:
            raise HTTPException(502, f"VK: {safe_error(e)}")

    def sent_ctx(peer_id: int, message_id: int):
        raw = vk().messages_by_id([message_id])
        messages, out_read = parse_history(raw, vk().me_id, marks())
        return {"peer_id": peer_id, "rows": rows(messages, time.time(), tz), "out_read": out_read,
                "newest": message_id, "oldest": None, "tz": tz}

    def send_form_error(request: Request, error: str):
        return render.invalid(request, "im_error", {"page": "im"}, error)

    @router.get("/im")
    def im_page(request: Request, sel: int | None = None):
        ctx = {"page": "im", "sel": sel, **guard(dialogs_ctx)}
        if sel is not None:
            ctx["chat"] = guard(lambda: chat_ctx(sel))
        return render.page(request, "im", ctx)

    @router.get("/im/dialogs")
    def dialogs_partial(request: Request):
        return render.partial(request, "im_dialogs", {"page": "im", **guard(dialogs_ctx)})

    @router.get("/im/{peer_id}/messages")
    def messages_partial(request: Request, peer_id: int, after: int | None = None, before: int | None = None):
        ctx = guard(lambda: chat_ctx(peer_id, before=before, after=after))
        return render.partial(request, "im_rows_page", {"chat": ctx, "after": after, "before": before, "page": "im"})

    @router.get("/im/{peer_id}")
    def chat_partial(request: Request, peer_id: int):
        ctx = guard(lambda: chat_ctx(peer_id))
        if not is_hx(request):
            return render.page(request, "im", {"page": "im", "sel": peer_id, "chat": ctx, **guard(dialogs_ctx)})
        return render.partial(request, "im_chat", {"chat": ctx, "page": "im"}, push_url=f"/im?sel={peer_id}")

    @router.post("/im/{peer_id}/send")
    def send_message(request: Request, peer_id: int, text: str = Form(""), reply_to: str = Form("")):
        text = text.strip()
        if not text:
            return send_form_error(request, "Пустое сообщение")
        reply_id = int(reply_to) if reply_to.strip() else None
        try:
            message_id = vk().send(peer_id, text, reply_to=reply_id)
            ctx = sent_ctx(peer_id, message_id)
        except Exception as e:
            return send_form_error(request, f"VK не отправил: {safe_error(e)}")
        if not is_hx(request):
            return RedirectResponse(f"/im?sel={peer_id}", status_code=303)
        return render.partial(request, "im_rows_page", {"chat": ctx, "after": message_id, "before": None, "page": "im"},
                              toast="Отправлено")

    @router.post("/im/{peer_id}/read")
    def mark_read(peer_id: int):
        guard(lambda: vk().mark_read(peer_id))
        return Response(status_code=204)

    @router.post("/im/{peer_id}/messages/{message_id}/delete")
    def delete_message(request: Request, peer_id: int, message_id: int):
        guard(lambda: vk().delete_message(message_id))
        return Response(status_code=200) if is_hx(request) else RedirectResponse(f"/im?sel={peer_id}", status_code=303)

    return router
