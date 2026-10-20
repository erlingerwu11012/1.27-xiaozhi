#!/usr/bin/env python3
"""Convert a square startup MP4 into the ESP32 boot animation assets.

The display payload is a small, lossless grayscale XOR/PackBits stream.  The
source used by this product is monochrome on black, so storing only its active
rectangle is both smaller and cheaper to decode than H.264 or MJPEG on-device.
Audio is converted separately to the mono 16 kHz Ogg Opus format already used
by AudioService::PlaySound().
"""

from __future__ import annotations

import argparse
import struct
import subprocess
from pathlib import Path

import cv2
import numpy as np


MAGIC = b"REBA"
VERSION = 1
HEADER = struct.Struct("<4sHHHHHHHHHHII")
FRAME_SIZE = struct.Struct("<I")


def pack_xor_delta(delta: np.ndarray) -> bytes:
    flat = delta.reshape(-1)
    output = bytearray()
    index = 0
    while index < flat.size:
        if flat[index] == 0:
            end = index + 1
            while end < flat.size and flat[end] == 0 and end - index < 128:
                end += 1
            output.append(end - index - 1)
        else:
            end = index + 1
            while end < flat.size and flat[end] != 0 and end - index < 128:
                end += 1
            output.append(0x80 | (end - index - 1))
            output.extend(flat[index:end].tobytes())
        index = end
    return bytes(output)


def unpack_xor_delta(encoded: bytes, previous: np.ndarray) -> np.ndarray:
    restored = previous.copy().reshape(-1)
    index = 0
    cursor = 0
    while index < restored.size:
        if cursor >= len(encoded):
            raise ValueError("truncated frame")
        control = encoded[cursor]
        cursor += 1
        count = (control & 0x7F) + 1
        if index + count > restored.size:
            raise ValueError("frame run exceeds crop")
        if control & 0x80:
            if cursor + count > len(encoded):
                raise ValueError("truncated literal run")
            literal = np.frombuffer(encoded[cursor : cursor + count], dtype=np.uint8)
            restored[index : index + count] ^= literal
            cursor += count
        index += count
    if cursor != len(encoded):
        raise ValueError("trailing frame bytes")
    return restored.reshape(previous.shape)


def sample_video(path: Path, target_fps: int, canvas: int) -> tuple[list[np.ndarray], float]:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"unable to open video: {path}")

    source_fps = float(capture.get(cv2.CAP_PROP_FPS))
    source_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    if source_fps <= 0 or source_frames <= 0:
        raise RuntimeError("video has invalid FPS or frame count")
    duration = source_frames / source_fps

    sampled: list[np.ndarray] = []
    next_time = 0.0
    frame_index = 0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        timestamp = frame_index / source_fps
        if timestamp + 1e-9 >= next_time:
            resized = cv2.resize(frame, (canvas, canvas), interpolation=cv2.INTER_AREA)
            # The source is neutral gray.  Converting explicitly also makes the
            # device payload independent of harmless H.264 channel noise.
            gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
            sampled.append(gray)
            next_time += 1.0 / target_fps
        frame_index += 1
    capture.release()

    if not sampled:
        raise RuntimeError("video decoder returned no frames")
    return sampled, duration


def active_crop(frames: list[np.ndarray], threshold: int) -> tuple[int, int, int, int]:
    active = np.zeros_like(frames[0], dtype=bool)
    for frame in frames:
        active |= frame > threshold
    ys, xs = np.where(active)
    if xs.size == 0:
        raise RuntimeError("startup animation contains no visible pixels")
    x1 = int(xs.min())
    y1 = int(ys.min())
    x2 = int(xs.max()) + 1
    y2 = int(ys.max()) + 1
    return x1, y1, x2, y2


def build_animation(
    source: Path,
    output: Path,
    fps: int,
    canvas: int,
    threshold: int,
    fade_ms: int,
) -> dict[str, int | float]:
    frames, source_duration = sample_video(source, fps, canvas)
    x1, y1, x2, y2 = active_crop(frames, threshold)

    if fade_ms > 0:
        fade_seconds = fade_ms / 1000.0
        fade_start = max(0.0, source_duration - fade_seconds)
        for index, frame in enumerate(frames):
            timestamp = index / fps
            if timestamp >= fade_start:
                factor = max(0.0, min(1.0, (source_duration - timestamp) / fade_seconds))
                frames[index] = np.rint(frame.astype(np.float32) * factor).astype(np.uint8)

    # A final black frame guarantees a clean handoff to the already-rendered
    # Home framebuffer without extending the source audio.
    frames.append(np.zeros_like(frames[0]))
    cropped = [frame[y1:y2, x1:x2] for frame in frames]

    previous = np.zeros_like(cropped[0])
    encoded_frames: list[bytes] = []
    for frame in cropped:
        encoded = pack_xor_delta(np.bitwise_xor(frame, previous))
        restored = unpack_xor_delta(encoded, previous)
        if not np.array_equal(restored, frame):
            raise RuntimeError("internal animation round-trip validation failed")
        encoded_frames.append(encoded)
        previous = frame

    interval_ms = round(1000 / fps)
    payload_size = sum(FRAME_SIZE.size + len(frame) for frame in encoded_frames)
    duration_ms = interval_ms * len(encoded_frames)
    header = HEADER.pack(
        MAGIC,
        VERSION,
        HEADER.size,
        canvas,
        canvas,
        x1,
        y1,
        x2 - x1,
        y2 - y1,
        interval_ms,
        len(encoded_frames),
        duration_ms,
        payload_size,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as stream:
        stream.write(header)
        for frame in encoded_frames:
            stream.write(FRAME_SIZE.pack(len(frame)))
            stream.write(frame)

    expected_size = HEADER.size + payload_size
    if output.stat().st_size != expected_size:
        raise RuntimeError("animation file size validation failed")
    return {
        "source_duration_ms": round(source_duration * 1000),
        "duration_ms": duration_ms,
        "frames": len(encoded_frames),
        "crop_x": x1,
        "crop_y": y1,
        "crop_width": x2 - x1,
        "crop_height": y2 - y1,
        "bytes": expected_size,
    }


def convert_audio(ffmpeg: Path, source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(ffmpeg),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-map",
        "0:a:0",
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-af",
        "volume=-0.9dB",
        "-c:a",
        "libopus",
        "-b:a",
        "32k",
        "-application",
        "audio",
        "-frame_duration",
        "60",
        str(output),
    ]
    subprocess.run(command, check=True)
    data = output.read_bytes()
    head = data.find(b"OpusHead")
    if head < 0 or head + 19 > len(data):
        raise RuntimeError("converted audio is not Ogg Opus")
    channels = data[head + 9]
    sample_rate = int.from_bytes(data[head + 12 : head + 16], "little")
    if channels != 1 or sample_rate != 16000:
        raise RuntimeError(
            f"unexpected Opus header: channels={channels}, sample_rate={sample_rate}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--animation-output", type=Path, required=True)
    parser.add_argument("--audio-output", type=Path, required=True)
    parser.add_argument("--ffmpeg", type=Path, required=True)
    parser.add_argument("--fps", type=int, default=20)
    parser.add_argument("--canvas", type=int, default=320)
    parser.add_argument("--threshold", type=int, default=5)
    parser.add_argument("--fade-ms", type=int, default=200)
    args = parser.parse_args()

    if not args.source.is_file():
        raise SystemExit(f"source not found: {args.source}")
    if not args.ffmpeg.is_file():
        raise SystemExit(f"ffmpeg not found: {args.ffmpeg}")
    if args.fps <= 0 or 1000 % args.fps != 0:
        raise SystemExit("fps must be a positive divisor of 1000")

    info = build_animation(
        args.source,
        args.animation_output,
        args.fps,
        args.canvas,
        args.threshold,
        args.fade_ms,
    )
    convert_audio(args.ffmpeg, args.source, args.audio_output)
    print(
        "animation: "
        f"{info['frames']} frames, {info['duration_ms']} ms, "
        f"crop=({info['crop_x']},{info['crop_y']},"
        f"{info['crop_width']}x{info['crop_height']}), "
        f"{info['bytes']} bytes"
    )
    print(f"audio: {args.audio_output.stat().st_size} bytes")


if __name__ == "__main__":
    main()
