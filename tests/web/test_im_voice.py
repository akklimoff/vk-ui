import shutil
import subprocess

import pytest

from web.im.voice import MAX_VOICE_BYTES, prepare_voice, sniff_voice, to_ogg

OGG = b"OggS" + b"\0" * 40
MP3 = b"ID3\x04" + b"\0" * 40


def test_sniff_by_magic_bytes_not_extension():
    assert sniff_voice(OGG, "whatever.bin") == "ogg"
    assert sniff_voice(MP3, "voice.mp3") == "mp3"
    assert sniff_voice(b"\xff\xfb\x90\x00" + b"\0" * 40, "voice.mp3") == "mp3"


def test_sniff_rejects_other_files():
    with pytest.raises(ValueError, match="ogg"):
        sniff_voice(b"RIFF....WAVE" + b"\0" * 40, "voice.wav")
    with pytest.raises(ValueError, match="пуст"):
        sniff_voice(b"", "voice.ogg")


def test_sniff_rejects_oversize():
    with pytest.raises(ValueError, match="20"):
        sniff_voice(b"OggS" + b"\0" * MAX_VOICE_BYTES, "v.ogg")


def test_to_ogg_pipes_through_ffmpeg():
    seen = {}

    def run(cmd, **kw):
        seen["cmd"], seen["input"] = cmd, kw["input"]
        return subprocess.CompletedProcess(cmd, 0, stdout=OGG, stderr=b"")

    assert to_ogg(MP3, run=run) == OGG
    assert seen["input"] == MP3 and seen["cmd"][0] == "ffmpeg" and "libopus" in seen["cmd"]
    assert "pipe:0" in seen["cmd"] and "pipe:1" in seen["cmd"]


def test_to_ogg_reports_ffmpeg_failure_and_absence():
    def fails(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"Invalid data found")

    with pytest.raises(ValueError, match="Invalid data"):
        to_ogg(MP3, run=fails)

    def missing(cmd, **kw):
        raise FileNotFoundError

    with pytest.raises(ValueError, match="ffmpeg"):
        to_ogg(MP3, run=missing)


def test_prepare_voice_passes_ogg_through_and_converts_mp3():
    assert prepare_voice(OGG, "v.ogg", run=lambda *a, **k: pytest.fail("ogg не конвертируем")) == OGG
    converted = prepare_voice(MP3, "v.mp3", run=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, OGG, b""))
    assert converted == OGG


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="нужен ffmpeg")
def test_real_ffmpeg_converts_mp3_to_opus():
    mp3 = subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.3",
                          "-c:a", "libmp3lame", "-f", "mp3", "pipe:1"], capture_output=True, check=True).stdout
    ogg = to_ogg(mp3)
    assert ogg[:4] == b"OggS" and b"OpusHead" in ogg[:200]
