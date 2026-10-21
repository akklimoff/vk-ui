from tests.web.im_fixtures import CONVERSATIONS, HISTORY, ME, SENT


class FakeVk:
    me_id = ME

    def __init__(self, token):
        self.calls = []
        self.sent = False

    def conversations(self, count=60, offset=0):
        self.calls.append(("conversations", count, offset))
        return CONVERSATIONS

    def history_page(self, peer_id, count, before_id=None):
        self.calls.append(("history", peer_id, count, before_id))
        return {**HISTORY, "items": SENT["items"] + HISTORY["items"]} if self.sent else HISTORY

    def send(self, peer_id, text="", reply_to=None, attachment=""):
        self.calls.append(("send", peer_id, text, reply_to, attachment))
        self.sent = True
        return 503

    def mark_read(self, peer_id):
        self.calls.append(("read", peer_id))

    def delete_message(self, message_id):
        self.calls.append(("delete", message_id))

    def upload_photos(self, peer_id, photos):
        self.calls.append(("photos", peer_id, [ext for _, ext in photos]))
        return [f"photo1_{i}_key" for i, _ in enumerate(photos)]

    def search_conversations(self, query, count):
        self.calls.append(("search", query, count))
        return {"count": 1, "items": [CONVERSATIONS["items"][1]["conversation"]], "profiles": CONVERSATIONS["profiles"]}

    def upload_voice(self, peer_id, data, ext):
        self.calls.append(("voice", peer_id, len(data), ext))
        return "audio_message1_8_abc"
