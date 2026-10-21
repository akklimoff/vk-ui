from zoneinfo import ZoneInfo

import pytest

from web.humanize import clock, mmss, plural, short_since


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
