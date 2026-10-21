from dataclasses import fields

from bot.runtime import RuntimeSettings, dump_runtime, parse_runtime, persona_for, personas_of, runtime_defaults


def test_missing_keys_take_defaults():
    d = RuntimeSettings(temperature=0.5, active_persona="v")
    assert parse_runtime({}, d) == d


def test_fields_are_parsed_and_coerced():
    rt = parse_runtime(
        {"active_persona": "valya", "active_model": " claude-opus-5 ", "paused": True,
         "paused_peers": ["2000000005", 7],
         "peer_personas": {"2000000362": ["rina", "monika", "rina"], "5": " ", "6": "m"}, "temperature": "0.9"},
        RuntimeSettings(),
    )
    assert rt.active_persona == "valya"
    assert rt.active_model == "claude-opus-5"
    assert rt.paused is True
    assert dict(rt.peer_personas) == {6: ("m",), 2000000362: ("rina", "monika")}
    assert persona_for(rt, 2000000362, pick=max) == "rina"
    assert persona_for(rt, 6) == "m"
    assert persona_for(rt, 1) == "valya"
    assert personas_of(rt, 2000000362) == ("rina", "monika") and personas_of(rt, 1) == ("valya",)
    assert persona_for(rt, 2000000362, pick=max, called={"monika"}) == "monika"
    assert persona_for(rt, 2000000362, pick=max, called={"valya"}) == "rina"
    assert persona_for(RuntimeSettings(), 1) == "" and personas_of(RuntimeSettings(), 1) == ()
    assert rt.paused_peers == frozenset({2000000005, 7})
    assert rt.temperature == 0.9


def test_settings_of_the_old_reply_path_are_gone_and_ignored_in_the_file():
    assert [f.name for f in fields(RuntimeSettings)] == ["active_persona", "active_model", "peer_personas", "paused",
                                                         "paused_peers", "temperature"]
    old = {"reply_delay_min": 5, "reply_delay_max": 1, "context_messages": "30", "dm_debounce_seconds": "мусор",
           "mark_read": False}
    assert parse_runtime(old, RuntimeSettings()) == RuntimeSettings()


def test_defaults_come_from_the_temperature_in_env():
    class Env:
        llm_temperature = 0.3

    assert runtime_defaults(Env()) == RuntimeSettings(temperature=0.3)


def test_dump_roundtrip():
    rt = RuntimeSettings(active_persona="v", paused_peers=frozenset({1, 2}),
                         peer_personas=((3, ("m",)), (4, ("a", "b"))))
    assert parse_runtime(dump_runtime(rt), RuntimeSettings()) == rt
    assert dump_runtime(rt)["paused_peers"] == [1, 2]
    assert dump_runtime(rt)["peer_personas"] == {"3": "m", "4": ["a", "b"]}
    assert set(dump_runtime(rt)) == {"active_persona", "active_model", "peer_personas", "paused", "paused_peers",
                                     "temperature"}
