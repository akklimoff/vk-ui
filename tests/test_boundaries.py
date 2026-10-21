import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# что панель берёт из ядра: форматы файлов config/ и state/, решения агента и исполнение (VK, dry-run, ИИ)
CORE_FOR_PANEL = {
    "bot.access", "bot.config", "bot.runtime", "bot.status", "bot.agent.journal", "bot.agent.rejections",
    "ai.personas",
    "bot.agent", "bot.agent.gate", "bot.limits", "bot.agent.loop",
    "bot.vk", "bot.agent.request", "bot.agent.pictures", "bot.reply",
    "ai.client", "ai.catalog", "ai.contract", "common.redact",
}
# сам бот в панели не нужен: ни long poll, ни очередь просьб, ни HTTP-сервис ИИ
BOT_ONLY = ("bot/main.py", "bot/agent/worker.py", "bot/names.py", "bot/privacy.py", "ai/http.py")


def imports_of(package: str) -> dict[str, set[str]]:
    found = {}
    for path in (ROOT / package).rglob("*.py"):
        names = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names.add(node.module.split(".")[0])
        found[str(path.relative_to(ROOT))] = names
    return found


def offenders(package: str, forbidden: set[str]) -> dict[str, set[str]]:
    return {f: bad for f, names in imports_of(package).items() if (bad := names & forbidden)}


def modules_of(package: str) -> dict[str, set[str]]:
    found = {}
    for path in (ROOT / package).rglob("*.py"):
        names = set()
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.Import):
                names |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names.add(node.module)
        found[str(path.relative_to(ROOT))] = names
    return found


def test_ai_knows_nothing_about_vk_or_the_panel():
    assert offenders("ai", {"bot", "web", "vk_api"}) == {}


def test_common_depends_on_nothing_in_project():
    assert offenders("common", {"ai", "bot", "web", "vk_api", "openai"}) == {}


def test_llm_sdk_only_in_ai_llm_and_vk_api_only_in_bot_vk():
    everywhere = {**imports_of("ai"), **imports_of("bot"), **imports_of("web")}
    assert {f for f, n in everywhere.items() if "openai" in n} == {"ai/llm.py"}
    assert {f for f, n in everywhere.items() if "vk_api" in n} == {"bot/vk.py"}


LLM_ONLY_SETTINGS = {"llm_api_key", "xai_api_key", "anthropic_api_key", "openai_api_key", "deepseek_api_key",
                     "moonshot_api_key", "llm_workspace_id", "persona_prompt", "agent_prompt"}


def test_panel_settings_hold_no_llm_secrets_or_prompts():
    from bot.config import Settings

    assert LLM_ONLY_SETTINGS & set(Settings.model_fields) == set()


AI_INTERNALS = {"ai.llm", "ai.service", "ai.config", "ai.http"}


def test_panel_and_core_reach_ai_only_through_contract_and_client():
    for package in ("bot", "web"):
        assert {f: n & AI_INTERNALS for f, n in modules_of(package).items() if n & AI_INTERNALS} == {}


def test_agent_takes_only_the_contract_from_ai():
    for file, names in modules_of("bot/agent").items():
        assert {n for n in names if n.split(".")[0] == "ai"} <= {"ai.contract"}, file


# решения агента — чистые функции: фильтр и права не могут сходить в VK, даже по ошибке
DECISION_MODULES = ("gate", "methods", "policy", "tool", "pending", "texts", "journal", "request", "rejections")


def test_agent_decisions_do_not_import_the_vk_client():
    files = modules_of("bot/agent")
    for name in DECISION_MODULES:
        assert "bot.vk" not in files[f"bot/agent/{name}.py"], name


def test_panel_takes_only_the_listed_modules_from_the_core():
    for file, names in modules_of("web").items():
        core = {n for n in names if n.split(".")[0] in ("ai", "bot", "common")}
        assert core <= CORE_FOR_PANEL, (file, core - CORE_FOR_PANEL)


def test_the_bot_itself_stays_out_of_the_panel():
    for path in BOT_ONLY:
        assert not (ROOT / path).exists(), path
