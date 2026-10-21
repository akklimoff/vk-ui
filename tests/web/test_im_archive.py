from web.im.archive import Archive


def test_archive_is_cached_for_a_while_and_refetched_on_demand():
    clock, asked = [0.0], []

    def fetch():
        asked.append(clock[0])
        return {len(asked)}

    archive = Archive(fetch, ttl=10, now=lambda: clock[0])
    assert archive.peers() == {1}
    clock[0] = 9
    assert archive.peers() == {1}
    assert archive.peers(fresh=True) == {2}
    clock[0] = 19.5
    assert archive.peers() == {3} and asked == [0, 9, 19.5]
