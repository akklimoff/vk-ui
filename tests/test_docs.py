import json
import re
from pathlib import Path

from bot.runtime import RuntimeSettings, dump_runtime, parse_runtime

ROOT = Path(__file__).resolve().parent.parent
COMPOSE_ONLY = {"WEB_DOMAIN", "BOT_CONFIG_DIR", "BOT_STATE_VOLUME", "BOT_NETWORK"}


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def known_settings() -> set[str]:
    from ai.config import AiSettings
    from bot.config import Settings

    return {name.upper() for name in (*Settings.model_fields, *AiSettings.model_fields)} | COMPOSE_ONLY


def test_runtime_example_holds_only_live_settings():
    data = json.loads(read("config/runtime.example.json"))
    assert set(data) == set(dump_runtime(RuntimeSettings()))
    rt = parse_runtime(data, RuntimeSettings())
    assert rt.active_persona and all(peer > 2_000_000_000 for peer, _ in rt.peer_personas)


def test_readme_names_only_settings_that_exist():
    named = set(re.findall(r"`([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)(?:=[^`]*)?`", read("README.md")))
    assert named and named <= known_settings(), named - known_settings()


def test_env_example_names_only_settings_that_exist():
    named = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", read(".env.example"), flags=re.M))
    assert named and named <= known_settings(), named - known_settings()


def test_env_example_shows_the_real_defaults():
    from ai.config import AiSettings
    from bot.config import Settings

    defaults = {name.upper(): field.default
                for name, field in (*AiSettings.model_fields.items(), *Settings.model_fields.items())}
    shown = re.findall(r"^# ([A-Z][A-Z0-9_]+)=([0-9.]+)$", read(".env.example"), flags=re.M)
    assert {"USER_COOLDOWN_SECONDS", "GLOBAL_LIMIT_PER_MINUTE", "AGENT_MAX_STEPS"} <= {name for name, _ in shown}
    for name, value in shown:
        assert float(value) == float(defaults[name]), name


def test_panel_listens_on_loopback_locally_and_on_every_interface_in_its_image():
    from bot.config import Settings

    assert Settings(vk_token="vk", _env_file=None).web_host == "127.0.0.1"
    assert "ENV WEB_HOST=0.0.0.0" in read("Dockerfile").splitlines()
    assert "reverse_proxy web:8080" in read("Caddyfile")
    assert "127.0.0.1:8080" in read("README.md")


def test_image_and_compose_take_nothing_from_outside_the_repo():
    compose = read("docker-compose.yml")
    for place in ("${BOT_CONFIG_DIR", "${BOT_STATE_VOLUME", "${BOT_NETWORK", "/app/state:ro"):
        assert place in compose, place
    for name in ("docker-compose.yml", "Dockerfile"):
        assert "../" not in read(name), name


def test_agent_docs_are_identical_and_carry_the_mandatory_rules():
    assert read("CLAUDE.md") == read("AGENTS.md")
    assert "## Mandatory project rules" in read("CLAUDE.md")
