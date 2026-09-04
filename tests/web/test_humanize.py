import pytest

from web.humanize import ago, duration


@pytest.mark.parametrize("seconds, expected", [
    (None, "—"),
    (0, "только что"),
    (4.9, "только что"),
    (45, "45 с назад"),
    (150, "2 мин назад"),
    (3599, "59 мин назад"),
    (7200, "2 ч назад"),
    (200000, "2 д назад"),
])
def test_ago(seconds, expected):
    assert ago(seconds) == expected


@pytest.mark.parametrize("seconds, expected", [
    (None, "—"),
    (45, "45 с"),
    (150, "2 мин"),
    (3720, "1 ч 2 мин"),
    (90000, "1 д 1 ч"),
])
def test_duration(seconds, expected):
    assert duration(seconds) == expected
