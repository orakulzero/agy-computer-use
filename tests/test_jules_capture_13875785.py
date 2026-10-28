import sys
from pathlib import Path
import struct

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from agy_computer_use.capture import encode_rgb_to_png

def test_encode_rgb_to_png_normal():
    # 2x2 image, so 4 pixels, 12 bytes
    rgb = b"\xff\x00\x00" * 4 
    res = encode_rgb_to_png(rgb, 2, 2)
    assert res.startswith(b"\x89PNG\r\n\x1a\n")
    assert b"IHDR" in res
    assert b"IDAT" in res
    assert b"IEND" in res

def test_encode_rgb_to_png_invalid_dimensions():
    with pytest.raises(ValueError, match="width and height must be positive integers"):
        encode_rgb_to_png(b"", 0, 10)
    with pytest.raises(ValueError, match="width and height must be positive integers"):
        encode_rgb_to_png(b"", 10, 0)
    with pytest.raises(ValueError, match="width and height must be positive integers"):
        encode_rgb_to_png(b"", -1, -1)

def test_encode_rgb_to_png_invalid_length():
    with pytest.raises(ValueError, match="Expected 12 RGB bytes, got 10"):
        encode_rgb_to_png(b"\x00" * 10, 2, 2)

class FakeBytes:
    def __init__(self, length):
        self._length = length

    def __len__(self):
        return self._length
    
    def __getitem__(self, key):
        return b"\x00" * (key.stop - key.start)

def test_encode_rgb_to_png_overflow_memory():
    # We want to trigger memory error on bytearray((row_stride + 1) * height)
    # row_stride = width * 3
    # bytearray((width * 3 + 1) * height)
    
    width = 2**30
    height = 2**30
    expected_len = width * height * 3
    fake_rgb = FakeBytes(expected_len)
    
    with pytest.raises(MemoryError):
        encode_rgb_to_png(fake_rgb, width, height)
