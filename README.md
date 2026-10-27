# AGY Computer Use & GUI Grounding (`agy-computer-use` v1.0.0 Prototype)

> **Status**: Public Prototype Release (`v1.0.0-prototype`). Actively tested on Windows 11 (`WinSta0\Default` and background `PrintWindow` / Ghost Desktop sessions) with Google Antigravity 2.0.

Native Windows Desktop Computer-Use, UIA + Set-of-Marks (SoM) Grounding, `[0, 1000]` Bijective Coordinate Normalization, Win32 `SendInput` & Focusless `PostMessageW` Action Synthesis, Window Session Management, and RFC 6962 Visual Safety Oracle for Google Antigravity 2.0.

## Key Capabilities

1. **Win32 GDI & Synthetic Screen Capture (`agy_computer_use.capture`)**
   - Live Win32 GDI (`user32` / `gdi32` `BitBlt` + `GetDIBits`) desktop and region capture with automatic `WinSta0\Default` sandbox bridge and deterministic synthetic fallback for headless CI.
   - Zero-dependency pure-Python 24-bit BMP (`b"BM"`) and zlib-compressed PNG (`IHDR` / `IDAT` / `IEND`) encoders.
   - Top-level window enumeration (`enumerate_visible_windows`) and interactive child UIA control extraction (`extract_uia_element_tree`).

2. **Per-Monitor DPI & Set-of-Marks Grounding (`agy_computer_use.som`)**
   - Per-Monitor DPI V2 scale detection (`get_monitor_dpi_scale`).
   - Bijective `[0, 1000] x [0, 1000]` coordinate normalization (`normalize_to_grid_1000`) and denormalization (`denormalize_from_grid_1000`) with multi-monitor negative origin offset invariance.
   - Visual Set-of-Marks (`annotate_som_elements`) bounding box and numbered tag overlay.

3. **GUI Action Dispatch, Clipboard Fast-Path & Fail-Safe Corner (`agy_computer_use.actions`)**
   - Synthesizes Win32 `INPUT` (`MOUSEINPUT` / `KEYBDINPUT`) structures for 9 action types: `click`, `double_click`, `right_click`, `move`, `drag`, `scroll`, `type_text`, `hotkey`, `key_tap`.
   - Verified `CF_UNICODETEXT` clipboard paste (`clipboard_paste_text`) with read-back verification and prior clipboard state restoration.
   - Direct Set-of-Marks `mark_id` target lookup and `(0, 0)` top-left fail-safe abort (`ComputerUseSafetyAbort`).

4. **Background Window Capture & Ghost Desktop Isolation (`agy_computer_use.background`)**
   - Captures occluded or off-screen windows without stealing foreground focus via `PrintWindow(PW_RENDERFULLCONTENT)` (`capture_window_background`).
   - Dispatches focusless pointer and keyboard messages via `PostMessageW` (`WM_LBUTTONDOWN`, `WM_MOUSEMOVE`, `WM_CHAR`, `WM_SETTEXT`) (`dispatch_background_window_action`).
   - Off-screen window staging (`stage_window_offscreen` / `restore_window_onscreen`) and isolated Win32 secondary desktop (`GhostDesktopSession` via `CreateDesktopW`).

5. **Window Session Manager, UIA Diffing & Bezier Trajectories (`agy_computer_use.window_session`)**
   - `WindowSessionManager` enforcing `screenshot_id` geometry validation (rejecting stale screenshots when target windows move or resize) and `CompactionImageBudget` sliding-window image eviction.
   - Hierarchical `#1..#N` UIA tree text formatter (`format_uia_tree_text`) and incremental structural tree diffing (`diff_uia_trees`).
   - 7-control-point (`P0..P6`) two-segment cubic Bezier cursor trajectory synthesis (`synthesize_bezier_cursor_path`), `WDA_EXCLUDEFROMCAPTURE` (`0x11`) overlay cloaking (`apply_exclude_from_capture`), and physical ESC / mouse movement `InterruptionMonitor`.

6. **64-Bit Perceptual dHash, Prompt-Injection Shield & RFC 6962 Merkle Safety Oracle (`agy_computer_use.safety_oracle`)**
   - 64-bit horizontal gradient difference hash (`compute_frame_dhash64`) and Hamming delta classifier (`[FACT]` for `>= 2` bits, `[NO_EFFECT]` for `< 2` bits).
   - `SafetyPolicy` window filter blocking password managers, credential dialogs, UAC, and SmartScreen, plus indirect UI prompt-injection scanner (`detect_ui_prompt_injection`) and `<node_repl_review_evidence>` XML isolation (`wrap_untrusted_ui_evidence`).
   - `VisualActionOracle` maintaining an RFC 6962 (`0x00` leaf / `0x01` internal node) SHA-256 Merkle audit trail with cryptographic inclusion proof verification (`verify_action_receipt`).

7. **7-Tool MCP JSON-RPC 2.0 Server (`agy_computer_use.mcp_server`)**
   - `cu_capture_som`, `cu_click`, `cu_type`, `cu_hotkey`, `cu_scroll`, `cu_verify_oracle`, `cu_merkle_audit` (all composite tool identifiers strictly `<= 50` chars, well below the 64-character Antigravity limit).

## Installation & Verification

```bash
python -m pip install -e . --no-deps
python -m pytest tests/ -v
```

## License

MIT License - Copyright (c) 2026 orakulzero
