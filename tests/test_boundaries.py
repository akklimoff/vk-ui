import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GONE = ("ai", "bot", "common", "config")
LLM_SDKS = {"openai", "anthropic"}


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


def test_the_panel_is_one_package_without_the_agent_core():
    for name in GONE:
        assert not (ROOT / name).exists(), name
    assert {n for names in imports_of("web").values() for n in names} & set(GONE) == set()


def test_vk_api_only_in_web_vk():
    assert {f for f, names in imports_of("web").items() if "vk_api" in names} == {"web/vk.py"}


def test_no_llm_anywhere():
    assert {f for f, names in imports_of("web").items() if names & LLM_SDKS} == set()
    required = {line.split("=")[0].split("[")[0].strip().lower() for line in
                (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines() if line.strip()}
    assert required & LLM_SDKS == set()
