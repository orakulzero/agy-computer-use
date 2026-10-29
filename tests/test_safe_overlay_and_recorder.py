"""ISO 9001:2015 Agile V Verification Suite for Safe Margin Overlay and Replay Recorder.

Covers REQ-CU-OVERLAY-01 (Collision-Aware Set-of-Marks Safe Margin Placement)
and REQ-CU-REPLAY-01 (Lossless dHash Idle-Frame Slicing and FFmpeg Concat Export).
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

VALID_ANCHORS = {
    "top_left_outside",
    "top_right_outside",
    "bottom_left_outside",
    "bottom_right_outside",
    "interior_fallback",
}


def test_safe_badge_placement_frozen_and_overlap_area() -> None:
    """@requirement("REQ-CU-OVERLAY-01") Verify frozen SafeBadgePlacement and boxes_overlap_area."""
    from agy_computer_use.safe_overlay import SafeBadgePlacement, SafeMarginOverlay

    placement = SafeBadgePlacement(
        mark_id=1,
        target_box_1000=(200, 200, 400, 260),
        badge_box_1000=(200, 180, 228, 200),
        anchor_position="top_left_outside",
        collision_score=0.0,
    )
    assert placement.mark_id == 1
    assert placement.anchor_position in VALID_ANCHORS
    with pytest.raises(FrozenInstanceError):
        placement.mark_id = 99  # type: ignore[misc]

    overlay = SafeMarginOverlay()
    assert overlay.boxes_overlap_area((100, 100, 200, 200), (150, 150, 250, 250)) == 2500
    assert SafeMarginOverlay.boxes_overlap_area((0, 0, 50, 50), (50, 50, 100, 100)) == 0
    assert SafeMarginOverlay.boxes_overlap_area((10, 10, 30, 40), (10, 10, 30, 40)) == 600


def test_safe_margin_overlay_avoids_text_occlusion_and_origin() -> None:
    """@requirement("REQ-CU-OVERLAY-01") Place badges outside control interior and away from (0, 0)."""
    from agy_computer_use.safe_overlay import SafeMarginOverlay

    overlay = SafeMarginOverlay()
    controls = [
        {"mark_id": 1, "box_1000": (200, 200, 400, 250)},
        {"mark_id": 2, "box_1000": (0, 0, 120, 40)},
        {"mark_id": 3, "box_1000": (960, 970, 1000, 1000)},
    ]
    placements = overlay.compute_safe_placements(controls, badge_width=28, badge_height=20)
    assert len(placements) == 3

    # Mark 1 has ample margin above/below; badge must be outside target interior
    p1 = placements[0]
    assert p1.mark_id == 1
    assert p1.anchor_position != "interior_fallback"
    assert p1.collision_score == 0.0
    assert SafeMarginOverlay.boxes_overlap_area(p1.badge_box_1000, p1.target_box_1000) == 0

    for p in placements:
        bx0, by0, bx1, by1 = p.badge_box_1000
        assert 0 <= bx0 < bx1 <= 1000
        assert 0 <= by0 < by1 <= 1000
        assert (bx1 - bx0) == 28
        assert (by1 - by0) == 20
        assert bx0 >= 5 or by0 >= 5, "Badge must not touch (0, 0) fail-safe abort corner"
        assert p.anchor_position in VALID_ANCHORS


def test_safe_margin_overlay_dense_neighbors_and_interior_fallback() -> None:
    """@requirement("REQ-CU-OVERLAY-01") Minimize badge collisions in dense grids and full-screen controls."""
    from agy_computer_use.safe_overlay import SafeMarginOverlay

    overlay = SafeMarginOverlay()
    dense_controls = [
        {"mark_id": 10, "box_1000": (300, 180, 500, 200)},
        {"mark_id": 11, "box_1000": (300, 202, 500, 240)},
        {"mark_id": 12, "box_1000": (0, 0, 1000, 1000)},
    ]
    placements = overlay.compute_safe_placements(dense_controls, badge_width=28, badge_height=20)
    assert len(placements) == 3
    # Control 11 has Control 10 directly above its top-left; should pick a non-colliding outside anchor
    assert placements[1].collision_score == 0.0
    assert SafeMarginOverlay.boxes_overlap_area(
        placements[0].badge_box_1000, placements[1].badge_box_1000
    ) == 0
    # Full-screen control has no outside margin available -> must use interior_fallback
    assert placements[2].anchor_position == "interior_fallback"
    assert placements[2].badge_box_1000[0] >= 5 or placements[2].badge_box_1000[1] >= 5


def test_replay_recorder_filters_idle_frames_and_keeps_fact_transitions() -> None:
    """@requirement("REQ-CU-REPLAY-01") Filter idle frames via 64-bit dHash Hamming delta and action labels."""
    from agy_computer_use.replay_recorder import LosslessReplayRecorder, ReplayFrameEvent

    frames = [
        ReplayFrameEvent(0, 0, 0b0000, "", None),
        ReplayFrameEvent(1, 100, 0b0001, "", None),  # Hamming 1 (<2) -> idle drop
        ReplayFrameEvent(2, 200, 0b0001, "click", (500, 500)),  # Hamming 0, but action_label -> keep
        ReplayFrameEvent(3, 300, 0b0111, "", None),  # Hamming 2 (>=2) -> [FACT] transition keep
        ReplayFrameEvent(4, 400, 0b0111, "", None),  # Hamming 0 -> idle drop
    ]
    recorder = LosslessReplayRecorder()
    res = recorder.filter_active_frames(frames, min_hamming_delta=2, keep_action_frames=True)

    kept = res["kept_frames"]
    assert [f.frame_index for f in kept] == [0, 2, 3]
    assert res["dropped_idle_count"] == 2
    assert res["fact_transitions"] == 1
    assert 0.0 < res["compression_ratio"] < 1.0

    res_no_actions = recorder.filter_active_frames(
        frames, min_hamming_delta=2, keep_action_frames=False
    )
    assert [f.frame_index for f in res_no_actions["kept_frames"]] == [0, 3]


def test_replay_recorder_ffmpeg_concat_manifest_and_encode_cmd(tmp_path: Path) -> None:
    """@requirement("REQ-CU-REPLAY-01") Build ffconcat v1.0 manifest and deterministic libx264 CLI args."""
    from agy_computer_use.replay_recorder import LosslessReplayRecorder, ReplayFrameEvent

    recorder = LosslessReplayRecorder()
    kept_frames = [
        ReplayFrameEvent(0, 0, 0x11, "init", None),
        ReplayFrameEvent(3, 300, 0xFF, "click", (250, 400)),
        ReplayFrameEvent(5, 500, 0xF00, "type", (250, 400)),
    ]
    manifest = recorder.build_ffmpeg_concat_manifest(kept_frames, frame_dir=tmp_path, fps=10)
    lines = [line.strip() for line in manifest.strip().splitlines() if line.strip()]
    assert lines[0] == "ffconcat version 1.0"
    assert any("frame_0000.png" in line for line in lines)
    assert any("frame_0003.png" in line for line in lines)
    assert any("frame_0005.png" in line for line in lines)
    assert any(line.startswith("duration ") for line in lines)

    manifest_file = tmp_path / "replay.ffconcat"
    output_mp4 = tmp_path / "replay.mp4"
    cmd = recorder.build_ffmpeg_encode_command(manifest_file, output_mp4, crf=18)
    assert cmd == [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(manifest_file),
        "-c:v",
        "libx264",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        str(output_mp4),
    ]
