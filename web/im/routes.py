import json
import time
from zoneinfo import ZoneInfo

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import PlainTextResponse, RedirectResponse, Response

from bot.access import AccessFile
from ai.personas import list_personas
from bot.runtime import RuntimeFile, runtime_defaults
from bot.status import ReplyLog, write_json_atomic
from web.im.controls import set_keyed_text, set_member, set_paused_peer, set_peer_blocked, set_peer_personas
from web.im.draft import draft_reply
from web.im.marks import bot_marks
from web.im.modes import bot_mode, chat_controls
from web.im.views import Message, Profiles, is_chat, parse_conversations, parse_history, peer_of, rows
from web.im.voice import MAX_VOICE_BYTES, prepare_voice
from web.render import is_hx
from web.services import access_raw, load_runtime_dict

DIALOGS = 60
PAGE = 40
POLL_WINDOW = 50
SWITCHES = {
    "auto": ("access", "auto_reply_users", "auto_reply_peers"),
    "blocked": ("access", "blocked_users", "blocked_peers"),
    "onboarding": ("access", None, "onboarding_peers"),
    "paused": ("runtime", "paused_peers", "paused_peers"),
}


def create_router(settings, vk, ai, render, safe_error) -> APIRouter:
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
        return {"dialogs": [(d, bot_mode(d.peer.id, access, rt)) for d in dialogs], "tz": tz, "now": time.time()}

    def rendered_tail(last_from: int | None, last_ts: float | None) -> Message | None:
        if last_from is None or last_ts is None:
            return None
        return Message(0, last_ts, last_from, "", "", "", False, False)

    def chat_ctx(peer_id: int, before: int | None = None, after: int | None = None, prev: Message | None = None):
        count = POLL_WINDOW if after else PAGE
        raw = vk().history_page(peer_id, count, before_id=before)
        messages, out_read = parse_history(raw, vk().me_id, marks())
        full_page = len(messages) >= count
        if after:
            messages = [m for m in messages if m.id > after]
        convs = raw.get("conversations") or []
        peer = peer_of(convs[0], Profiles(raw)) if convs else None
        opening = convs and not after and not before and convs[0].get("unread_count")
        in_read = int(convs[0].get("in_read", 0)) if opening else None
        now = time.time()
        return {"peer": peer, "peer_id": peer_id, "rows": rows(messages, now, tz, prev, in_read),
                "out_read": out_read, "oldest": messages[0].id if messages and full_page else None,
                "mode": bot_mode(peer_id, lists(), runtime()), "tz": tz, "now": now, "page": "im"}

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
    def dialogs_partial(request: Request):
        return render.partial(request, "im_dialogs", {"page": "im", **guard(dialogs_ctx)})

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
                     voice: UploadFile | None = File(None), after: int = Form(0),
                     last_from: int | None = Form(None), last_ts: float | None = Form(None)):
        text = text.strip()
        # на байт больше лимита — чтобы sniff_voice увидел превышение, не читая гигабайты
        data = voice.file.read(MAX_VOICE_BYTES + 1) if voice is not None and voice.filename else b""
        if not text and not data:
            return send_form_error(request, "Пустое сообщение")
        reply_id = int(reply_to) if reply_to.strip() else None
        try:
            ogg = prepare_voice(data, voice.filename) if data else b""
        except ValueError as e:
            return send_form_error(request, str(e))
        try:
            attachment = vk().upload_voice(peer_id, ogg, "ogg") if ogg else ""
        except Exception as e:
            return send_form_error(request, f"VK не принял голосовое: {safe_error(e)}")
        try:
            vk().send(peer_id, text, reply_to=reply_id, attachment=attachment)
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

    @router.post("/im/{peer_id}/read")
    def mark_read(peer_id: int):
        guard(lambda: vk().mark_read(peer_id))
        return Response(status_code=204)

    @router.post("/im/{peer_id}/messages/{message_id}/delete")
    def delete_message(request: Request, peer_id: int, message_id: int):
        guard(lambda: vk().delete_message(message_id))
        return Response(status_code=200) if is_hx(request) else RedirectResponse(f"/im?sel={peer_id}", status_code=303)

    @router.post("/im/{peer_id}/draft")
    def bot_draft(peer_id: int):
        try:
            return PlainTextResponse(draft_reply(settings, ai(), vk(), lists(), runtime(), peer_id))
        except Exception as e:
            raise HTTPException(502, f"Не удалось получить черновик: {safe_error(e)}")

    def bot_ctx(peer_id: int):
        access, rt = lists(), runtime()
        raw = vk().members(peer_id) if is_chat(peer_id) else {}
        profiles = Profiles(raw)
        members = [(m["member_id"], profiles.name(m["member_id"]), profiles.photo(m["member_id"]))
                   for m in raw.get("items") or [] if m["member_id"] != vk().me_id and m["member_id"] > 0]
        return {"peer_id": peer_id, "mode": bot_mode(peer_id, access, rt), "c": chat_controls(peer_id, access, rt),
                "members": members, "personas": list_personas(settings.personas_dir),
                "active": rt.active_persona, "page": "im"}

    def bot_panel(request: Request, peer_id: int, toast: str | None = None):
        if not is_hx(request):
            return RedirectResponse(f"/im?sel={peer_id}", status_code=303)
        return render.partial(request, "im_bot", guard(lambda: bot_ctx(peer_id)), toast=toast)

    @router.get("/im/{peer_id}/bot")
    def bot_page(request: Request, peer_id: int):
        return bot_panel(request, peer_id)

    @router.post("/im/{peer_id}/bot/prompt")
    def bot_prompt(request: Request, peer_id: int, text: str = Form("")):
        field = "peer_prompts" if is_chat(peer_id) else "user_prompts"
        data = set_keyed_text(access_raw(settings.access_file), field, peer_id, text, vk().resolve_screen_names)
        write_json_atomic(settings.access_file, data)
        return bot_panel(request, peer_id, toast="Промпт сохранён")

    @router.post("/im/{peer_id}/bot/personas")
    def bot_personas(request: Request, peer_id: int, slug: list[str] = Form([])):
        known = {p.slug for p in list_personas(settings.personas_dir)}
        unknown = [s for s in slug if s not in known]
        if unknown:
            return render.invalid(request, "im_bot", guard(lambda: bot_ctx(peer_id)), f"Нет персоны: {', '.join(unknown)}")
        write_json_atomic(settings.runtime_file, set_peer_personas(load_runtime_dict(settings.runtime_file), peer_id, slug))
        return bot_panel(request, peer_id, toast="Персоны сохранены")

    @router.post("/im/{peer_id}/bot/members/{user_id}")
    def bot_member(request: Request, peer_id: int, user_id: int, on: str = Form("")):
        data = set_peer_blocked(access_raw(settings.access_file), peer_id, user_id, bool(on), vk().resolve_screen_names)
        write_json_atomic(settings.access_file, data)
        return bot_panel(request, peer_id, toast="Сохранено")

    @router.post("/im/{peer_id}/bot/{switch}")
    def bot_switch(request: Request, peer_id: int, switch: str, on: str = Form("")):
        if switch not in SWITCHES:
            raise HTTPException(404)
        target, user_field, peer_field = SWITCHES[switch]
        field = peer_field if is_chat(peer_id) else user_field
        if field is None:
            raise HTTPException(404, "только для бесед")
        if target == "runtime":
            write_json_atomic(settings.runtime_file,
                              set_paused_peer(load_runtime_dict(settings.runtime_file), peer_id, bool(on)))
        else:
            data = set_member(access_raw(settings.access_file), field, peer_id, bool(on), vk().resolve_screen_names)
            write_json_atomic(settings.access_file, data)
        return bot_panel(request, peer_id, toast="Сохранено")

    return router
