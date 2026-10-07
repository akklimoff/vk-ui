import json
import time
from dataclasses import replace
from zoneinfo import ZoneInfo

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response

from bot.access import AccessFile
from ai.personas import list_personas
from bot.runtime import RuntimeFile, runtime_defaults
from bot.agent.journal import ActionLog
from web import trust
from web.im.controls import set_paused_peer, set_peer_personas
from web.im.marks import bot_marks
from web.im.modes import bot_mode, chat_controls
from web.im.views import Message, Profiles, is_chat, parse_conversations, parse_history, peer_of, rows
from web.im.voice import MAX_VOICE_BYTES, prepare_voice
from web.render import is_hx
from web.services import update_config

DIALOGS = 60
PAGE = 40
POLL_WINDOW = 50


def create_router(settings, vk, render, safe_error) -> APIRouter:
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
        return bot_marks(ActionLog(f"{settings.state_dir}/actions.jsonl").read())

    def dialogs_ctx():
        access, rt = lists(), runtime()
        dialogs = parse_conversations(vk().conversations(DIALOGS), vk().me_id, marks())
        return {"dialogs": [(d, bot_mode(d.peer.id, access, rt, vk().me_id)) for d in dialogs], "tz": tz,
                "now": time.time()}

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
                "mode": bot_mode(peer_id, lists(), runtime(), vk().me_id), "tz": tz, "now": now, "page": "im"}

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
        if reply_to.strip() and not reply_to.strip().isdecimal():
            return send_form_error(request, "Непонятно, на какое сообщение ответ")
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

    def bot_ctx(peer_id: int):
        access, rt = lists(), runtime()
        raw = vk().members(peer_id) if is_chat(peer_id) else {}
        profiles = Profiles(raw)
        members = [(m["member_id"], profiles.name(m["member_id"]), profiles.photo(m["member_id"]))
                   for m in raw.get("items") or [] if m["member_id"] != vk().me_id and m["member_id"] > 0]
        return {"peer_id": peer_id, "mode": bot_mode(peer_id, access, rt, vk().me_id),
                "c": chat_controls(peer_id, access, rt, vk().me_id),
                "members": members, "personas": list_personas(settings.personas_dir),
                "active": rt.active_persona, "page": "im"}

    def bot_panel(request: Request, peer_id: int, toast: str | None = None):
        if not is_hx(request):
            return RedirectResponse(f"/im?sel={peer_id}", status_code=303)
        return render.partial(request, "im_bot", guard(lambda: bot_ctx(peer_id)), toast=toast)

    @router.get("/im/{peer_id}/bot")
    def bot_page(request: Request, peer_id: int):
        return bot_panel(request, peer_id)

    def not_saved(request: Request, peer_id: int, error: ValueError, **entered):
        if not is_hx(request):
            return render.invalid(request, "im_bot", {}, str(error))
        try:
            ctx = bot_ctx(peer_id)
        except Exception:
            return render.invalid(request, "im_error", {"page": "im"}, str(error))
        return render.invalid(request, "im_bot", {**ctx, "c": replace(ctx["c"], **entered)}, str(error))

    def chats_only(peer_id: int) -> None:
        if not is_chat(peer_id):
            raise HTTPException(404, "только для бесед")

    def trust_change(request: Request, peer_id: int, change, toast: str, **entered):
        try:
            trust.save(settings.access_file, change)
        except ValueError as e:
            return not_saved(request, peer_id, e, **entered)
        return bot_panel(request, peer_id, toast=toast)

    @router.post("/im/{peer_id}/bot/note")
    def bot_note(request: Request, peer_id: int, text: str = Form("")):
        chats_only(peer_id)
        # браузер отправляет переводы строк textarea как CRLF, а в заметке они хранятся как \n
        text = text.replace("\r\n", "\n")
        return trust_change(request, peer_id, lambda lists: trust.set_note(lists, peer_id, text), "Заметка сохранена",
                            note=text)

    @router.post("/im/{peer_id}/bot/listens")
    def bot_listens(request: Request, peer_id: int, on: str = Form("")):
        chats_only(peer_id)
        change = trust.trust_peer if on else trust.untrust_peer
        return trust_change(request, peer_id, lambda lists: change(lists, peer_id),
                            "Агент слушает эту беседу" if on else "Агент больше не слушает эту беседу")

    def runtime_change(request: Request, peer_id: int, change, toast: str):
        try:
            update_config(settings.runtime_file, change)
        except (ValueError, TypeError) as e:
            return not_saved(request, peer_id, e)
        return bot_panel(request, peer_id, toast=toast)

    @router.post("/im/{peer_id}/bot/paused")
    def bot_paused(request: Request, peer_id: int, on: str = Form("")):
        return runtime_change(request, peer_id, lambda stored: set_paused_peer(stored, peer_id, bool(on)), "Сохранено")

    @router.post("/im/{peer_id}/bot/personas")
    def bot_personas(request: Request, peer_id: int, slug: list[str] = Form([])):
        known = {p.slug for p in list_personas(settings.personas_dir)}
        unknown = [s for s in slug if s not in known]
        if unknown:
            return render.invalid(request, "im_bot", guard(lambda: bot_ctx(peer_id)), f"Нет персоны: {', '.join(unknown)}")
        return runtime_change(request, peer_id, lambda stored: set_peer_personas(stored, peer_id, slug),
                              "Персоны сохранены")

    @router.post("/im/{peer_id}/bot/members/{user_id}")
    def bot_member(request: Request, peer_id: int, user_id: int, on: str = Form("")):
        chats_only(peer_id)
        if on:
            return trust_change(request, peer_id, lambda lists: trust.trust_user(lists, user_id),
                                "Человек в доверенных")
        resolve = vk().resolve_screen_names
        return trust_change(request, peer_id, lambda lists: trust.untrust_user_id(lists, user_id, resolve),
                            "Человек убран из доверенных")

    return router
