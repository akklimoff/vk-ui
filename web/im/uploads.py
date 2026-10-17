MAX_PHOTO_BYTES = 20 * 1024 * 1024
MAX_PHOTOS = 10


def sniff_photo(data: bytes, filename: str) -> str:
    """Тип картинки по сигнатуре, а не по имени: из буфера обмена файл приходит как image.png при любом содержимом."""
    if not data:
        raise ValueError(f"Файл «{filename}» пуст")
    if len(data) > MAX_PHOTO_BYTES:
        raise ValueError(f"«{filename}» больше {MAX_PHOTO_BYTES // (1024 * 1024)} МБ")
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    raise ValueError(f"Фото нужно в JPEG, PNG, GIF или WebP, а не «{filename}»")


def prepare_photos(files: list[tuple[bytes, str]]) -> list[tuple[bytes, str]]:
    if len(files) > MAX_PHOTOS:
        raise ValueError(f"За раз не больше {MAX_PHOTOS} фото")
    return [(data, sniff_photo(data, name)) for data, name in files]
