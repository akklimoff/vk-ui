from bot.access import scoped_prompts
from bot.batching import split_reply
from bot.context import build_context
from bot.llm import secrets_of
from bot.personas import load_persona
from bot.reply import ReplyRequest, generate_reply
from bot.repetition import own_messages
from bot.runtime import persona_for
from web.im.views import is_chat

UNKNOWN_ASKER = "Собеседник"


def draft_reply(settings, llm, vk, lists, rt, peer_id: int) -> str:
    history = vk.history(peer_id, rt.context_messages)
    conversation = build_context(history, vk.resolve_name, settings.message_char_limit,
                                 settings.context_char_budget, vk.me_id)
    private = not is_chat(peer_id)
    general_prompt, specific_prompt = scoped_prompts(lists, peer_id, private)
    last_other = next((m["from_id"] for m in history if m.get("from_id") != vk.me_id), peer_id if private else None)
    slug = persona_for(rt, peer_id)
    persona = load_persona(settings.personas_dir, slug) if slug else None
    request = ReplyRequest(
        conversation, vk.resolve_name(last_other) if last_other else UNKNOWN_ASKER, is_private=private,
        auto_chat=not private and peer_id in lists.auto_reply_peers,
        persona_prompt=persona.prompt if persona else settings.persona_prompt,
        private_prompt=general_prompt, user_prompt=specific_prompt,
        temperature=rt.temperature, seed=last_other or peer_id,
        own_recent=own_messages(history, vk.me_id), model=rt.active_model,
    )
    reply, _ = generate_reply(llm, request, [settings.vk_token, *secrets_of(settings)], vk.me_id)
    # бот шлёт части по отдельности, а из композера уходит одно сообщение
    return "\n".join(split_reply(reply))
