from ai.service import ReplyResult


class FakeAi:
    def __init__(self, settings=None, parts=("ответ из песочницы",)):
        self.requests = []
        self.parts = parts

    def reply(self, req):
        self.requests.append(req)
        return ReplyResult(tuple(self.parts), False, req.model or "grok-4.3",
                           req.transcript or "\n".join(f"{line.author}: {line.text}" for line in req.lines))
