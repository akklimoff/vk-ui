from ai.service import ReplyRequest
from bot.access import scoped_prompts
from bot.context import to_lines
from bot.reply import deliverable
from bot.runtime import persona_for
from web.im.views import is_chat

UNKNOWN_ASKER = "Собеседник"


def draft_reply(settings, ai, vk, lists, rt, peer_id: int) -> str:
    history = vk.history(peer_id, rt.context_messages)
    private = not is_chat(peer_id)
    general_prompt, specific_prompt = scoped_prompts(lists, peer_id, private)
    last_other = next((m["from_id"] for m in history if m.get("from_id") != vk.me_id), peer_id if private else None)
    result = ai.reply(ReplyRequest(
        to_lines(history, vk.resolve_name, vk.me_id),
        vk.resolve_name(last_other) if last_other else UNKNOWN_ASKER, is_private=private,
        auto_chat=not private and peer_id in lists.auto_reply_peers,
        persona=persona_for(rt, peer_id), scope_prompt=general_prompt, user_prompt=specific_prompt,
        temperature=rt.temperature, model=rt.active_model,
    ))
    # бот шлёт части по отдельности, а из композера уходит одно сообщение
    return "\n".join(deliverable(result.parts, [settings.vk_token], vk.me_id))
