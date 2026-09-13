from zoneinfo import ZoneInfo

import pytest

from web.humanize import ago, clock, duration, mmss, plural, short_since


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


def test_clock_and_mmss():
    assert clock(1788876240, ZoneInfo("Europe/Moscow")) == "17:04"
    assert mmss(20) == "0:20" and mmss(75) == "1:15"


@pytest.mark.parametrize("n, expected", [
    (1, "1 участник"), (3, "3 участника"), (5, "5 участников"), (11, "11 участников"),
    (21, "21 участник"), (23, "23 участника"), (112, "112 участников"),
])
def test_plural(n, expected):
    assert plural(n, "участник", "участника", "участников") == expected


def test_short_since():
    tz = ZoneInfo("Europe/Moscow")
    now = 1788876240
    assert short_since(now - 30, now, tz) == "1м"
    assert short_since(now - 300, now, tz) == "5м"
    assert short_since(now - 3 * 3600, now, tz) == "3ч"
    assert short_since(now - 5 * 86400, now, tz) == "5д"
    assert short_since(1786525200, now, tz) == "12 авг"
