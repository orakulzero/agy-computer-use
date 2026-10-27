"""ISO 9001:2015 Agile V Hypothesis Property-Based Verification Suite.

Covers mathematical invariants for [0..1000] coordinate normalization/denormalization,
multi-monitor negative origin translation invariance, DPI scaling monotonicity,
64-bit dHash determinism, Hamming metric properties, and RFC 6962 Merkle proof soundness.
"""

from __future__ import annotations

import sys
from pathlib import Path

from hypothesis import given, settings, strategies as st

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


@settings(max_examples=50, deadline=None)
@given(
    x_px=st.integers(min_value=-50000, max_value=50000),
    y_px=st.integers(min_value=-50000, max_value=50000),
    screen_width=st.integers(min_value=1, max_value=15360),
    screen_height=st.integers(min_value=1, max_value=8640),
    origin_x=st.integers(min_value=-16384, max_value=16384),
    origin_y=st.integers(min_value=-16384, max_value=16384),
)
def test_hypothesis_normalize_bounds_invariants(
    x_px: int,
    y_px: int,
    screen_width: int,
    screen_height: int,
    origin_x: int,
    origin_y: int,
) -> None:
    """REQ-CU-002: Property 1: normalize_to_grid_1000 always maps into integer [0, 1000] x [0, 1000]."""
    from agy_computer_use.som import normalize_to_grid_1000

    nx, ny = normalize_to_grid_1000(
        x_px,
        y_px,
        screen_width=screen_width,
        screen_height=screen_height,
        origin_x=origin_x,
        origin_y=origin_y,
    )
    assert isinstance(nx, int)
    assert isinstance(ny, int)
    assert 0 <= nx <= 1000
    assert 0 <= ny <= 1000


@settings(max_examples=50, deadline=None)
@given(
    x1=st.integers(min_value=-4000, max_value=8000),
    dx=st.integers(min_value=0, max_value=4000),
    y1=st.integers(min_value=-4000, max_value=8000),
    dy=st.integers(min_value=0, max_value=4000),
    screen_width=st.integers(min_value=100, max_value=7680),
    screen_height=st.integers(min_value=100, max_value=4320),
)
def test_hypothesis_normalize_monotonicity(
    x1: int,
    dx: int,
    y1: int,
    dy: int,
    screen_width: int,
    screen_height: int,
) -> None:
    """REQ-CU-002: Property 2: normalize_to_grid_1000 is monotonically non-decreasing in both axes."""
    from agy_computer_use.som import normalize_to_grid_1000

    nx1, ny1 = normalize_to_grid_1000(x1, y1, screen_width=screen_width, screen_height=screen_height)
    nx2, ny2 = normalize_to_grid_1000(
        x1 + dx, y1 + dy, screen_width=screen_width, screen_height=screen_height
    )
    assert nx1 <= nx2
    assert ny1 <= ny2


@settings(max_examples=50, deadline=None)
@given(
    norm_x=st.integers(min_value=0, max_value=1000),
    norm_y=st.integers(min_value=0, max_value=1000),
    screen_width=st.integers(min_value=1000, max_value=7680),
    screen_height=st.integers(min_value=1000, max_value=4320),
    origin_x=st.integers(min_value=-7680, max_value=7680),
    origin_y=st.integers(min_value=-4320, max_value=4320),
)
def test_hypothesis_bijective_grid_1000_roundtrip(
    norm_x: int,
    norm_y: int,
    screen_width: int,
    screen_height: int,
    origin_x: int,
    origin_y: int,
) -> None:
    """REQ-CU-002 / REQ-CU-003: Property 3: Denormalizing then normalizing recovers [0..1000] within <= 1 grid unit."""
    from agy_computer_use.som import denormalize_from_grid_1000, normalize_to_grid_1000

    x_px, y_px = denormalize_from_grid_1000(
        norm_x,
        norm_y,
        screen_width=screen_width,
        screen_height=screen_height,
        origin_x=origin_x,
        origin_y=origin_y,
        dpi_scale=1.0,
    )
    rec_x, rec_y = normalize_to_grid_1000(
        x_px,
        y_px,
        screen_width=screen_width,
        screen_height=screen_height,
        origin_x=origin_x,
        origin_y=origin_y,
    )
    assert abs(rec_x - norm_x) <= 1
    assert abs(rec_y - norm_y) <= 1


@settings(max_examples=50, deadline=None)
@given(
    rel_x=st.integers(min_value=0, max_value=3840),
    rel_y=st.integers(min_value=0, max_value=2160),
    origin_x=st.integers(min_value=-11520, max_value=11520),
    origin_y=st.integers(min_value=-6480, max_value=6480),
    screen_width=st.integers(min_value=640, max_value=3840),
    screen_height=st.integers(min_value=480, max_value=2160),
)
def test_hypothesis_multi_monitor_negative_offset_translation_invariance(
    rel_x: int,
    rel_y: int,
    origin_x: int,
    origin_y: int,
    screen_width: int,
    screen_height: int,
) -> None:
    """REQ-CU-002: Property 4: Shifting both pixel coordinates and monitor origin preserves normalized coords."""
    from agy_computer_use.som import normalize_to_grid_1000

    base_nx, base_ny = normalize_to_grid_1000(
        rel_x,
        rel_y,
        screen_width=screen_width,
        screen_height=screen_height,
        origin_x=0,
        origin_y=0,
    )
    shifted_nx, shifted_ny = normalize_to_grid_1000(
        origin_x + rel_x,
        origin_y + rel_y,
        screen_width=screen_width,
        screen_height=screen_height,
        origin_x=origin_x,
        origin_y=origin_y,
    )
    assert base_nx == shifted_nx
    assert base_ny == shifted_ny


@settings(max_examples=40, deadline=None)
@given(
    norm_x=st.integers(min_value=10, max_value=1000),
    norm_y=st.integers(min_value=10, max_value=1000),
    dpi_low=st.floats(min_value=0.5, max_value=1.5, allow_nan=False, allow_infinity=False),
    dpi_delta=st.floats(min_value=0.25, max_value=2.0, allow_nan=False, allow_infinity=False),
)
def test_hypothesis_dpi_scale_ordering(
    norm_x: int,
    norm_y: int,
    dpi_low: float,
    dpi_delta: float,
) -> None:
    """REQ-CU-002: Property 5: Denormalization with higher DPI scale yields monotonic physical coordinates."""
    from agy_computer_use.som import denormalize_from_grid_1000

    dpi_high = dpi_low + dpi_delta
    x_low, y_low = denormalize_from_grid_1000(
        norm_x, norm_y, screen_width=1920, screen_height=1080, origin_x=0, origin_y=0, dpi_scale=dpi_low
    )
    x_high, y_high = denormalize_from_grid_1000(
        norm_x, norm_y, screen_width=1920, screen_height=1080, origin_x=0, origin_y=0, dpi_scale=dpi_high
    )
    assert isinstance(x_low, int) and isinstance(y_low, int)
    assert isinstance(x_high, int) and isinstance(y_high, int)
    assert (x_low <= x_high and y_low <= y_high) or (x_low >= x_high and y_low >= y_high)


@settings(max_examples=30, deadline=None)
@given(
    seed=st.integers(min_value=0, max_value=100000),
    width=st.integers(min_value=16, max_value=160),
    height=st.integers(min_value=16, max_value=120),
)
def test_hypothesis_dhash64_determinism_and_uint64_bounds(
    seed: int,
    width: int,
    height: int,
) -> None:
    """REQ-CU-004: Property 6: compute_frame_dhash64 is deterministic and bounded in [0, 2^64 - 1]."""
    from agy_computer_use.capture import capture_screen_frame
    from agy_computer_use.safety_oracle import compute_frame_dhash64

    frame = capture_screen_frame(width=width, height=height, synthetic_seed=seed)
    h1 = compute_frame_dhash64(frame["rgb_bytes"], width, height)
    h2 = compute_frame_dhash64(frame["rgb_bytes"], width, height)
    assert h1 == h2
    assert 0 <= h1 <= (1 << 64) - 1


@settings(max_examples=50, deadline=None)
@given(
    a=st.integers(min_value=0, max_value=(1 << 64) - 1),
    b=st.integers(min_value=0, max_value=(1 << 64) - 1),
    c=st.integers(min_value=0, max_value=(1 << 64) - 1),
)
def test_hypothesis_hamming_delta_metric_space_axioms(a: int, b: int, c: int) -> None:
    """REQ-CU-004: Property 7: Hamming delta satisfies identity, symmetry, triangle inequality, and epistemic law."""
    from agy_computer_use.safety_oracle import compute_visual_hamming_delta

    d_aa = compute_visual_hamming_delta(a, a)
    assert d_aa["hamming_distance"] == 0
    assert d_aa["epistemic_status"] == "[NO_EFFECT]"
    assert d_aa["visual_change_detected"] is False

    d_ab = compute_visual_hamming_delta(a, b)
    d_ba = compute_visual_hamming_delta(b, a)
    d_bc = compute_visual_hamming_delta(b, c)
    d_ac = compute_visual_hamming_delta(a, c)

    assert d_ab["hamming_distance"] == d_ba["hamming_distance"]
    assert 0 <= d_ab["hamming_distance"] <= 64
    assert d_ac["hamming_distance"] <= d_ab["hamming_distance"] + d_bc["hamming_distance"]

    if d_ab["hamming_distance"] >= 2:
        assert d_ab["epistemic_status"] == "[FACT]"
        assert d_ab["visual_change_detected"] is True
    else:
        assert d_ab["epistemic_status"] == "[NO_EFFECT]"
        assert d_ab["visual_change_detected"] is False


@settings(max_examples=15, deadline=None)
@given(leaf_count=st.integers(min_value=1, max_value=12))
def test_hypothesis_rfc6962_merkle_proof_soundness(leaf_count: int) -> None:
    """REQ-CU-005: Property 8: Every leaf in an N-leaf VisualActionOracle verifies against the Merkle root."""
    from agy_computer_use.capture import capture_screen_frame
    from agy_computer_use.safety_oracle import VisualActionOracle

    oracle = VisualActionOracle()
    base_frame = capture_screen_frame(width=64, height=48, synthetic_seed=1)

    for idx in range(leaf_count):
        next_frame = capture_screen_frame(width=64, height=48, synthetic_seed=idx + 2)
        oracle.record_and_verify_action(
            action_payload={"action_type": "click", "seq": idx, "norm_x": 100 + idx, "norm_y": 200},
            frame_before=base_frame,
            frame_after=next_frame,
        )

    summary = oracle.get_merkle_audit_summary()
    assert summary["leaf_count"] == leaf_count
    root = summary["root"]
    for receipt in summary["receipts"]:
        assert VisualActionOracle.verify_action_receipt(
            receipt,
            receipt["merkle_proof"],
            root,
        ) is True


@settings(max_examples=20, deadline=None)
@given(
    leaf_count=st.integers(min_value=1, max_value=8),
    flip_pos=st.integers(min_value=0, max_value=63),
)
def test_hypothesis_rfc6962_merkle_root_tamper_detection(leaf_count: int, flip_pos: int) -> None:
    """REQ-CU-005: Property 9: Corrupting any hex digit of expected_root invalidates all Merkle inclusion proofs."""
    from agy_computer_use.capture import capture_screen_frame
    from agy_computer_use.safety_oracle import VisualActionOracle

    oracle = VisualActionOracle()
    f0 = capture_screen_frame(width=64, height=48, synthetic_seed=50)
    for idx in range(leaf_count):
        f1 = capture_screen_frame(width=64, height=48, synthetic_seed=51 + idx)
        oracle.record_and_verify_action(
            action_payload={"action_type": "move", "seq": idx, "norm_x": 300, "norm_y": 300},
            frame_before=f0,
            frame_after=f1,
        )

    summary = oracle.get_merkle_audit_summary()
    root = summary["root"]
    mutated_char = "0" if root[flip_pos] != "0" else "a"
    corrupted_root = root[:flip_pos] + mutated_char + root[flip_pos + 1 :]

    for receipt in summary["receipts"]:
        assert VisualActionOracle.verify_action_receipt(
            receipt,
            receipt["merkle_proof"],
            corrupted_root,
        ) is False
