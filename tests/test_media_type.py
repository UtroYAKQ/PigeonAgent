"""媒体类型判定：扩展名优先，魔数兜底。"""

from app.domain.media_type import detect_media_type

PNG = b"\x89PNG\r\n\x1a\n" + b"pixels"
PDF = b"%PDF-1.7"


def test_extension_wins_over_magic() -> None:
    assert detect_media_type("chart.png", PDF) == "image/png"


def test_magic_is_the_fallback() -> None:
    assert detect_media_type("no-extension", PNG) == "image/png"
    assert detect_media_type(None, PDF) == "application/pdf"


def test_unknown_stays_octet_stream() -> None:
    assert detect_media_type("archive.unknown", b"\x00\x01") == "application/octet-stream"
