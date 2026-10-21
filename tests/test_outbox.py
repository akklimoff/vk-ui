import threading

import pytest

from bot.outbox import Outbox


def test_sent_message_is_recognised_by_its_id_and_by_its_random_id():
    outbox, used = Outbox(), []
    assert outbox.send(lambda random_id: used.append(random_id) or 555) == 555
    assert used[0]
    assert outbox.owns(555, 0)
    assert outbox.owns(None, used[0])


def test_foreign_message_is_not_owned():
    outbox = Outbox()
    outbox.send(lambda random_id: 555)
    assert not outbox.owns(556, 0)
    assert not outbox.owns(None, 0)
    assert not outbox.owns(None, None)


def test_echo_check_waits_for_a_send_in_flight():
    outbox, started, release, answers = Outbox(), threading.Event(), threading.Event(), []

    def deliver(random_id):
        started.set()
        release.wait(5)
        return 777

    sender = threading.Thread(target=outbox.send, args=(deliver,))
    sender.start()
    started.wait(5)
    checker = threading.Thread(target=lambda: answers.append(outbox.owns(777, 0)))
    checker.start()
    checker.join(0.1)
    assert answers == []
    release.set()
    sender.join(5)
    checker.join(5)
    assert answers == [True]


def test_failed_send_propagates_and_leaves_the_outbox_usable():
    outbox = Outbox()

    def broken(random_id):
        raise RuntimeError("сеть")

    with pytest.raises(RuntimeError):
        outbox.send(broken)
    assert outbox.send(lambda random_id: 9) == 9
    assert outbox.owns(9, 0)


def test_answers_that_are_not_message_ids_are_not_remembered():
    outbox = Outbox()
    outbox.send(lambda random_id: True)
    outbox.send(lambda random_id: {"peer_id": 1})
    assert not outbox.owns(1, 0)
    assert not outbox.owns(True, 0)


def test_old_marks_are_forgotten():
    outbox = Outbox(keep=4)
    for message_id in range(1, 6):
        outbox.send(lambda random_id, message_id=message_id: message_id)
    assert not outbox.owns(1, 0)
    assert outbox.owns(5, 0)


def test_every_message_of_a_send_to_several_addressees_is_marked_as_own():
    outbox = Outbox()
    outbox.send(lambda random_id: [{"peer_id": 1, "message_id": 71}, {"peer_id": 2, "message_id": 72},
                                   {"peer_id": 3, "error": {"code": 7}}, "мусор"])
    assert outbox.owns(71, 0) and outbox.owns(72, 0) and not outbox.owns(73, 0)
