---
name: computer-use
description: Native Windows desktop screen capture, UIA control extraction, Set-of-Marks (SoM) visual grounding, [0..1000] coordinate normalization, Win32 SendInput synthesis, and RFC 6962 visual safety oracle.
---

# AGY Computer Use & GUI Grounding Skill

Use this skill when automating native Windows desktop applications, inspecting UIA control hierarchies, rendering Set-of-Marks (SoM) overlays, dispatching `[0, 1000]` normalized mouse/keyboard actions, or auditing GUI state transitions with RFC 6962 Merkle receipts.

## Workflow
1. **Capture & Ground (`cu_capture_som`)**: Capture desktop or window frames (`capture_screen_frame`), extract interactive UIA elements (`extract_uia_element_tree`), and overlay numbered Set-of-Marks (`annotate_som_elements`).
2. **Coordinate Mapping**: Map between physical pixels and `[0, 1000]` normalized coordinates (`normalize_to_grid_1000` / `denormalize_from_grid_1000`) with Per-Monitor DPI V2 awareness (`get_monitor_dpi_scale`).
3. **Safe Action Synthesis (`cu_click`, `cu_type`, `cu_hotkey`, `cu_scroll`)**: Synthesize Win32 `SendInput` events via `dispatch_gui_action` with `(0, 0)` fail-safe corner abort (`ComputerUseSafetyAbort`) and `SafetyPolicy` window filtering.
4. **Visual Action Oracle (`cu_verify_oracle`, `cu_merkle_audit`)**: Compute 64-bit horizontal gradient dHash deltas (`compute_frame_dhash64`, `compute_visual_hamming_delta`) and verify RFC 6962 (`0x00` leaf / `0x01` internal node) Merkle inclusion proofs (`VisualActionOracle`).
