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
