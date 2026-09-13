from bot.config import parse_user_refs


def means_user(entry, user_id: int, resolve) -> bool:
    ids, names = parse_user_refs(str(entry))
    if user_id in ids:
        return True
    return bool(names) and resolve is not None and user_id in resolve(names)


def set_member(data: dict, field: str, ref_id: int, on: bool, resolve=None) -> dict:
    kept = [x for x in data.get(field) or [] if not means_user(x, ref_id, resolve)]
    if on:
        kept.append(ref_id)
    return {**data, field: kept}


def set_keyed_text(data: dict, field: str, ref_id: int, text: str, resolve=None) -> dict:
    prompts = dict(data.get(field) or {})
    key = next((k for k in prompts if means_user(k, ref_id, resolve)), str(ref_id))
    if text.strip():
        prompts[key] = text.strip()
    else:
        prompts.pop(key, None)
    return {**data, field: prompts}


def set_peer_blocked(data: dict, peer_id: int, user_id: int, on: bool, resolve=None) -> dict:
    table = dict(data.get("peer_blocked_users") or {})
    kept = [x for x in table.get(str(peer_id)) or [] if not means_user(x, user_id, resolve)]
    if on:
        kept.append(user_id)
    if kept:
        table[str(peer_id)] = kept
    else:
        table.pop(str(peer_id), None)
    return {**data, "peer_blocked_users": table}


def set_paused_peer(data: dict, peer_id: int, on: bool) -> dict:
    peers = [int(p) for p in data.get("paused_peers") or [] if int(p) != peer_id]
    if on:
        peers.append(peer_id)
    return {**data, "paused_peers": sorted(peers)}


def set_peer_personas(data: dict, peer_id: int, slugs: list[str]) -> dict:
    table = dict(data.get("peer_personas") or {})
    clean = list(dict.fromkeys(s.strip() for s in slugs if s.strip()))
    if not clean:
        table.pop(str(peer_id), None)
    else:
        table[str(peer_id)] = clean[0] if len(clean) == 1 else clean
    return {**data, "peer_personas": table}
