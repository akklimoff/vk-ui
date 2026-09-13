import subprocess

MAX_VOICE_BYTES = 20 * 1024 * 1024
FFMPEG_TIMEOUT = 60
ACCEPTED = "Нужен .ogg (Opus) или .mp3"
# VK принимает голосовые только как Ogg Opus; моно 48 кГц — то, что пишет сам клиент VK
FFMPEG_TO_OPUS = ["ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-vn", "-c:a", "libopus",
                  "-b:a", "48k", "-ar", "48000", "-ac", "1", "-f", "ogg", "pipe:1"]


def sniff_voice(data: bytes, filename: str) -> str:
    if not data:
        raise ValueError("Файл пуст")
    if len(data) > MAX_VOICE_BYTES:
        raise ValueError(f"Файл больше {MAX_VOICE_BYTES // (1024 * 1024)} МБ")
    if data[:4] == b"OggS":
        return "ogg"
    # mp3 начинается либо с тега ID3, либо сразу с MPEG-фрейма (11 бит синхронизации)
    if data[:3] == b"ID3" or (len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return "mp3"
    raise ValueError(f"{ACCEPTED}, а не «{filename}»")


def to_ogg(data: bytes, run=subprocess.run) -> bytes:
    try:
        done = run(FFMPEG_TO_OPUS, input=data, capture_output=True, timeout=FFMPEG_TIMEOUT)
    except FileNotFoundError:
        raise ValueError("ffmpeg не установлен, mp3 сконвертировать нечем") from None
    except subprocess.TimeoutExpired:
        raise ValueError("ffmpeg не уложился в минуту") from None
    if done.returncode != 0 or not done.stdout:
        tail = done.stderr.decode(errors="replace").strip().splitlines()[-1:] or ["без деталей"]
        raise ValueError(f"Не удалось сконвертировать mp3: {tail[0]}")
    return done.stdout


def prepare_voice(data: bytes, filename: str, run=subprocess.run) -> bytes:
    return data if sniff_voice(data, filename) == "ogg" else to_ogg(data, run=run)
