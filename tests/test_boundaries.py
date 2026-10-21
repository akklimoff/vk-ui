import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


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


def test_the_panel_is_the_only_package():
    packages = {p.parent.name for p in ROOT.glob("*/__init__.py")}
    assert packages == {"web", "tests"}


def test_vk_api_only_in_web_vk():
    assert {f for f, names in imports_of("web").items() if "vk_api" in names} == {"web/vk.py"}
