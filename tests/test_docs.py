import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPOSE_ONLY = {"WEB_DOMAIN"}


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def known_settings() -> set[str]:
    from web.config import Settings

    return {name.upper() for name in Settings.model_fields} | COMPOSE_ONLY


def test_readme_names_only_settings_that_exist():
    named = set(re.findall(r"`([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)(?:=[^`]*)?`", read("README.md")))
    assert named and named <= known_settings(), named - known_settings()


def test_env_example_names_only_settings_that_exist():
    named = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", read(".env.example"), flags=re.M))
    assert named and named <= known_settings(), named - known_settings()


def test_env_example_shows_the_real_defaults():
    from web.config import Settings

    defaults = {name.upper(): field.default for name, field in Settings.model_fields.items()}
    shown = re.findall(r"^# ([A-Z][A-Z0-9_]+)=(\S+)$", read(".env.example"), flags=re.M)
    assert shown
    for name, value in shown:
        assert value == str(defaults[name]), name


def test_panel_listens_on_loopback_locally_and_on_every_interface_in_its_image():
    from web.config import Settings

    assert Settings(vk_token="vk", _env_file=None).web_host == "127.0.0.1"
    assert "ENV WEB_HOST=0.0.0.0" in read("Dockerfile").splitlines()
    assert "reverse_proxy web:8080" in read("Caddyfile")
    assert "127.0.0.1:8080" in read("README.md")


def test_panel_is_served_over_https_on_port_8080():
    assert "{$WEB_DOMAIN}:8080 {" in read("Caddyfile") and "tls internal" in read("Caddyfile")
    assert '"8080:8080"' in read("docker-compose.yml") and "443" not in read("docker-compose.yml")
    assert "https://<WEB_DOMAIN>:8080" in read("README.md")


def test_image_and_compose_take_nothing_from_outside_the_repo_and_keep_no_panel_data():
    compose = read("docker-compose.yml")
    for foreign in ("external", "BOT_", "vk_mcp", "/app/state", "/app/config", "AI_URL"):
        assert foreign not in compose, foreign
    for name in ("docker-compose.yml", "Dockerfile", ".env.example"):
        assert "../" not in read(name) and "vk_mcp" not in read(name) and "vk-mcp" not in read(name), name


def test_agent_docs_are_identical_and_carry_the_mandatory_rules():
    assert read("CLAUDE.md") == read("AGENTS.md")
    assert "## Mandatory project rules" in read("CLAUDE.md")
