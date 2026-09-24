from ai.contract import ModelInfo, ReplyResult


class FakeAi:
    def __init__(self, settings=None, parts=("ответ из песочницы",)):
        self.requests = []
        self.parts = parts

    def reply(self, req):
        self.requests.append(req)
        return ReplyResult(tuple(self.parts), False, req.model or "grok-4.3",
                           req.transcript or "\n".join(f"{line.author}: {line.text}" for line in req.lines))

    def models(self):
        return [ModelInfo("grok-4.6", "Grok 4.6", "grok", "Grok"),
                ModelInfo("claude-opus-5", "Claude Opus 5", "claude", "Claude")]

    def model_id(self, model=""):
        return model or "grok-4.3"

    def scrub(self, text):
        return text.replace("xai-KEY", "[скрыто]")
