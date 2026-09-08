ME = 1
PEER_USER = 22
PEER_CHAT = 2000000001

CONVERSATIONS = {
    "count": 2, "unread_count": 1,
    "items": [
        {"conversation": {"peer": {"id": PEER_CHAT, "type": "chat", "local_id": 1},
                          "in_read": 500, "out_read": 501, "last_message_id": 502, "unread_count": 2,
                          "sort_id": {"major_id": 1, "minor_id": 502},
                          "push_settings": {"disabled_forever": True},
                          "chat_settings": {"title": "лампочки", "members_count": 23,
                                            "photo": {"photo_50": "https://cdn.example/chat50.jpg"}}},
         "last_message": {"id": 502, "date": 1788876240, "peer_id": PEER_CHAT, "from_id": 11, "out": 0,
                          "text": "", "attachments": [{"type": "sticker", "sticker": {
                              "images": [{"url": "https://cdn.example/st64.png", "width": 64, "height": 64},
                                         {"url": "https://cdn.example/st256.png", "width": 256, "height": 256}]}}]}},
        {"conversation": {"peer": {"id": PEER_USER, "type": "user", "local_id": PEER_USER},
                          "in_read": 300, "out_read": 299, "last_message_id": 300,
                          "sort_id": {"major_id": 0, "minor_id": 300}},
         "last_message": {"id": 300, "date": 1788872640, "peer_id": PEER_USER, "from_id": ME, "out": 1,
                          "text": "Ну вот доедешь - напиши", "attachments": []}},
    ],
    "profiles": [
        {"id": 11, "first_name": "Вася", "last_name": "Пупкин", "photo_50": "https://cdn.example/u11.jpg", "online": 1},
        {"id": 22, "first_name": "Аня", "last_name": "Иванова", "photo_50": "https://cdn.example/u22.jpg", "online": 0},
        {"id": ME, "first_name": "Валентина", "last_name": "Тина", "photo_50": "https://cdn.example/me.jpg", "online": 1},
    ],
    "groups": [],
}

HISTORY = {
    "count": 4,
    "items": [
        {"id": 502, "date": 1788876240, "peer_id": PEER_CHAT, "from_id": 11, "out": 0, "text": "",
         "attachments": [{"type": "sticker", "sticker": {"images": [
             {"url": "https://cdn.example/st256.png", "width": 256, "height": 256}]}}]},
        {"id": 501, "date": 1788876180, "peer_id": PEER_CHAT, "from_id": ME, "out": 1, "text": "ну все тогда",
         "attachments": []},
        {"id": 500, "date": 1788876120, "peer_id": PEER_CHAT, "from_id": 11, "out": 0, "text": "после смены выкину.",
         "attachments": [{"type": "audio_message", "audio_message": {
             "id": 7, "owner_id": 11, "duration": 20, "waveform": [1, 5, 9], "access_key": "k",
             "link_ogg": "https://cdn.example/v.ogg", "link_mp3": "https://cdn.example/v.mp3",
             "transcript": "после смены выкину", "transcript_state": "done"}}],
         "reply_message": {"from_id": ME, "text": "выкидывай тогда"}},
        {"id": 499, "date": 1788739980, "peer_id": PEER_CHAT, "from_id": 11, "out": 0, "text": "",
         "attachments": [], "action": {"type": "chat_invite_user", "member_id": 22}},
    ],
    "profiles": CONVERSATIONS["profiles"],
    "groups": [],
    "conversations": [CONVERSATIONS["items"][0]["conversation"]],
}

MEMBERS = {
    "count": 3,
    "items": [{"member_id": ME, "is_owner": True}, {"member_id": 11, "is_admin": True}, {"member_id": 22}],
    "profiles": CONVERSATIONS["profiles"],
    "groups": [],
}

SENT = {"items": [{"id": 503, "date": 1788876300, "peer_id": PEER_CHAT, "from_id": ME, "out": 1,
                   "text": "привет из админки", "attachments": []}],
        "profiles": CONVERSATIONS["profiles"], "groups": []}

UPLOADED_VOICE = {"type": "audio_message",
                  "audio_message": {"id": 8, "owner_id": ME, "access_key": "abc", "duration": 3,
                                    "link_mp3": "https://cdn.example/out.mp3",
                                    "link_ogg": "https://cdn.example/out.ogg",
                                    "waveform": [1, 5, 9]}}
