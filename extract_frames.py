#!/usr/bin/env python3
"""
Extract frames from recorded video for annotation.

Run on your workstation after copying video files from the Pi.
Extracts one frame every --interval seconds and saves as JPEG
into dataset/images/train/ ready for annotation on Roboflow.

Usage:
    python3 extract_frames.py recording_20260318_140000.h264
    python3 extract_frames.py recording.h264 --interval 2
    python3 extract_frames.py recording.h264 --output-dir dataset/images/train
"""

import argparse
import os

import cv2


def main():
    parser = argparse.ArgumentParser(description="Extract frames from video")
    parser.add_argument("video", help="Path to video file (.h264 / .mp4)")
    parser.add_argument("--interval", type=float, default=1.0,
                        help="Seconds between extracted frames (default: 1.0)")
    parser.add_argument("--output-dir", default="dataset/images/train",
                        help="Output directory (default: dataset/images/train)")
    parser.add_argument("--prefix", default="",
                        help="Filename prefix for extracted frames")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        print(f"Error: cannot open {args.video}")
        print("  If .h264, convert first: ffmpeg -i recording.h264 -c copy recording.mp4")
        return

    fps = cap.get(cv2.CAP_PROP_FPS) or 15.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frame_step = max(1, int(fps * args.interval))

    # Derive prefix from video filename if not provided
    prefix = args.prefix
    if not prefix:
        base = os.path.splitext(os.path.basename(args.video))[0]
        prefix = base + "_"

    print(f"Video:     {args.video}")
    print(f"FPS:       {fps:.1f}")
    print(f"Frames:    {total_frames}")
    print(f"Interval:  every {args.interval}s (every {frame_step} frames)")
    print(f"Output:    {args.output_dir}/")
    print()

    saved = 0
    frame_num = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_num % frame_step == 0:
            filename = f"{prefix}{frame_num:06d}.jpg"
            filepath = os.path.join(args.output_dir, filename)
            cv2.imwrite(filepath, frame)
            saved += 1
            if saved % 50 == 0:
                print(f"  Extracted {saved} frames...")
        frame_num += 1

    cap.release()
    print(f"\nDone — extracted {saved} frames to {args.output_dir}/")


if __name__ == "__main__":
    main()
