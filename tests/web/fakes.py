from ai.contract import ModelInfo


class FakeAi:
    def __init__(self, settings=None):
        self.requests = []

    def models(self):
        return [ModelInfo("grok-4.6", "Grok 4.6", "grok", "Grok"),
                ModelInfo("claude-opus-5", "Claude Opus 5", "claude", "Claude")]

    def model_id(self, model=""):
        return model or "grok-4.3"

    def scrub(self, text):
        return text.replace("xai-KEY", "[скрыто]")
