from __future__ import annotations

import base64
import random
from pathlib import Path

from PIL import Image

from src.config import ParamValue
from src.param_resolver import resolve_param_value
from src.utils import image_to_base64


def _decode_data_uri(data_uri: str) -> bytes:
    return base64.b64decode(data_uri.split(",", 1)[1])


def _make_noise_rgb(path: Path, size: tuple[int, int] = (256, 256)) -> None:
    rng = random.Random(42)
    pixels = [
        (rng.randrange(256), rng.randrange(256), rng.randrange(256))
        for _ in range(size[0] * size[1])
    ]
    img = Image.new("RGB", size)
    img.putdata(pixels)
    img.save(path, format="PNG")


def test_none_mode_keeps_jfif_with_jpeg_mime(tmp_path: Path) -> None:
    src = tmp_path / "sample.jfif"
    Image.new("RGB", (32, 32), color=(200, 100, 50)).save(src, format="JPEG")
    encoded = image_to_base64(src, with_prefix=True, image_encode="none")
    assert encoded.startswith("data:image/jpeg;base64,")


def test_none_mode_tiff_mime_mapping(tmp_path: Path) -> None:
    src = tmp_path / "sample.tiff"
    Image.new("RGB", (16, 16), color=(10, 20, 30)).save(src, format="TIFF")
    encoded = image_to_base64(src, with_prefix=True, image_encode="none")
    assert encoded.startswith("data:image/tiff;base64,")


def test_smart_jpeg_converts_rgb_png_when_smaller(tmp_path: Path) -> None:
    src = tmp_path / "noise.png"
    _make_noise_rgb(src)

    plain = image_to_base64(src, with_prefix=True, image_encode="none")
    smart = image_to_base64(
        src,
        with_prefix=True,
        image_encode="smart_jpeg",
        jpeg_quality=95,
    )

    assert plain.startswith("data:image/png;base64,")
    assert smart.startswith("data:image/jpeg;base64,")
    assert len(_decode_data_uri(smart)) < len(_decode_data_uri(plain))


def test_smart_jpeg_keeps_transparent_png(tmp_path: Path) -> None:
    src = tmp_path / "alpha.png"
    Image.new("RGBA", (32, 32), color=(255, 0, 0, 128)).save(src, format="PNG")
    encoded = image_to_base64(src, with_prefix=True, image_encode="smart_jpeg")
    assert encoded.startswith("data:image/png;base64,")


def test_smart_jpeg_keeps_animated_gif(tmp_path: Path) -> None:
    src = tmp_path / "anim.gif"
    frame1 = Image.new("RGB", (24, 24), color=(255, 0, 0))
    frame2 = Image.new("RGB", (24, 24), color=(0, 255, 0))
    frame1.save(src, save_all=True, append_images=[frame2], duration=120, loop=0)

    encoded = image_to_base64(src, with_prefix=True, image_encode="smart_jpeg")
    assert encoded.startswith("data:image/gif;base64,")


def test_smart_jpeg_corrupt_file_fallback(tmp_path: Path) -> None:
    src = tmp_path / "broken.png"
    raw = b"not-an-image"
    src.write_bytes(raw)

    encoded = image_to_base64(src, with_prefix=True, image_encode="smart_jpeg")
    assert encoded.startswith("data:image/png;base64,")
    assert _decode_data_uri(encoded) == raw


def test_param_resolver_passes_image_encode_options(tmp_path: Path) -> None:
    src = tmp_path / "noise.png"
    _make_noise_rgb(src)

    param = ParamValue.model_validate(
        {
            "glob": "*.png",
            "as": "base64",
            "image_encode": "smart_jpeg",
            "jpeg_quality": 95,
        }
    )
    values = resolve_param_value(param, base_dir=tmp_path)

    assert len(values) == 1
    encoded, meta = values[0]
    assert isinstance(encoded, str)
    assert encoded.startswith("data:image/jpeg;base64,")
    assert meta["filename"] == "noise"
