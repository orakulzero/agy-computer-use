import pytest
from pathlib import Path
from agy_computer_use.replay_recorder import LosslessReplayRecorder, ReplayFrameEvent

def test_filter_active_frames_identical_consecutive_no_action_keep_action_false():
    """
    Test that filter_active_frames correctly handles frames with identical consecutive
    dhash64 values (zero Hamming distance) when keep_action_frames=False and no
    action labels are present, ensuring all but the first frame are dropped as idle.
    """
    recorder = LosslessReplayRecorder()
    frames = [
        ReplayFrameEvent(frame_index=0, timestamp_ms=0, dhash64=0xFF00FF00FF00FF00, action_label=""),
        ReplayFrameEvent(frame_index=1, timestamp_ms=100, dhash64=0xFF00FF00FF00FF00, action_label=""),
        ReplayFrameEvent(frame_index=2, timestamp_ms=200, dhash64=0xFF00FF00FF00FF00, action_label=""),
        ReplayFrameEvent(frame_index=3, timestamp_ms=300, dhash64=0xFF00FF00FF00FF00, action_label=""),
    ]
    
    result = recorder.filter_active_frames(frames, min_hamming_delta=2, keep_action_frames=False)
    
    assert len(result["kept_frames"]) == 1
    assert result["kept_frames"][0].frame_index == 0
    assert result["dropped_idle_count"] == 3
    assert result["fact_transitions"] == 0
    assert result["compression_ratio"] == 0.25

def test_filter_active_frames_empty_list():
    """Test behavior with an empty list of frames."""
    recorder = LosslessReplayRecorder()
    result = recorder.filter_active_frames([], min_hamming_delta=2, keep_action_frames=True)
    
    assert result["kept_frames"] == []
    assert result["dropped_idle_count"] == 0
    assert result["fact_transitions"] == 0
    assert result["compression_ratio"] == 0.0

def test_filter_active_frames_hamming_distance_threshold():
    """Test that frames are kept when Hamming distance is >= threshold."""
    recorder = LosslessReplayRecorder()
    # 0xFF00... vs 0xFE00... has 1 bit difference
    # 0xFF00... vs 0xFC00... has 2 bits difference
    frames = [
        ReplayFrameEvent(frame_index=0, timestamp_ms=0, dhash64=0xFF00FF00FF00FF00, action_label=""),
        ReplayFrameEvent(frame_index=1, timestamp_ms=100, dhash64=0xFE00FF00FF00FF00, action_label=""), # delta 1 (drop)
        ReplayFrameEvent(frame_index=2, timestamp_ms=200, dhash64=0xFC00FF00FF00FF00, action_label=""), # delta 2 from prev (0xFE00... vs 0xFC00... -> delta 1, wait, prev kept is NOT used for comparison. The code compares with immediately preceding frame!)
    ]
    
    # Wait, let's look at the code.
    # prev = frames[idx - 1]
    # hamming = self._hamming64(prev.dhash64, current.dhash64)
    # It compares with idx-1 frame, not the last kept frame.
    
    frames2 = [
        ReplayFrameEvent(frame_index=0, timestamp_ms=0, dhash64=0xFF00FF00FF00FF00, action_label=""),
        ReplayFrameEvent(frame_index=1, timestamp_ms=100, dhash64=0xFC00FF00FF00FF00, action_label=""), # delta 2 -> keep
        ReplayFrameEvent(frame_index=2, timestamp_ms=200, dhash64=0xF800FF00FF00FF00, action_label=""), # delta 1 from 0xFC (11111100 vs 11111000) -> drop
    ]
    
    result = recorder.filter_active_frames(frames2, min_hamming_delta=2, keep_action_frames=False)
    
    assert len(result["kept_frames"]) == 2
    assert result["kept_frames"][0].frame_index == 0
    assert result["kept_frames"][1].frame_index == 1
    assert result["dropped_idle_count"] == 1
    assert result["fact_transitions"] == 1

def test_filter_active_frames_keep_action_frames_true():
    """Test that frames with actions are kept even if Hamming distance < threshold when keep_action_frames=True."""
    recorder = LosslessReplayRecorder()
    frames = [
        ReplayFrameEvent(frame_index=0, timestamp_ms=0, dhash64=0xFF00FF00FF00FF00, action_label=""),
        ReplayFrameEvent(frame_index=1, timestamp_ms=100, dhash64=0xFF00FF00FF00FF00, action_label="click"), # keep
        ReplayFrameEvent(frame_index=2, timestamp_ms=200, dhash64=0xFF00FF00FF00FF00, action_label="  "), # drop (whitespace only)
    ]
    
    result = recorder.filter_active_frames(frames, min_hamming_delta=2, keep_action_frames=True)
    
    assert len(result["kept_frames"]) == 2
    assert result["kept_frames"][0].frame_index == 0
    assert result["kept_frames"][1].frame_index == 1
    assert result["dropped_idle_count"] == 1

def test_build_ffmpeg_concat_manifest():
    """Test building ffmpeg concat manifest."""
    recorder = LosslessReplayRecorder()
    frames = [
        ReplayFrameEvent(frame_index=0, timestamp_ms=0, dhash64=0),
        ReplayFrameEvent(frame_index=5, timestamp_ms=500, dhash64=0),
        ReplayFrameEvent(frame_index=10, timestamp_ms=1200, dhash64=0),
    ]
    
    manifest = recorder.build_ffmpeg_concat_manifest(frames, frame_dir="/tmp/frames", fps=10)
    
    lines = manifest.splitlines()
    assert lines[0] == "ffconcat version 1.0"
    assert lines[1] == "file '/tmp/frames/frame_0000.png'"
    assert lines[2] == "duration 0.500"
    assert lines[3] == "file '/tmp/frames/frame_0005.png'"
    assert lines[4] == "duration 0.700"
    assert lines[5] == "file '/tmp/frames/frame_0010.png'"
    assert lines[6] == "duration 0.100" # default for 10fps

def test_build_ffmpeg_encode_command():
    """Test building ffmpeg encode command."""
    recorder = LosslessReplayRecorder()
    command = recorder.build_ffmpeg_encode_command(manifest_file="manifest.txt", output_mp4="out.mp4", crf=23)
    
    assert command == [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        "manifest.txt",
        "-c:v",
        "libx264",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "out.mp4",
    ]
