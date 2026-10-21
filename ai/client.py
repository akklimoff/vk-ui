import httpx

from ai.contract import dump, load_model, load_preview, load_step


class AiError(RuntimeError):
    pass


class AiClient:
    """Тот же интерфейс, что у AiService, но через HTTP к контейнеру ai."""

    def __init__(self, base_url: str, timeout: float, http=None):
        self._http = http if http is not None else httpx.Client(base_url=base_url, timeout=timeout)

    def _call(self, method: str, path: str, **kw):
        try:
            response = self._http.request(method, path, **kw)
        except httpx.HTTPError as e:
            raise AiError(f"ИИ-сервис недоступен: {e}") from None
        if response.status_code >= 400:
            raise AiError(f"ИИ-сервис ответил {response.status_code}: {response.text[:300]}")
        return response.json()

    def step(self, req):
        return load_step(self._call("POST", "/v1/agent/step", json=dump(req)))

    def models(self):
        return [load_model(m) for m in self._call("GET", "/v1/models")]

    def model_id(self, model: str = "") -> str:
        return self._call("GET", "/v1/model-id", params={"model": model})["model_id"]

    def agent_preview(self, persona: str, peer_note: str = ""):
        return load_preview(self._call("POST", "/v1/agent/preview", json={"persona": persona, "peer_note": peer_note}))

    def scrub(self, text: str) -> str:
        # ключи знает только ИИ-сервис, его ошибки приходят уже вычищенными
        return text


def ai_backend(settings):
    if settings.ai_url:
        return AiClient(settings.ai_url, settings.ai_timeout_seconds)
    from ai.config import AiSettings
    from ai.service import AiService

    return AiService(AiSettings())
