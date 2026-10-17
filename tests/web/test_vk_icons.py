import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web"


def used_icons() -> set[str]:
    used = set()
    for path in (WEB / "templates").rglob("*.html"):
        text = path.read_text()
        used |= set(re.findall(r"""icon\(['"]([a-z0-9_]+)['"]""", text))
        used |= set(re.findall(r"vk-icons\.svg(?:'\) }})?#([a-z0-9_]+)", text))
    return used


def test_every_icon_used_in_templates_is_in_the_sprite():
    from web.render import NAV
    sprite = (WEB / "static" / "vk-icons.svg").read_text()
    have = set(re.findall(r'<symbol id="([a-z0-9_]+)"', sprite))
    used = used_icons() | {item.icon for item in NAV}
    assert used and used <= have, used - have


def test_sprite_keeps_the_mit_notice_and_uses_current_color():
    sprite = (WEB / "static" / "vk-icons.svg").read_text()
    assert "MIT" in sprite and "VK LLC" in sprite
    assert 'fill="currentColor"' in sprite and "#000" not in sprite


def test_sprite_is_well_formed_xml():
    import xml.etree.ElementTree as ET

    # браузер бросает разбор спрайта на первой ошибке, и все иконки после неё молча пропадают
    root = ET.parse(WEB / "static" / "vk-icons.svg").getroot()
    assert len(root) == len(re.findall(r"<symbol ", (WEB / "static" / "vk-icons.svg").read_text()))
