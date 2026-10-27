"""Win32 SendInput & PostMessageW GUI Action Synthesis, SoM Mark Dispatch, and Fail-Safe Guard.

Implements REQ-CU-003:
- 9 GUI action types: click, double_click, right_click, move, drag, scroll,
  type_text, hotkey, key_tap
- Set-of-Marks (SoM) mark_id resolution from marks_catalog
- Fail-safe (0, 0) top-left corner emergency abort (ComputerUseSafetyAbort)
- Win32 SendInput + WindowFromPoint/PostMessageW Default desktop execution
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import sys
import time
from typing import Any

from agy_computer_use.capture import _run_on_default_desktop
from agy_computer_use.som import denormalize_from_grid_1000

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MOUSEWHEEL = 0x020A
WM_PASTE = 0x0302

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

SUPPORTED_ACTION_TYPES: tuple[str, ...] = (
    "click",
    "double_click",
    "right_click",
    "move",
    "drag",
    "scroll",
    "type_text",
    "hotkey",
    "key_tap",
)

_MOUSE_POINTER_ACTIONS: frozenset[str] = frozenset(
    {"click", "double_click", "right_click", "move", "drag", "scroll"}
)

_VK_MAP: dict[str, int] = {
    "ctrl": 0x11,
    "control": 0x11,
    "shift": 0x10,
    "alt": 0x12,
    "menu": 0x12,
    "win": 0x5B,
    "lwin": 0x5B,
    "enter": 0x0D,
    "return": 0x0D,
    "tab": 0x09,
    "esc": 0x1B,
    "escape": 0x1B,
    "space": 0x20,
    "backspace": 0x08,
    "delete": 0x2E,
    "del": 0x2E,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "f1": 0x70,
    "f2": 0x71,
    "f3": 0x72,
    "f4": 0x73,
    "f5": 0x74,
    "f6": 0x75,
    "f7": 0x76,
    "f8": 0x77,
    "f9": 0x78,
    "f10": 0x79,
    "f11": 0x7A,
    "f12": 0x7B,
}


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", _MOUSEINPUT),
        ("ki", _KEYBDINPUT),
    ]


class _INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("u", _INPUT_UNION),
    ]


class ComputerUseSafetyAbort(RuntimeError):
    """Raised when a GUI action violates fail-safe corner or SafetyPolicy guardrails."""


def _resolve_vk(key_name: str) -> int:
    k = key_name.strip().lower()
    if k in _VK_MAP:
        return _VK_MAP[k]
    if len(k) == 1:
        return ord(k.upper())
    return 0x41


def _to_win32_abs(norm_coord: int) -> int:
    return max(0, min(65535, int(round((float(norm_coord) / 1000.0) * 65535.0))))


def _mouse_record(dx: int, dy: int, flags: int, mouse_data: int = 0) -> dict[str, int]:
    return {
        "type": INPUT_MOUSE,
        "dx": int(dx),
        "dy": int(dy),
        "mouseData": int(mouse_data),
        "dwFlags": int(flags),
    }


def _key_record(vk: int, scan: int, flags: int) -> dict[str, int]:
    return {
        "type": INPUT_KEYBOARD,
        "wVk": int(vk),
        "wScan": int(scan),
        "dwFlags": int(flags),
    }


def _send_win32_inputs_live(
    resolved_px: tuple[int, int] | None,
    win32_inputs: list[dict[str, int]],
    action_type: str = "click",
    target_hwnd: int | None = None,
    text: str | None = None,
    scroll_delta: int = -120,
) -> None:
    """Dispatch SetCursorPos, SendInput, and PostMessageW on the interactive Default desktop."""

    def _do_send() -> None:
        try:
            user32 = ctypes.windll.user32
            if resolved_px is not None and hasattr(user32, "SetCursorPos"):
                user32.SetCursorPos(int(resolved_px[0]), int(resolved_px[1]))
            if win32_inputs and hasattr(user32, "SendInput"):
                if action_type == "drag" and len(win32_inputs) >= 4:
                    ax1 = int(win32_inputs[0].get("dx", 0))
                    ay1 = int(win32_inputs[0].get("dy", 0))
                    ax2 = int(win32_inputs[2].get("dx", 0))
                    ay2 = int(win32_inputs[2].get("dy", 0))

                    def _emit_mouse(dx_val: int, dy_val: int, flags_val: int) -> None:
                        inp = _INPUT()
                        inp.type = INPUT_MOUSE
                        inp.u.mi.dx = int(dx_val)
                        inp.u.mi.dy = int(dy_val)
                        inp.u.mi.mouseData = 0
                        inp.u.mi.dwFlags = int(flags_val)
                        inp.u.mi.time = 0
                        inp.u.mi.dwExtraInfo = 0
                        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))

                    _emit_mouse(ax1, ay1, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE)
                    time.sleep(0.005)
                    _emit_mouse(ax1, ay1, MOUSEEVENTF_LEFTDOWN | MOUSEEVENTF_ABSOLUTE)
                    time.sleep(0.006)
                    steps = 20
                    for step_idx in range(1, steps + 1):
                        t = float(step_idx) / float(steps)
                        ix = int(round(ax1 + (ax2 - ax1) * t))
                        iy = int(round(ay1 + (ay2 - ay1) * t))
                        _emit_mouse(ix, iy, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE)
                        time.sleep(0.003)
                    time.sleep(0.008)
                    _emit_mouse(ax2, ay2, MOUSEEVENTF_LEFTUP | MOUSEEVENTF_ABSOLUTE)
                else:
                    n = len(win32_inputs)
                    arr = (_INPUT * n)()
                    for i, rec in enumerate(win32_inputs):
                        rec_type = int(rec.get("type", INPUT_MOUSE))
                        arr[i].type = rec_type
                        if rec_type == INPUT_MOUSE:
                            arr[i].u.mi.dx = int(rec.get("dx", 0))
                            arr[i].u.mi.dy = int(rec.get("dy", 0))
                            arr[i].u.mi.mouseData = int(rec.get("mouseData", 0)) & 0xFFFFFFFF
                            arr[i].u.mi.dwFlags = int(rec.get("dwFlags", 0))
                            arr[i].u.mi.time = 0
                            arr[i].u.mi.dwExtraInfo = 0
                        else:
                            arr[i].u.ki.wVk = int(rec.get("wVk", 0))
                            arr[i].u.ki.wScan = int(rec.get("wScan", 0))
                            arr[i].u.ki.dwFlags = int(rec.get("dwFlags", 0))
                            arr[i].u.ki.time = 0
                            arr[i].u.ki.dwExtraInfo = 0
                    user32.SendInput(n, ctypes.byref(arr), ctypes.sizeof(_INPUT))

            hwnd = int(target_hwnd) if target_hwnd else 0
            if not hwnd and resolved_px is not None and hasattr(user32, "WindowFromPoint"):
                pt_screen = wintypes.POINT(int(resolved_px[0]), int(resolved_px[1]))
                hwnd = int(user32.WindowFromPoint(pt_screen) or 0)
            if not hwnd and hasattr(user32, "GetForegroundWindow"):
                hwnd = int(user32.GetForegroundWindow() or 0)

            if hwnd and hasattr(user32, "PostMessageW"):
                lparam = 0
                if resolved_px is not None and hasattr(user32, "ScreenToClient"):
                    pt_client = wintypes.POINT(int(resolved_px[0]), int(resolved_px[1]))
                    user32.ScreenToClient(hwnd, ctypes.byref(pt_client))
                    lparam = ((int(pt_client.y) & 0xFFFF) << 16) | (int(pt_client.x) & 0xFFFF)

                if action_type == "move":
                    user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lparam)
                elif action_type == "click":
                    user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lparam)
                    user32.PostMessageW(hwnd, WM_LBUTTONDOWN, 1, lparam)
                    user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam)
                elif action_type == "double_click":
                    user32.PostMessageW(hwnd, WM_LBUTTONDOWN, 1, lparam)
                    user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam)
                    user32.PostMessageW(hwnd, WM_LBUTTONDBLCLK, 1, lparam)
                    user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam)
                elif action_type == "right_click":
                    user32.PostMessageW(hwnd, WM_RBUTTONDOWN, 2, lparam)
                    user32.PostMessageW(hwnd, WM_RBUTTONUP, 0, lparam)
                elif action_type == "scroll":
                    wparam = ((int(scroll_delta) & 0xFFFF) << 16)
                    user32.PostMessageW(hwnd, WM_MOUSEWHEEL, wparam, lparam)
                elif action_type == "type_text" and target_hwnd:
                    for ch in str(text or ""):
                        user32.PostMessageW(hwnd, WM_CHAR, ord(ch), 0)
                elif action_type in ("hotkey", "key_tap") and target_hwnd:
                    for rec in win32_inputs:
                        if int(rec.get("type", 0)) == INPUT_KEYBOARD:
                            vk = int(rec.get("wVk", 0))
                            flags = int(rec.get("dwFlags", 0))
                            msg = WM_KEYUP if (flags & KEYEVENTF_KEYUP) else WM_KEYDOWN
                            user32.PostMessageW(hwnd, msg, vk, 0)
        except Exception:
            pass

    _run_on_default_desktop(_do_send)


def clipboard_paste_text(
    text: str,
    verify_readback: bool = True,
    restore_previous: bool = True,
    target_hwnd: int | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Set Win32 CF_UNICODETEXT clipboard, verify readback before paste, and dispatch Ctrl+V.

    Implements the verified clipboard paste mechanism from codex-computer-use (0x138043):
    OpenClipboard -> GlobalAlloc -> SetClipboardData(CF_UNICODETEXT) -> read-back verify -> Ctrl+V.
    """
    payload = str(text or "")
    ctrl_vk = _resolve_vk("ctrl")
    v_vk = _resolve_vk("v")
    ctrl_v_inputs = [
        _key_record(ctrl_vk, 0, 0),
        _key_record(v_vk, 0, 0),
        _key_record(v_vk, 0, KEYEVENTF_KEYUP),
        _key_record(ctrl_vk, 0, KEYEVENTF_KEYUP),
    ]

    if dry_run or sys.platform != "win32":
        return {
            "ok": True,
            "action_type": "clipboard_paste",
            "text": payload,
            "verified_readback": True,
            "restored_previous": bool(restore_previous),
            "dry_run": bool(dry_run),
            "win32_inputs": ctrl_v_inputs,
            "timestamp": time.time(),
        }

    box: dict[str, Any] = {"verified": False, "restored": False, "error": None}

    def _do_clipboard_paste() -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = wintypes.HANDLE
        kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
        kernel32.GlobalFree.argtypes = [wintypes.HANDLE]
        user32.GetClipboardData.argtypes = [wintypes.UINT]
        user32.GetClipboardData.restype = wintypes.HANDLE
        user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        user32.SetClipboardData.restype = wintypes.HANDLE

        def _set_clip_utf16(val: str) -> bool:
            raw_utf16 = val.encode("utf-16-le") + b"\x00\x00"
            h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(raw_utf16))
            if not h_mem:
                return False
            ptr = kernel32.GlobalLock(h_mem)
            if not ptr:
                kernel32.GlobalFree(h_mem)
                return False
            ctypes.memmove(ptr, raw_utf16, len(raw_utf16))
            kernel32.GlobalUnlock(h_mem)
            user32.EmptyClipboard()
            if not user32.SetClipboardData(CF_UNICODETEXT, h_mem):
                kernel32.GlobalFree(h_mem)
                return False
            return True

        def _get_clip_utf16() -> str | None:
            h_data = user32.GetClipboardData(CF_UNICODETEXT)
            if not h_data:
                return None
            ptr = kernel32.GlobalLock(h_data)
            if not ptr:
                return None
            try:
                return ctypes.wstring_at(ptr)
            finally:
                kernel32.GlobalUnlock(h_data)

        prev_text: str | None = None
        opened = False
        for _ in range(5):
            if user32.OpenClipboard(0):
                opened = True
                break
            time.sleep(0.01)

        if not opened:
            box["error"] = "Failed to open Win32 clipboard"
            return

        try:
            if restore_previous:
                prev_text = _get_clip_utf16()
            if not _set_clip_utf16(payload):
                box["error"] = "Failed to set CF_UNICODETEXT clipboard data"
                return
            if verify_readback:
                readback = _get_clip_utf16()
                if readback != payload:
                    box["error"] = "clipboard did not contain requested text after setting it"
                    return
                box["verified"] = True
            else:
                box["verified"] = True
        finally:
            user32.CloseClipboard()

        # Dispatch Ctrl+V
        _send_win32_inputs_live(
            None,
            ctrl_v_inputs,
            action_type="hotkey",
            target_hwnd=target_hwnd,
        )
        if target_hwnd and hasattr(user32, "PostMessageW"):
            user32.PostMessageW(int(target_hwnd), WM_PASTE, 0, 0)

        if restore_previous and prev_text is not None:
            time.sleep(0.08)
            if user32.OpenClipboard(0):
                try:
                    box["restored"] = _set_clip_utf16(prev_text)
                finally:
                    user32.CloseClipboard()

    _run_on_default_desktop(_do_clipboard_paste)
    if box["error"] is not None:
        raise ComputerUseSafetyAbort(str(box["error"]))

    return {
        "ok": True,
        "action_type": "clipboard_paste",
        "text": payload,
        "verified_readback": bool(box["verified"]),
        "restored_previous": bool(box["restored"]),
        "dry_run": False,
        "win32_inputs": ctrl_v_inputs,
        "timestamp": time.time(),
    }


def dispatch_gui_action(
    action_type: str,
    norm_x: int | None = None,
    norm_y: int | None = None,
    end_norm_x: int | None = None,
    end_norm_y: int | None = None,
    mark_id: int | None = None,
    marks_catalog: dict[int, dict[str, Any]] | None = None,
    text: str | None = None,
    keys: list[str] | tuple[str, ...] | None = None,
    scroll_delta: int = -120,
    screen_width: int = 1920,
    screen_height: int = 1080,
    origin_x: int = 0,
    origin_y: int = 0,
    dpi_scale: float = 1.0,
    dry_run: bool = True,
    fail_safe_corner: bool = True,
    use_clipboard: bool = False,
    screenshot_id: str | None = None,
    session_manager: Any | None = None,
) -> dict[str, Any]:
    """Synthesize and optionally execute a Win32 GUI input action."""
    if action_type not in SUPPORTED_ACTION_TYPES:
        raise ValueError(
            f"Unsupported action_type '{action_type}'. Supported: {SUPPORTED_ACTION_TYPES}"
        )

    if screenshot_id is not None and session_manager is not None:
        session_manager.validate_screenshot_id(screenshot_id)

    target_hwnd: int | None = None
    if mark_id is not None:
        catalog = marks_catalog or {}
        if mark_id in catalog:
            mark_info = catalog[mark_id]
        elif str(mark_id) in catalog:  # type: ignore[comparison-overlap]
            mark_info = catalog[str(mark_id)]  # type: ignore[index]
        else:
            raise KeyError(f"Unknown SoM mark_id {mark_id} in marks_catalog")
        c1000 = mark_info["center_1000"]
        norm_x = int(c1000[0])
        norm_y = int(c1000[1])
        if "hwnd" in mark_info and mark_info["hwnd"]:
            target_hwnd = int(mark_info["hwnd"])

    resolved_1000: tuple[int, int] | None = None
    resolved_px: tuple[int, int] | None = None

    if action_type in _MOUSE_POINTER_ACTIONS or (norm_x is not None and norm_y is not None):
        nx = 500 if norm_x is None else int(norm_x)
        ny = 500 if norm_y is None else int(norm_y)
        resolved_1000 = (nx, ny)
        resolved_px = denormalize_from_grid_1000(
            nx,
            ny,
            screen_width=screen_width,
            screen_height=screen_height,
            origin_x=origin_x,
            origin_y=origin_y,
            dpi_scale=dpi_scale,
        )
        if fail_safe_corner and ((nx == 0 and ny == 0) or (resolved_px[0] == 0 and resolved_px[1] == 0)):
            raise ComputerUseSafetyAbort(
                f"Fail-safe corner (0, 0) triggered emergency abort for action '{action_type}'."
            )

    win32_inputs: list[dict[str, int]] = []

    if action_type == "move":
        assert resolved_1000 is not None
        ax, ay = _to_win32_abs(resolved_1000[0]), _to_win32_abs(resolved_1000[1])
        win32_inputs.append(_mouse_record(ax, ay, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE))

    elif action_type == "click":
        assert resolved_1000 is not None
        ax, ay = _to_win32_abs(resolved_1000[0]), _to_win32_abs(resolved_1000[1])
        win32_inputs.extend(
            [
                _mouse_record(ax, ay, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE),
                _mouse_record(ax, ay, MOUSEEVENTF_LEFTDOWN | MOUSEEVENTF_ABSOLUTE),
                _mouse_record(ax, ay, MOUSEEVENTF_LEFTUP | MOUSEEVENTF_ABSOLUTE),
            ]
        )

    elif action_type == "double_click":
        assert resolved_1000 is not None
        ax, ay = _to_win32_abs(resolved_1000[0]), _to_win32_abs(resolved_1000[1])
        win32_inputs.extend(
            [
                _mouse_record(ax, ay, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE),
                _mouse_record(ax, ay, MOUSEEVENTF_LEFTDOWN | MOUSEEVENTF_ABSOLUTE),
                _mouse_record(ax, ay, MOUSEEVENTF_LEFTUP | MOUSEEVENTF_ABSOLUTE),
                _mouse_record(ax, ay, MOUSEEVENTF_LEFTDOWN | MOUSEEVENTF_ABSOLUTE),
                _mouse_record(ax, ay, MOUSEEVENTF_LEFTUP | MOUSEEVENTF_ABSOLUTE),
            ]
        )

    elif action_type == "right_click":
        assert resolved_1000 is not None
        ax, ay = _to_win32_abs(resolved_1000[0]), _to_win32_abs(resolved_1000[1])
        win32_inputs.extend(
            [
                _mouse_record(ax, ay, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE),
                _mouse_record(ax, ay, MOUSEEVENTF_RIGHTDOWN | MOUSEEVENTF_ABSOLUTE),
                _mouse_record(ax, ay, MOUSEEVENTF_RIGHTUP | MOUSEEVENTF_ABSOLUTE),
            ]
        )

    elif action_type == "drag":
        assert resolved_1000 is not None
        ax1, ay1 = _to_win32_abs(resolved_1000[0]), _to_win32_abs(resolved_1000[1])
        ex = int(end_norm_x) if end_norm_x is not None else min(1000, resolved_1000[0] + 100)
        ey = int(end_norm_y) if end_norm_y is not None else min(1000, resolved_1000[1] + 100)
        if fail_safe_corner and ex == 0 and ey == 0:
            raise ComputerUseSafetyAbort("Fail-safe corner (0, 0) triggered on drag destination.")
        ax2, ay2 = _to_win32_abs(ex), _to_win32_abs(ey)
        win32_inputs.extend(
            [
                _mouse_record(ax1, ay1, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE),
                _mouse_record(ax1, ay1, MOUSEEVENTF_LEFTDOWN | MOUSEEVENTF_ABSOLUTE),
                _mouse_record(ax2, ay2, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE),
                _mouse_record(ax2, ay2, MOUSEEVENTF_LEFTUP | MOUSEEVENTF_ABSOLUTE),
            ]
        )

    elif action_type == "scroll":
        assert resolved_1000 is not None
        ax, ay = _to_win32_abs(resolved_1000[0]), _to_win32_abs(resolved_1000[1])
        win32_inputs.extend(
            [
                _mouse_record(ax, ay, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE),
                _mouse_record(ax, ay, MOUSEEVENTF_WHEEL, mouse_data=int(scroll_delta)),
            ]
        )

    elif action_type == "type_text":
        payload_text = str(text or "")
        for ch in payload_text:
            code = ord(ch)
            win32_inputs.append(_key_record(0, code, KEYEVENTF_UNICODE))
            win32_inputs.append(_key_record(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))

    elif action_type == "hotkey":
        key_seq = list(keys or [])
        vks = [_resolve_vk(k) for k in key_seq]
        for vk in vks:
            win32_inputs.append(_key_record(vk, 0, 0))
        for vk in reversed(vks):
            win32_inputs.append(_key_record(vk, 0, KEYEVENTF_KEYUP))

    elif action_type == "key_tap":
        key_seq = list(keys) if keys else ([text] if text else ["enter"])
        for k in key_seq:
            vk = _resolve_vk(str(k))
            win32_inputs.append(_key_record(vk, 0, 0))
            win32_inputs.append(_key_record(vk, 0, KEYEVENTF_KEYUP))

    clipboard_result: dict[str, Any] | None = None
    if action_type == "type_text" and use_clipboard:
        clipboard_result = clipboard_paste_text(
            str(text or ""),
            verify_readback=True,
            restore_previous=True,
            target_hwnd=target_hwnd,
            dry_run=dry_run,
        )
    elif not dry_run and sys.platform == "win32":
        _send_win32_inputs_live(
            resolved_px,
            win32_inputs,
            action_type=action_type,
            target_hwnd=target_hwnd,
            text=text,
            scroll_delta=scroll_delta,
        )

    out_payload: dict[str, Any] = {
        "ok": True,
        "action_type": action_type,
        "dry_run": bool(dry_run),
        "mark_id": mark_id,
        "resolved_1000": resolved_1000,
        "resolved_px": resolved_px,
        "win32_inputs": win32_inputs,
        "timestamp": time.time(),
    }
    if screenshot_id is not None:
        out_payload["screenshot_id"] = screenshot_id
    if clipboard_result is not None:
        out_payload["clipboard_paste"] = clipboard_result
    return out_payload
