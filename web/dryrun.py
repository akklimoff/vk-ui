from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from bot.agent.gate import CHAT, OWNER, SAVED, TRUSTED, Caller
from bot.agent.journal import call_entry
from bot.agent.loop import Limits, run
from bot.agent.pictures import data_url
from bot.agent.request import Request, first_turn, format_now, mentions_in, without_self_mention
from bot.reply import deliverable
from web import trust
from web.journal import OUTCOMES, CallView, call_view

SAVED_PEER = "saved"
ASKERS = {OWNER: "Владелец (проба из админки)", TRUSTED: "Доверенный человек (проба из админки)"}
NOT_LISTENED = "Агент не слушает эту беседу: сначала добавьте её в доверенные"


@dataclass(frozen=True)
class DryRun:
    outcome: str
    outcome_kind: str
    reply: str
    calls: tuple[CallView, ...]
    steps: int
    model: str
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    first_turn: str
    ai_error: str


class Watched:
    """Цикл агента глотает сбой ИИ и отвечает «не получилось»; в песочнице нужна сама причина."""

    def __init__(self, ai):
        self._ai = ai
        self.error: Exception | None = None

    def step(self, req):
        try:
            return self._ai.step(req)
        except Exception as e:
            self.error = e
            raise


def place_of(peer: str, me_id: int, lists: trust.TrustLists) -> int:
    if peer == SAVED_PEER:
        return me_id
    # пробовать можно только там, где агент и правда откликнется: иначе прогон обещал бы то, чего не будет
    if not peer.isdigit() or int(peer) not in lists.peers:
        raise ValueError(NOT_LISTENED)
    return int(peer)


def dry_run(settings, ai, vk, *, text: str, peer: str, role: str, persona: str, model: str,
            temperature: float | None, safe_error=str, now: datetime | None = None) -> DryRun:
    lists = trust.load(settings.access_file)
    me_id = vk.me_id
    peer_id = place_of(peer.strip(), me_id, lists)
    caller = Caller(SAVED, OWNER) if peer_id == me_id else Caller(CHAT, TRUSTED if role == TRUSTED else OWNER)
    moment = now or datetime.now(ZoneInfo(settings.web_timezone))
    request = Request(without_self_mention(text, me_id), peer_id, 0, me_id, ASKERS[caller.role], format_now(moment),
                      mentions_in(text, me_id))
    limits = Limits(settings.agent_max_steps, settings.agent_time_budget_seconds,
                    settings.agent_result_char_limit, settings.agent_confirm_ttl_seconds)
    secrets = [settings.vk_token]
    watched = Watched(ai)
    outcome = run(request, caller, watched, vk.call, me_id=me_id, secrets=secrets, persona=persona,
                  peer_note=lists.notes.get(peer_id, ""), model=model, temperature=temperature, limits=limits,
                  dry_run=True, see=lambda url: data_url(*fetched) if (fetched := vk.fetch_image(url)) else None)
    title, kind = OUTCOMES.get(outcome.kind, (outcome.kind, ""))
    return DryRun(
        outcome=title, outcome_kind=kind,
        reply="\n".join(deliverable([outcome.text], secrets, me_id)),
        calls=tuple(call_view(call_entry(call, secrets)) for call in outcome.calls),
        steps=outcome.steps, model=outcome.model_id,
        prompt_tokens=outcome.prompt_tokens, completion_tokens=outcome.completion_tokens,
        cached_tokens=outcome.cached_tokens, first_turn=first_turn(request, caller),
        ai_error=safe_error(watched.error) if watched.error is not None else "",
    )
