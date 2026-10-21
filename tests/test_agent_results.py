from bot.agent.results import best_size, slim

SIZES = [{"type": "s", "url": "https://sun1.userapi.com/s.jpg", "width": 75, "height": 50},
         {"type": "z", "url": "https://sun1.userapi.com/z.jpg", "width": 1280, "height": 853},
         {"type": "w", "url": "https://sun1.userapi.com/w.jpg", "width": 2560, "height": 1706}]


def test_the_largest_copy_that_is_not_too_wide_is_chosen():
    assert best_size(SIZES) == "https://sun1.userapi.com/z.jpg"
    assert best_size(SIZES[2:]) == "https://sun1.userapi.com/w.jpg"
    assert best_size([]) == "" and best_size([{"type": "s"}, "мусор"]) == ""


def test_a_photo_keeps_its_address_and_ids_and_loses_the_list_of_copies():
    photo = {"id": 7, "owner_id": 5, "access_key": "k", "sizes": SIZES, "text": "", "has_tags": False,
             "orig_photo": {"url": "https://sun1.userapi.com/o.jpg"}}
    assert slim(photo) == {"id": 7, "owner_id": 5, "access_key": "k", "url": "https://sun1.userapi.com/z.jpg"}


def test_service_fields_and_empty_values_go_and_the_message_stays():
    message = {"id": 3, "from_id": 5, "text": "привет", "out": 0, "random_id": 0, "important": False,
               "is_hidden": False, "attachments": [], "fwd_messages": [], "reply_message": None,
               "conversation_message_id": 12}
    assert slim({"count": 1, "items": [message]}) == {
        "count": 1, "items": [{"id": 3, "from_id": 5, "text": "привет", "out": 0, "conversation_message_id": 12}]}


def test_flags_the_model_may_have_asked_for_stay():
    profile = {"id": 5, "can_write_private_message": 1, "can_post": 0, "is_closed": False}
    assert slim(profile) == profile


def test_zero_and_false_are_values_and_not_emptiness():
    assert slim({"count": 0, "online": False, "items": [0, False, "", None, [], {}]}) == {
        "count": 0, "online": False, "items": [0, False]}


def test_bare_values_pass_through():
    assert slim(1) == 1 and slim("текст") == "текст" and slim(None) is None


def test_small_avatars_and_online_details_nobody_asked_for_go():
    member = {"id": 5, "first_name": "Аня", "last_name": "Ким", "screen_name": "anya", "online": 1,
              "photo_50": "https://sun1.userapi.com/a50.jpg", "photo_100": "https://sun1.userapi.com/a100.jpg",
              "online_info": {"visible": True, "is_online": True, "app_id": 2274003, "last_seen": 1791000000},
              "can_access_closed": True, "is_closed": False}
    assert slim({"items": [{"member_id": 5, "is_admin": True}], "profiles": [member]}) == {
        "items": [{"member_id": 5, "is_admin": True}],
        "profiles": [{"id": 5, "first_name": "Аня", "last_name": "Ким", "screen_name": "anya", "online": 1,
                      "is_closed": False}]}


def test_the_avatar_the_model_asked_for_stays():
    profile = {"id": 5, "photo_max_orig": "https://sun1.userapi.com/max.jpg", "photo_200": "https://sun1.userapi.com/200.jpg"}
    assert slim(profile) == profile
