from web.im.controls import set_paused_peer, set_peer_personas


def test_runtime_edits():
    data = set_paused_peer({"paused_peers": [5], "paused": True}, 2000000001, True)
    assert data == {"paused_peers": [5, 2000000001], "paused": True}
    assert set_paused_peer(data, 5, False)["paused_peers"] == [2000000001]
    one = set_peer_personas({}, 7, ["rina"])
    assert one == {"peer_personas": {"7": "rina"}}
    assert set_peer_personas(one, 7, ["rina", "monika", "rina", " "])["peer_personas"] == {"7": ["rina", "monika"]}
    assert set_peer_personas(one, 7, [])["peer_personas"] == {}
