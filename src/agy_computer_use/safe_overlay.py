"""Collision-Aware Set-of-Marks (SoM) Safe Margin Badge Placement Engine.

Implements REQ-CU-OVERLAY-01:
- Frozen SafeBadgePlacement dataclass in [0, 1000] x [0, 1000] normalized space
- Exact bounding-box intersection area computation (boxes_overlap_area)
- Exterior anchor selection avoiding text occlusion, neighbor collisions, and (0, 0) fail-safe corner
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

VALID_ANCHORS: tuple[str, ...] = (
    "top_left_outside",
    "top_right_outside",
    "bottom_left_outside",
    "bottom_right_outside",
    "interior_fallback",
)


@dataclass(frozen=True)
class SafeBadgePlacement:
    """@requirement("REQ-CU-OVERLAY-01") Immutable SoM badge placement descriptor."""

    mark_id: int
    target_box_1000: tuple[int, int, int, int]
    badge_box_1000: tuple[int, int, int, int]
    anchor_position: str
    collision_score: float


def _contains_box(
    outer: tuple[int, int, int, int],
    inner: tuple[int, int, int, int],
) -> bool:
    """Return True if outer completely contains inner."""
    return (
        outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and outer[2] >= inner[2]
        and outer[3] >= inner[3]
    )


class SafeMarginOverlay:
    """@requirement("REQ-CU-OVERLAY-01") Collision-aware Set-of-Marks badge placement engine."""

    @staticmethod
    def boxes_overlap_area(
        box_a: tuple[int, int, int, int],
        box_b: tuple[int, int, int, int],
    ) -> int:
        """@requirement("REQ-CU-OVERLAY-01") Compute intersection area of two [x0, y0, x1, y1] boxes."""
        ix0 = max(int(box_a[0]), int(box_b[0]))
        iy0 = max(int(box_a[1]), int(box_b[1]))
        ix1 = min(int(box_a[2]), int(box_b[2]))
        iy1 = min(int(box_a[3]), int(box_b[3]))
        if ix1 <= ix0 or iy1 <= iy0:
            return 0
        return (ix1 - ix0) * (iy1 - iy0)

    def compute_safe_placements(
        self,
        controls: list[dict[str, Any]],
        badge_width: int = 28,
        badge_height: int = 20,
    ) -> list[SafeBadgePlacement]:
        """@requirement("REQ-CU-OVERLAY-01") Compute non-occluding badge placements in [0, 1000] space."""
        w = max(1, int(badge_width))
        h = max(1, int(badge_height))

        parsed_controls: list[tuple[int, tuple[int, int, int, int]]] = []
        for idx, ctrl in enumerate(controls, start=1):
            mark_id = int(ctrl.get("mark_id", idx))
            raw_box = ctrl.get("box_1000", ctrl.get("bbox_1000", (0, 0, 100, 100)))
            tx0 = max(0, min(1000, int(raw_box[0])))
            ty0 = max(0, min(1000, int(raw_box[1])))
            tx1 = max(tx0, min(1000, int(raw_box[2])))
            ty1 = max(ty0, min(1000, int(raw_box[3])))
            parsed_controls.append((mark_id, (tx0, ty0, tx1, ty1)))

        placements: list[SafeBadgePlacement] = []

        for idx, (mark_id, target_box) in enumerate(parsed_controls):
            tx0, ty0, tx1, ty1 = target_box

            raw_candidates: list[tuple[str, tuple[int, int, int, int]]] = [
                ("top_left_outside", (tx0, ty0 - h, tx0 + w, ty0)),
                ("top_right_outside", (tx1 - w, ty0 - h, tx1, ty0)),
                ("bottom_left_outside", (tx0, ty1, tx0 + w, ty1 + h)),
                ("bottom_right_outside", (tx1 - w, ty1, tx1, ty1 + h)),
            ]

            best_anchor: str | None = None
            best_box: tuple[int, int, int, int] | None = None
            best_score: float = float("inf")

            for anchor_name, (bx0, by0, bx1, by1) in raw_candidates:
                if bx0 < 0:
                    bx0 = 0
                    bx1 = w
                elif bx1 > 1000:
                    bx1 = 1000
                    bx0 = 1000 - w

                if bx0 < 0 or by0 < 0 or bx1 > 1000 or by1 > 1000:
                    continue
                if bx0 < 5 and by0 < 5:
                    continue
                cand_box = (bx0, by0, bx1, by1)
                if self.boxes_overlap_area(cand_box, target_box) > 0:
                    continue

                collision = 0
                for j, (_, other_box) in enumerate(parsed_controls):
                    if j == idx:
                        continue
                    if _contains_box(other_box, target_box):
                        continue
                    collision += self.boxes_overlap_area(cand_box, other_box)

                for prev in placements:
                    collision += self.boxes_overlap_area(cand_box, prev.badge_box_1000)

                score = float(collision)
                if score < best_score:
                    best_score = score
                    best_anchor = anchor_name
                    best_box = cand_box
                    if score == 0.0:
                        break

            if best_anchor is None or best_box is None:
                fb_x0 = max(6 if ty0 < 5 else 0, min(1000 - w, tx0))
                fb_y0 = max(6 if fb_x0 < 5 else 0, min(1000 - h, ty0))
                best_box = (fb_x0, fb_y0, fb_x0 + w, fb_y0 + h)
                best_anchor = "interior_fallback"
                best_score = float(self.boxes_overlap_area(best_box, target_box))

            placements.append(
                SafeBadgePlacement(
                    mark_id=mark_id,
                    target_box_1000=target_box,
                    badge_box_1000=best_box,
                    anchor_position=best_anchor,
                    collision_score=best_score,
                )
            )

        return placements
