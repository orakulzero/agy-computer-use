"""Lossless dHash Idle-Frame Slicing and Deterministic FFmpeg Concat Replay Recorder.

Implements REQ-CU-REPLAY-01:
- ReplayFrameEvent dataclass with 64-bit dHash and optional GUI action telemetry
- Idle-frame pruning via 64-bit dHash Hamming delta ([FACT] >= 2 bits) and action retention
- FFmpeg ffconcat v1.0 manifest generation and deterministic libx264 CLI encoding builder
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

_UINT64_MASK = (1 << 64) - 1


@dataclass(frozen=True)
class ReplayFrameEvent:
    """@requirement("REQ-CU-REPLAY-01") Single captured desktop frame event for replay slicing."""

    frame_index: int
    timestamp_ms: int
    dhash64: int
    action_label: str = ""
    cursor_1000: tuple[int, int] | None = None


class LosslessReplayRecorder:
    """@requirement("REQ-CU-REPLAY-01") Lossless idle-frame filter and FFmpeg concat exporter."""

    @staticmethod
    def _hamming64(a: int, b: int) -> int:
        return ((int(a) & _UINT64_MASK) ^ (int(b) & _UINT64_MASK)).bit_count()

    def filter_active_frames(
        self,
        frames: list[ReplayFrameEvent],
        min_hamming_delta: int = 2,
        keep_action_frames: bool = True,
    ) -> dict[str, Any]:
        """@requirement("REQ-CU-REPLAY-01") Filter idle frames while preserving [FACT] transitions."""
        if not frames:
            return {
                "kept_frames": [],
                "dropped_idle_count": 0,
                "fact_transitions": 0,
                "compression_ratio": 0.0,
            }

        threshold = max(1, int(min_hamming_delta))
        kept_frames: list[ReplayFrameEvent] = [frames[0]]
        dropped_idle_count = 0
        fact_transitions = 0

        for idx in range(1, len(frames)):
            current = frames[idx]
            prev = frames[idx - 1]
            hamming = self._hamming64(prev.dhash64, current.dhash64)
            is_fact = hamming >= threshold
            has_action = bool(current.action_label and current.action_label.strip())

            if is_fact:
                fact_transitions += 1
                kept_frames.append(current)
            elif keep_action_frames and has_action:
                kept_frames.append(current)
            else:
                dropped_idle_count += 1

        total = len(frames)
        compression_ratio = float(len(kept_frames)) / float(total) if total > 0 else 0.0

        return {
            "kept_frames": kept_frames,
            "dropped_idle_count": dropped_idle_count,
            "fact_transitions": fact_transitions,
            "compression_ratio": compression_ratio,
        }

    def build_ffmpeg_concat_manifest(
        self,
        kept_frames: list[ReplayFrameEvent],
        frame_dir: Path | str,
        fps: int = 10,
    ) -> str:
        """@requirement("REQ-CU-REPLAY-01") Build an ffconcat version 1.0 manifest for kept frames."""
        base_dir = Path(frame_dir)
        safe_fps = max(1, int(fps))
        default_duration = 1.0 / float(safe_fps)

        lines: list[str] = ["ffconcat version 1.0"]
        for i, frame in enumerate(kept_frames):
            frame_path = (base_dir / f"frame_{int(frame.frame_index):04d}.png").as_posix()
            lines.append(f"file '{frame_path}'")
            if i + 1 < len(kept_frames):
                delta_sec = (
                    float(kept_frames[i + 1].timestamp_ms - frame.timestamp_ms) / 1000.0
                )
                duration = max(default_duration, delta_sec)
            else:
                duration = default_duration
            lines.append(f"duration {duration:.3f}")

        return "\n".join(lines) + "\n"

    def build_ffmpeg_encode_command(
        self,
        manifest_file: Path | str,
        output_mp4: Path | str,
        crf: int = 18,
    ) -> list[str]:
        """@requirement("REQ-CU-REPLAY-01") Build deterministic FFmpeg libx264 encoding arguments."""
        return [
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
            str(int(crf)),
            "-pix_fmt",
            "yuv420p",
            str(output_mp4),
        ]
