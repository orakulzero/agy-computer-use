"""Non-Intrusive Background Computer Use & Hidden Win32 Desktop (Ghost Desktop) Engine.

Implements:
- REQ-CUA-BG-01: Per-window DWM/GDI background frame capture via PrintWindow(PW_RENDERFULLCONTENT)
  without bringing windows to the foreground or requiring screen BitBlt visibility.
- REQ-CUA-BG-02: Focusless background input synthesis via child-window coordinate routing
  and PostMessageW / SendMessageTimeoutW (click, double_click, right_click, drag, scroll,
  type_text, wm_settext) plus off-screen window staging (SW_SHOWNOACTIVATE + WS_EX_TOOLWINDOW).
- REQ-CUA-BG-03: Isolated Win32 kernel desktop session (GhostDesktopSession via CreateDesktopW
  and CreateProcessW with STARTUPINFOW.lpDesktop) so GUI applications execute 100% invisibly
  in the background without appearing on the user's interactive desktop or stealing cursor focus.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import sys
import threading
import time
from typing import Any, TypeVar
from collections.abc import Callable

from agy_computer_use.actions import ComputerUseSafetyAbort
from agy_computer_use.capture import (
    _BITMAPINFO,
    _BITMAPINFOHEADER,
    _RECT,
    DIB_RGB_COLORS,
    _generate_synthetic_rgb,
    encode_rgb_to_bmp,
    encode_rgb_to_png,
)
from agy_computer_use.safety_oracle import compute_frame_dhash64
from agy_computer_use.som import denormalize_from_grid_1000
import contextlib

PW_CLIENTONLY = 0x00000001
PW_RENDERFULLCONTENT = 0x00000002

SW_SHOWNOACTIVATE = 4
SW_RESTORE = 9
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_SHOWWINDOW = 0x0040

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_EX_NOACTIVATE = 0x08000000

WM_SETTEXT = 0x000C
WM_CLOSE = 0x0010
WM_MOUSEACTIVATE = 0x0021
WM_SETCURSOR = 0x0020
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102
WM_COMMAND = 0x0111
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MOUSEWHEEL = 0x020A
BM_CLICK = 0x00F5

MK_LBUTTON = 0x0001
MK_RBUTTON = 0x0002
HTCLIENT = 1
SMTO_ABORTIFHUNG = 0x0002

DESKTOP_ALL_ACCESS = 0x01FF
GENERIC_ALL = 0x10000000
CREATE_NO_WINDOW = 0x08000000
STARTF_USESHOWWINDOW = 0x00000001

_T = TypeVar("_T")


class _POINT(ctypes.Structure):
    _fields_ = [
        ("x", wintypes.LONG),
        ("y", wintypes.LONG),
    ]


class _STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


def _run_on_desktop(desktop_name: str, fn: Callable[[], _T], create_if_missing: bool = False) -> _T:
    """REQ-CUA-BG-03: Execute fn on a fresh worker thread attached to the target Win32 desktop."""
    if sys.platform != "win32":
        return fn()

    box: dict[str, Any] = {}

    def _worker() -> None:
        h_desk = 0
        h_orig = 0
        user32 = None
        kernel32 = None
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            if hasattr(user32, "OpenDesktopW") and hasattr(user32, "SetThreadDesktop"):
                h_desk = user32.OpenDesktopW(desktop_name, 0, False, DESKTOP_ALL_ACCESS | GENERIC_ALL)
                if not h_desk and create_if_missing and hasattr(user32, "CreateDesktopW"):
                    h_desk = user32.CreateDesktopW(
                        desktop_name,
                        None,
                        None,
                        0,
                        DESKTOP_ALL_ACCESS | GENERIC_ALL,
                        None,
                    )
                if h_desk:
                    if hasattr(user32, "GetThreadDesktop") and hasattr(kernel32, "GetCurrentThreadId"):
                        h_orig = user32.GetThreadDesktop(kernel32.GetCurrentThreadId())
                    user32.SetThreadDesktop(h_desk)
        except Exception:
            h_desk = 0

        try:
            box["result"] = fn()
        except BaseException as exc:
            box["error"] = exc
        finally:
            if h_orig and user32 is not None:
                with contextlib.suppress(Exception):
                    user32.SetThreadDesktop(h_orig)
            if h_desk and user32 is not None and hasattr(user32, "CloseDesktop"):
                with contextlib.suppress(Exception):
                    user32.CloseDesktop(h_desk)

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    thread.join()

    if "error" in box:
        raise box["error"]
    return box["result"]


def capture_window_background(
    hwnd: int,
    *,
    desktop_name: str = "Default",
    fallback_seed: int = 101,
    fallback_width: int = 640,
    fallback_height: int = 480,
) -> dict[str, Any]:
    """REQ-CUA-BG-01: Capture a window's surface in the background via PrintWindow(PW_RENDERFULLCONTENT).

    Works without bringing the window to the foreground, even if the window is occluded
    by other windows, positioned off-screen, or running on an isolated hidden desktop.
    """
    target_hwnd = int(hwnd)

    def _do_print_window() -> tuple[bytes, int, int, tuple[int, int, int, int]] | None:
        if sys.platform != "win32" or target_hwnd <= 0:
            return None
        try:
            user32 = ctypes.windll.user32
            gdi32 = ctypes.windll.gdi32

            user32.GetWindowDC.argtypes = [wintypes.HWND]
            user32.GetWindowDC.restype = wintypes.HDC
            user32.GetDC.argtypes = [wintypes.HWND]
            user32.GetDC.restype = wintypes.HDC
            user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
            user32.ReleaseDC.restype = ctypes.c_int
            if hasattr(user32, "PrintWindow"):
                user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
                user32.PrintWindow.restype = wintypes.BOOL
            if hasattr(user32, "SendMessageW"):
                user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
                user32.SendMessageW.restype = ctypes.c_ssize_t

            gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
            gdi32.CreateCompatibleDC.restype = wintypes.HDC
            gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
            gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
            gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
            gdi32.SelectObject.restype = wintypes.HGDIOBJ
            gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
            gdi32.DeleteObject.restype = wintypes.BOOL
            gdi32.DeleteDC.argtypes = [wintypes.HDC]
            gdi32.DeleteDC.restype = wintypes.BOOL
            gdi32.GetDIBits.argtypes = [
                wintypes.HDC,
                wintypes.HBITMAP,
                wintypes.UINT,
                wintypes.UINT,
                wintypes.LPVOID,
                ctypes.POINTER(_BITMAPINFO),
                wintypes.UINT,
            ]
            gdi32.GetDIBits.restype = ctypes.c_int

            if not user32.IsWindow(target_hwnd):
                return None

            rect = _RECT()
            if not user32.GetWindowRect(target_hwnd, ctypes.byref(rect)):
                return None

            width = int(rect.right - rect.left)
            height = int(rect.bottom - rect.top)
            if width <= 0 or height <= 0:
                return None

            hdc_win = user32.GetWindowDC(target_hwnd)
            if not hdc_win:
                hdc_win = user32.GetDC(0)
            if not hdc_win:
                return None

            hdc_mem = gdi32.CreateCompatibleDC(hdc_win)
            if not hdc_mem:
                user32.ReleaseDC(target_hwnd, hdc_win)
                return None

            hbmp = gdi32.CreateCompatibleBitmap(hdc_win, width, height)
            if not hbmp:
                gdi32.DeleteDC(hdc_mem)
                user32.ReleaseDC(target_hwnd, hdc_win)
                return None

            old_obj = gdi32.SelectObject(hdc_mem, hbmp)

            bmi = _BITMAPINFO()
            bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = width
            bmi.bmiHeader.biHeight = -height  # top-down
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 32
            bmi.bmiHeader.biCompression = 0

            bgra_len = width * height * 4
            bgra_buf = (ctypes.c_ubyte * bgra_len)()

            def _extract_rgb_if_nonempty() -> bytes | None:
                lines = gdi32.GetDIBits(
                    hdc_mem,
                    hbmp,
                    0,
                    height,
                    bgra_buf,
                    ctypes.byref(bmi),
                    DIB_RGB_COLORS,
                )
                if lines != height:
                    return None
                raw_bytes = bytes(bgra_buf)
                rgb_arr = bytearray(width * height * 3)
                rgb_arr[0::3] = raw_bytes[2::4]
                rgb_arr[1::3] = raw_bytes[1::4]
                rgb_arr[2::3] = raw_bytes[0::4]
                if not any(rgb_arr):
                    return None
                return bytes(rgb_arr)

            rgb_result: bytes | None = None
            if hasattr(user32, "PrintWindow"):
                if user32.PrintWindow(target_hwnd, hdc_mem, PW_RENDERFULLCONTENT):
                    rgb_result = _extract_rgb_if_nonempty()
                if rgb_result is None and user32.PrintWindow(target_hwnd, hdc_mem, 0):
                    rgb_result = _extract_rgb_if_nonempty()

            if rgb_result is None and hasattr(user32, "SendMessageW"):
                WM_PRINT = 0x0317
                PRF_CLIENT = 0x00000004
                PRF_NONCLIENT = 0x00000002
                PRF_CHILDREN = 0x00000010
                PRF_ERASEBKGND = 0x00000008
                user32.SendMessageW(
                    target_hwnd,
                    WM_PRINT,
                    hdc_mem,
                    PRF_NONCLIENT | PRF_CLIENT | PRF_CHILDREN | PRF_ERASEBKGND,
                )
                rgb_result = _extract_rgb_if_nonempty()

            gdi32.SelectObject(hdc_mem, old_obj)
            gdi32.DeleteObject(hbmp)
            gdi32.DeleteDC(hdc_mem)
            user32.ReleaseDC(target_hwnd, hdc_win)

            if rgb_result is None:
                return None

            return rgb_result, width, height, (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))
        except Exception:
            return None

    captured = _run_on_desktop(desktop_name, _do_print_window)
    if captured is not None:
        rgb_bytes, width, height, win_rect = captured
        backend = "win32_printwindow"
    else:
        width = max(16, int(fallback_width))
        height = max(16, int(fallback_height))
        rgb_bytes = _generate_synthetic_rgb(width, height, fallback_seed)
        win_rect = (0, 0, width, height)
        backend = "synthetic_fallback"

    bmp_bytes = encode_rgb_to_bmp(rgb_bytes, width, height)
    png_bytes = encode_rgb_to_png(rgb_bytes, width, height)
    dhash64 = compute_frame_dhash64(rgb_bytes, width, height)
    sha256_hex = hashlib.sha256(png_bytes).hexdigest()

    return {
        "hwnd": target_hwnd,
        "desktop_name": desktop_name,
        "backend": backend,
        "width": width,
        "height": height,
        "window_rect": win_rect,
        "rgb_bytes": rgb_bytes,
        "bmp_bytes": bmp_bytes,
        "png_bytes": png_bytes,
        "dhash64": dhash64,
        "sha256": sha256_hex,
        "timestamp": time.time(),
    }


def stage_window_offscreen(
    hwnd: int,
    *,
    offscreen_x: int = -3200,
    offscreen_y: int = -3200,
    width: int | None = None,
    height: int | None = None,
    hide_from_taskbar: bool = True,
    desktop_name: str = "Default",
) -> dict[str, Any]:
    """REQ-CUA-BG-02: Stage a window off-screen with SW_SHOWNOACTIVATE so it never interrupts the user
    while keeping its DWM composition surface active for PrintWindow(PW_RENDERFULLCONTENT).
    """
    target_hwnd = int(hwnd)

    def _do_stage() -> dict[str, Any]:
        if sys.platform != "win32" or target_hwnd <= 0:
            return {
                "hwnd": target_hwnd,
                "staged": False,
                "original_rect": (0, 0, 640, 480),
                "original_exstyle": 0,
            }
        user32 = ctypes.windll.user32
        if not user32.IsWindow(target_hwnd):
            return {
                "hwnd": target_hwnd,
                "staged": False,
                "original_rect": (0, 0, 0, 0),
                "original_exstyle": 0,
            }

        rect = _RECT()
        user32.GetWindowRect(target_hwnd, ctypes.byref(rect))
        orig_rect = (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))
        cur_w = int(width) if width is not None else max(200, int(rect.right - rect.left))
        cur_h = int(height) if height is not None else max(200, int(rect.bottom - rect.top))

        if user32.IsIconic(target_hwnd):
            user32.ShowWindow(target_hwnd, SW_SHOWNOACTIVATE)

        orig_exstyle = int(user32.GetWindowLongW(target_hwnd, GWL_EXSTYLE))
        if hide_from_taskbar:
            new_exstyle = (orig_exstyle | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE) & ~WS_EX_APPWINDOW
            user32.SetWindowLongW(target_hwnd, GWL_EXSTYLE, new_exstyle)

        flags = SWP_NOACTIVATE | SWP_NOZORDER | SWP_SHOWWINDOW
        ok = bool(
            user32.SetWindowPos(
                target_hwnd,
                0,
                int(offscreen_x),
                int(offscreen_y),
                cur_w,
                cur_h,
                flags,
            )
        )
        return {
            "hwnd": target_hwnd,
            "staged": ok,
            "offscreen_rect": (int(offscreen_x), int(offscreen_y), int(offscreen_x) + cur_w, int(offscreen_y) + cur_h),
            "original_rect": orig_rect,
            "original_exstyle": orig_exstyle,
        }

    return _run_on_desktop(desktop_name, _do_stage)


def restore_window_onscreen(
    hwnd: int,
    saved_state: dict[str, Any],
    *,
    desktop_name: str = "Default",
) -> bool:
    """REQ-CUA-BG-02: Restore a previously staged off-screen window to its original coordinates and style."""
    target_hwnd = int(hwnd)

    def _do_restore() -> bool:
        if sys.platform != "win32" or target_hwnd <= 0:
            return False
        user32 = ctypes.windll.user32
        if not user32.IsWindow(target_hwnd):
            return False

        orig_exstyle = saved_state.get("original_exstyle")
        if orig_exstyle is not None:
            user32.SetWindowLongW(target_hwnd, GWL_EXSTYLE, int(orig_exstyle))

        orig_rect = saved_state.get("original_rect", (100, 100, 900, 700))
        left, top, right, bottom = (int(v) for v in orig_rect)
        w = max(200, right - left)
        h = max(200, bottom - top)
        return bool(
            user32.SetWindowPos(
                target_hwnd,
                0,
                left,
                top,
                w,
                h,
                SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED | SWP_SHOWWINDOW,
            )
        )

    return _run_on_desktop(desktop_name, _do_restore)


def _pack_lparam_point(x: int, y: int) -> int:
    return ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)


def _resolve_deepest_child_at_window_offset(
    user32: Any,
    root_hwnd: int,
    win_offset_x: int,
    win_offset_y: int,
) -> tuple[int, int, int, str]:
    """Resolve the deepest visible child HWND and its client-relative (x, y) for a root window offset."""
    root_rect = _RECT()
    user32.GetWindowRect(root_hwnd, ctypes.byref(root_rect))
    screen_x = int(root_rect.left) + int(win_offset_x)
    screen_y = int(root_rect.top) + int(win_offset_y)

    best_hwnd = root_hwnd
    best_area: int | None = None

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _enum_child(child_hwnd: int, _lparam: int) -> bool:
        nonlocal best_hwnd, best_area
        try:
            if not user32.IsWindowVisible(child_hwnd):
                return True
            crect = _RECT()
            if not user32.GetWindowRect(child_hwnd, ctypes.byref(crect)):
                return True
            if crect.left <= screen_x < crect.right and crect.top <= screen_y < crect.bottom:
                area = max(1, int(crect.right - crect.left)) * max(1, int(crect.bottom - crect.top))
                if best_area is None or area <= best_area:
                    best_area = area
                    best_hwnd = int(child_hwnd)
        except Exception:
            pass
        return True

    cb = WNDENUMPROC(_enum_child)
    user32.EnumChildWindows(root_hwnd, cb, 0)

    pt = _POINT(screen_x, screen_y)
    user32.ScreenToClient(best_hwnd, ctypes.byref(pt))

    cls_buf = ctypes.create_unicode_buffer(128)
    user32.GetClassNameW(best_hwnd, cls_buf, 128)
    return best_hwnd, int(pt.x), int(pt.y), cls_buf.value


def dispatch_background_window_action(
    hwnd: int,
    action_type: str,
    *,
    norm_x: int | None = None,
    norm_y: int | None = None,
    end_norm_x: int | None = None,
    end_norm_y: int | None = None,
    text: str = "",
    wheel_delta: int = -120,
    drag_steps: int = 16,
    desktop_name: str = "Default",
    dry_run: bool = False,
) -> dict[str, Any]:
    """REQ-CUA-BG-02: Dispatch GUI actions to a window in the background via PostMessageW / SendMessageTimeoutW.

    Never calls SendInput, SetCursorPos, or SetForegroundWindow — the user's physical mouse
    and keyboard focus remain 100% untouched.
    """
    if norm_x == 0 and norm_y == 0:
        raise ComputerUseSafetyAbort(
            "Top-left (0, 0) fail-safe abort guard triggered in dispatch_background_window_action."
        )
    if end_norm_x == 0 and end_norm_y == 0 and action_type == "drag":
        raise ComputerUseSafetyAbort(
            "Top-left (0, 0) fail-safe abort guard triggered on drag endpoint."
        )

    supported = {
        "click",
        "double_click",
        "right_click",
        "move",
        "drag",
        "scroll",
        "type_text",
        "wm_settext",
    }
    if action_type not in supported:
        raise ValueError(f"Unsupported background action_type '{action_type}'. Expected one of {sorted(supported)}")

    target_root = int(hwnd)

    def _do_dispatch() -> dict[str, Any]:
        if sys.platform != "win32" or target_root <= 0 or dry_run:
            w, h = 800, 600
            wx, wy = denormalize_from_grid_1000(norm_x or 500, norm_y or 500, w, h)
            return {
                "hwnd": target_root,
                "target_child_hwnd": target_root,
                "target_class": "SyntheticWindow",
                "action_type": action_type,
                "window_offset": (wx, wy),
                "client_point": (wx, wy),
                "dispatched": True,
                "dry_run": dry_run,
                "method": "post_message_background",
            }

        user32 = ctypes.windll.user32
        if not user32.IsWindow(target_root):
            return {
                "hwnd": target_root,
                "target_child_hwnd": 0,
                "action_type": action_type,
                "dispatched": False,
                "error": "invalid_hwnd",
            }

        rrect = _RECT()
        user32.GetWindowRect(target_root, ctypes.byref(rrect))
        win_w = max(1, int(rrect.right - rrect.left))
        win_h = max(1, int(rrect.bottom - rrect.top))

        nx = 500 if norm_x is None else int(norm_x)
        ny = 500 if norm_y is None else int(norm_y)
        win_off_x, win_off_y = denormalize_from_grid_1000(nx, ny, win_w, win_h)

        child_hwnd, client_x, client_y, child_class = _resolve_deepest_child_at_window_offset(
            user32, target_root, win_off_x, win_off_y
        )
        lparam = _pack_lparam_point(client_x, client_y)

        if action_type == "move":
            user32.PostMessageW(child_hwnd, WM_MOUSEMOVE, 0, lparam)

        elif action_type == "click":
            user32.PostMessageW(child_hwnd, WM_MOUSEMOVE, 0, lparam)
            user32.PostMessageW(child_hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam)
            user32.PostMessageW(child_hwnd, WM_LBUTTONUP, 0, lparam)
            if child_class.lower() == "button":
                user32.PostMessageW(child_hwnd, BM_CLICK, 0, 0)

        elif action_type == "double_click":
            user32.PostMessageW(child_hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam)
            user32.PostMessageW(child_hwnd, WM_LBUTTONUP, 0, lparam)
            user32.PostMessageW(child_hwnd, WM_LBUTTONDBLCLK, MK_LBUTTON, lparam)
            user32.PostMessageW(child_hwnd, WM_LBUTTONUP, 0, lparam)

        elif action_type == "right_click":
            user32.PostMessageW(child_hwnd, WM_MOUSEMOVE, 0, lparam)
            user32.PostMessageW(child_hwnd, WM_RBUTTONDOWN, MK_RBUTTON, lparam)
            user32.PostMessageW(child_hwnd, WM_RBUTTONUP, 0, lparam)

        elif action_type == "drag":
            enx = nx if end_norm_x is None else int(end_norm_x)
            eny = ny if end_norm_y is None else int(end_norm_y)
            end_off_x, end_off_y = denormalize_from_grid_1000(enx, eny, win_w, win_h)

            end_screen_x = int(rrect.left) + end_off_x
            end_screen_y = int(rrect.top) + end_off_y
            end_pt = _POINT(end_screen_x, end_screen_y)
            user32.ScreenToClient(child_hwnd, ctypes.byref(end_pt))
            end_cx, end_cy = int(end_pt.x), int(end_pt.y)

            steps = max(2, int(drag_steps))
            user32.PostMessageW(child_hwnd, WM_MOUSEMOVE, 0, lparam)
            user32.PostMessageW(child_hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam)
            for i in range(1, steps + 1):
                ix = int(round(client_x + (end_cx - client_x) * (i / steps)))
                iy = int(round(client_y + (end_cy - client_y) * (i / steps)))
                user32.PostMessageW(child_hwnd, WM_MOUSEMOVE, MK_LBUTTON, _pack_lparam_point(ix, iy))
            user32.PostMessageW(child_hwnd, WM_LBUTTONUP, 0, _pack_lparam_point(end_cx, end_cy))

        elif action_type == "scroll":
            wparam = ((int(wheel_delta) & 0xFFFF) << 16)
            screen_pt_lparam = _pack_lparam_point(int(rrect.left) + win_off_x, int(rrect.top) + win_off_y)
            user32.PostMessageW(child_hwnd, WM_MOUSEWHEEL, wparam, screen_pt_lparam)

        elif action_type == "type_text":
            for ch in text:
                user32.PostMessageW(child_hwnd, WM_CHAR, ord(ch), 1)

        elif action_type == "wm_settext":
            buf = ctypes.create_unicode_buffer(text)
            res = wintypes.DWORD(0)
            user32.SendMessageTimeoutW(
                child_hwnd,
                WM_SETTEXT,
                0,
                ctypes.cast(buf, wintypes.LPARAM),
                SMTO_ABORTIFHUNG,
                1000,
                ctypes.byref(res),
            )

        return {
            "hwnd": target_root,
            "target_child_hwnd": child_hwnd,
            "target_class": child_class,
            "action_type": action_type,
            "window_offset": (win_off_x, win_off_y),
            "client_point": (client_x, client_y),
            "dispatched": True,
            "dry_run": False,
            "method": "post_message_background",
        }

    return _run_on_desktop(desktop_name, _do_dispatch)


class GhostDesktopSession:
    """REQ-CUA-BG-03: Isolated Win32 Kernel Desktop Session (CreateDesktopW without SwitchDesktop).

    Allows launching and automating GUI applications on a hidden desktop inside WinSta0
    so that windows never appear on the user's screen, taskbar, or Alt+Tab switcher,
    and never touch the user's physical mouse cursor or keyboard focus.
    """

    def __init__(self, desktop_name: str = "AGY_GhostDesktop") -> None:
        if not desktop_name or "\\" in desktop_name:
            raise ValueError("desktop_name must be a non-empty desktop identifier without backslashes")
        self.desktop_name = desktop_name
        self._hdesk: int = 0
        self._spawned_pids: list[int] = []
        self._process_handles: list[int] = []
        self._ensure_desktop_created()

    def _ensure_desktop_created(self) -> None:
        if sys.platform != "win32":
            return
        user32 = ctypes.windll.user32
        if hasattr(user32, "CreateDesktopW"):
            h_desk = user32.CreateDesktopW(
                self.desktop_name,
                None,
                None,
                0,
                DESKTOP_ALL_ACCESS | GENERIC_ALL,
                None,
            )
            if h_desk:
                self._hdesk = int(h_desk)

    def launch_process(
        self,
        command_line: str,
        *,
        wait_for_window_sec: float = 5.0,
        show_window: int = SW_SHOWNOACTIVATE,
    ) -> dict[str, Any]:
        """REQ-CUA-BG-03: Spawn a GUI process directly on WinSta0\\<desktop_name>."""
        if sys.platform != "win32":
            return {
                "pid": 99999,
                "hwnd": 10001,
                "desktop": f"WinSta0\\{self.desktop_name}",
                "command_line": command_line,
            }

        kernel32 = ctypes.windll.kernel32
        si = _STARTUPINFOW()
        si.cb = ctypes.sizeof(_STARTUPINFOW)
        si.lpDesktop = f"WinSta0\\{self.desktop_name}"
        si.dwFlags = STARTF_USESHOWWINDOW
        si.wShowWindow = int(show_window)

        pi = _PROCESS_INFORMATION()
        cmd_buf = ctypes.create_unicode_buffer(command_line)

        ok = kernel32.CreateProcessW(
            None,
            cmd_buf,
            None,
            None,
            False,
            CREATE_NO_WINDOW,
            None,
            None,
            ctypes.byref(si),
            ctypes.byref(pi),
        )
        if not ok:
            err_code = kernel32.GetLastError()
            raise RuntimeError(f"CreateProcessW on WinSta0\\{self.desktop_name} failed with error {err_code}")

        pid = int(pi.dwProcessId)
        self._spawned_pids.append(pid)
        if pi.hThread:
            kernel32.CloseHandle(pi.hThread)
        if pi.hProcess:
            self._process_handles.append(int(pi.hProcess))

        deadline = time.time() + max(0.2, float(wait_for_window_sec))
        found_hwnd = 0
        while time.time() < deadline:
            wins = self.enumerate_windows()
            for w in wins:
                if w.get("pid") == pid or (w.get("width", 0) >= 80 and w.get("height", 0) >= 60):
                    if w.get("pid") == pid:
                        found_hwnd = int(w["hwnd"])
                        break
                    if not found_hwnd:
                        found_hwnd = int(w["hwnd"])
            if found_hwnd:
                break
            time.sleep(0.15)

        return {
            "pid": pid,
            "hwnd": found_hwnd,
            "desktop": f"WinSta0\\{self.desktop_name}",
            "command_line": command_line,
        }

    def enumerate_windows(self) -> list[dict[str, Any]]:
        """REQ-CUA-BG-03: Enumerate top-level windows on this isolated desktop."""
        def _do_enum() -> list[dict[str, Any]]:
            if sys.platform != "win32":
                return []
            user32 = ctypes.windll.user32
            results: list[dict[str, Any]] = []

            WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

            def _cb(hwnd: int, _lparam: int) -> bool:
                try:
                    if not user32.IsWindowVisible(hwnd):
                        return True
                    rect = _RECT()
                    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                        return True
                    w = int(rect.right - rect.left)
                    h = int(rect.bottom - rect.top)
                    if w <= 0 or h <= 0:
                        return True

                    length = user32.GetWindowTextLengthW(hwnd)
                    title_buf = ctypes.create_unicode_buffer(length + 2)
                    user32.GetWindowTextW(hwnd, title_buf, length + 1)

                    cls_buf = ctypes.create_unicode_buffer(128)
                    user32.GetClassNameW(hwnd, cls_buf, 128)

                    pid_val = wintypes.DWORD(0)
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_val))

                    results.append(
                        {
                            "hwnd": int(hwnd),
                            "pid": int(pid_val.value),
                            "title": title_buf.value,
                            "class_name": cls_buf.value,
                            "rect": (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)),
                            "width": w,
                            "height": h,
                            "desktop": self.desktop_name,
                        }
                    )
                except Exception:
                    pass
                return True

            proc = WNDENUMPROC(_cb)
            user32.EnumWindows(proc, 0)
            return results

        return _run_on_desktop(self.desktop_name, _do_enum, create_if_missing=True)

    def capture_window(self, hwnd: int, *, fallback_seed: int = 202) -> dict[str, Any]:
        """REQ-CUA-BG-01 / REQ-CUA-BG-03: Capture a window living on this isolated desktop."""
        return capture_window_background(
            hwnd,
            desktop_name=self.desktop_name,
            fallback_seed=fallback_seed,
        )

    def dispatch_action(
        self,
        hwnd: int,
        action_type: str,
        *,
        norm_x: int | None = None,
        norm_y: int | None = None,
        end_norm_x: int | None = None,
        end_norm_y: int | None = None,
        text: str = "",
        wheel_delta: int = -120,
        drag_steps: int = 16,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """REQ-CUA-BG-02 / REQ-CUA-BG-03: Dispatch an action to a window on this isolated desktop."""
        return dispatch_background_window_action(
            hwnd,
            action_type,
            norm_x=norm_x,
            norm_y=norm_y,
            end_norm_x=end_norm_x,
            end_norm_y=end_norm_y,
            text=text,
            wheel_delta=wheel_delta,
            drag_steps=drag_steps,
            desktop_name=self.desktop_name,
            dry_run=dry_run,
        )

    def close(self, terminate_spawned: bool = True) -> None:
        """REQ-CUA-BG-03: Terminate spawned processes on the ghost desktop and release the desktop handle."""
        if sys.platform != "win32":
            return
        kernel32 = ctypes.windll.kernel32
        if terminate_spawned:
            for h_proc in self._process_handles:
                try:
                    kernel32.TerminateProcess(h_proc, 0)
                    kernel32.CloseHandle(h_proc)
                except Exception:
                    pass
            self._process_handles.clear()
            self._spawned_pids.clear()
        if self._hdesk:
            with contextlib.suppress(Exception):
                ctypes.windll.user32.CloseDesktop(self._hdesk)
            self._hdesk = 0
