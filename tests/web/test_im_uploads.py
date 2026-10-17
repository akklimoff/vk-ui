import pytest

from web.im.uploads import MAX_PHOTOS, prepare_photos, sniff_photo


def test_photo_type_comes_from_the_signature():
    assert sniff_photo(b"\xff\xd8\xff\xe0rest", "a.png") == "jpg"
    assert sniff_photo(b"\x89PNG\r\n\x1a\nrest", "image.png") == "png"
    assert sniff_photo(b"GIF89a...", "x") == "gif"
    assert sniff_photo(b"RIFF\x00\x00\x00\x00WEBPVP8 ", "x") == "webp"


def test_not_a_picture_or_too_many_is_refused():
    with pytest.raises(ValueError, match="JPEG"):
        sniff_photo(b"%PDF-1.7", "doc.pdf")
    with pytest.raises(ValueError, match="пуст"):
        sniff_photo(b"", "a.jpg")
    with pytest.raises(ValueError, match=str(MAX_PHOTOS)):
        prepare_photos([(b"\xff\xd8\xff", "a.jpg")] * (MAX_PHOTOS + 1))
