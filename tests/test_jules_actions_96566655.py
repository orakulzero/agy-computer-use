import pytest
from agy_computer_use.actions import _to_win32_abs, _resolve_vk

def test_to_win32_abs_clamping():
    assert _to_win32_abs(-50) == 0
    assert _to_win32_abs(1500) == 65535
    assert _to_win32_abs(0) == 0
    assert _to_win32_abs(1000) == 65535
    assert _to_win32_abs(500) == 32768

def test_resolve_vk_fallback():
    assert _resolve_vk("unknown") == 0x41
    assert _resolve_vk("UNKNOWN") == 0x41
    assert _resolve_vk("a") == ord("A")
    assert _resolve_vk("ctrl") == 0x11
