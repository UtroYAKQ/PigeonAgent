"""媒体类型判定：扩展名优先，魔数兜底。"""

from app.domain.media.media_type import detect_media_type, effective_media_type, extension_for

PNG = b"\x89PNG\r\n\x1a\n" + b"pixels"
GIF = b"GIF89a" + b"pixels"
PDF = b"%PDF-1.7"


def test_extension_wins_over_magic() -> None:
    assert detect_media_type("chart.png", PDF) == "image/png"


def test_magic_is_the_fallback() -> None:
    assert detect_media_type("no-extension", PNG) == "image/png"
    assert detect_media_type("no-extension", GIF) == "image/gif"
    assert detect_media_type(None, PDF) == "application/pdf"


def test_unknown_stays_octet_stream() -> None:
    assert detect_media_type("archive.unknown", b"\x00\x01") == "application/octet-stream"


def test_effective_type_prefers_record_and_falls_back_to_name() -> None:
    assert effective_media_type("chart.jpg", "image/png") == "image/png"
    assert effective_media_type("chart.png", "application/octet-stream") == "image/png"
    assert effective_media_type("chart.png", None) == "image/png"


def test_extension_for_matches_readable_image_types() -> None:
    assert extension_for("image/png") == "png"
    assert extension_for("image/jpeg") == "jpg"
    assert extension_for("image/gif") == "gif"
    assert extension_for("image/webp") == "webp"
