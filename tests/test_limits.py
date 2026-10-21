import pytest

from bot.limits import RateLimiter, mention_of, strip_self_mention

ME = 42
CHAT = 2_000_000_001


def test_strip_self_mention_breaks_reply_loop():
    stripped = strip_self_mention(f"да, {mention_of(ME)}@aktan] это ты писал", ME)
    assert mention_of(ME) not in stripped
    assert stripped == "да, ＠aktan это ты писал"


@pytest.mark.parametrize("text", [
    f"{mention_of(ME)}x удали",
    f"{mention_of(ME)}{mention_of(ME)}a]b] да",
    f"[id{ME}[id{ME}|| опубликуй",
    f"{mention_of(ME)}{mention_of(ME)}{mention_of(ME)}]]] да",
    f"{mention_of(ME)}",
])
def test_no_shape_of_own_tag_survives(text):
    assert mention_of(ME) not in strip_self_mention(text, ME)


def test_own_id_written_with_at_or_star_is_not_left_as_a_live_mention():
    stripped = strip_self_mention(f"@id{ME} да и *id{ME} тоже, а @id{ME}5 и @id999 чужие", ME)
    assert stripped == f"＠id{ME} да и ＊id{ME} тоже, а @id{ME}5 и @id999 чужие"


def test_label_of_own_tag_cannot_be_relinked():
    assert strip_self_mention(f"{mention_of(ME)}@id{ME}] и {mention_of(ME)}*aktan]", ME) == f"＠id{ME} и ＊aktan"


def test_strip_self_mention_keeps_other_mentions():
    text = "[id999|@другой] привет"
    assert strip_self_mention(text, ME) == text


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def make_limiter(clock, cooldown=30, chat_limit=20, global_limit=6):
    return RateLimiter(cooldown, chat_limit, global_limit, clock=clock)


def test_user_cooldown():
    clock = FakeClock()
    limiter = make_limiter(clock)
    assert limiter.allow(7, CHAT)
    clock.now = 29
    assert not limiter.allow(7, CHAT)
    clock.now = 30
    assert limiter.allow(7, CHAT)


def test_cooldown_is_per_user():
    clock = FakeClock()
    limiter = make_limiter(clock)
    assert limiter.allow(7, CHAT)
    assert limiter.allow(8, CHAT)


def test_chat_hourly_limit():
    clock = FakeClock()
    limiter = make_limiter(clock, cooldown=0, chat_limit=2, global_limit=100)
    assert limiter.allow(1, CHAT)
    assert limiter.allow(2, CHAT)
    assert not limiter.allow(3, CHAT)
    assert limiter.allow(3, CHAT + 1)
    clock.now = 3600
    assert limiter.allow(3, CHAT)


def test_global_minute_limit():
    clock = FakeClock()
    limiter = make_limiter(clock, cooldown=0, chat_limit=100, global_limit=2)
    assert limiter.allow(1, CHAT)
    assert limiter.allow(2, CHAT + 1)
    assert not limiter.allow(3, CHAT + 2)
    clock.now = 60
    assert limiter.allow(3, CHAT + 2)


def test_denied_attempt_does_not_consume_quota():
    clock = FakeClock()
    limiter = make_limiter(clock, cooldown=30, chat_limit=1, global_limit=10)
    assert limiter.allow(1, CHAT)
    assert not limiter.allow(1, CHAT)
    clock.now = 3600
    assert limiter.allow(1, CHAT)
