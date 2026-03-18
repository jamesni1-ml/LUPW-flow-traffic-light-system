#!/usr/bin/env python3
"""
Continuous video recording for LUPW rotameter data collection.

Run on the Raspberry Pi with the Camera Module 2. Records H264 video
until Ctrl+C or the optional --duration limit is reached.

Usage:
    python3 record_video.py                        # Record until Ctrl+C
    python3 record_video.py --duration 3600        # Record for 1 hour
    python3 record_video.py --resolution 1920x1080 # Record at 1080p

Default resolution is 640x480 to match inference.py.
Files are saved as: recording_YYYYMMDD_HHMMSS.h264
"""

import argparse
import signal
import sys
import time
from datetime import datetime

from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FfmpegOutput


def main():
    parser = argparse.ArgumentParser(description="Record video from Pi Camera")
    parser.add_argument("--duration", type=int, default=0,
                        help="Recording duration in seconds (0 = until Ctrl+C)")
    parser.add_argument("--resolution", default="640x480",
                        help="Video resolution WxH (default: 640x480)")
    parser.add_argument("--fps", type=int, default=15,
                        help="Frames per second (default: 15)")
    parser.add_argument("--output-dir", default=".",
                        help="Directory for output files (default: current)")
    args = parser.parse_args()

    width, height = (int(x) for x in args.resolution.split("x"))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{args.output_dir}/recording_{timestamp}.h264"

    cam = Picamera2()
    video_config = cam.create_video_configuration(
        main={"size": (width, height), "format": "RGB888"},
        controls={"FrameRate": args.fps},
    )
    cam.configure(video_config)

    encoder = H264Encoder(bitrate=4_000_000)
    output = FfmpegOutput(filename)

    # Graceful shutdown on Ctrl+C
    stop = False

    def handle_signal(sig, frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    cam.start()
    time.sleep(2)  # Camera warm-up
    cam.start_encoder(encoder, output)

    print(f"Recording to {filename}")
    print(f"  Resolution: {width}x{height} @ {args.fps} fps")
    if args.duration > 0:
        print(f"  Duration:   {args.duration}s")
    else:
        print("  Duration:   until Ctrl+C")
    print()

    start_time = time.time()
    try:
        while not stop:
            elapsed = time.time() - start_time
            mins, secs = divmod(int(elapsed), 60)
            hrs, mins = divmod(mins, 60)
            sys.stdout.write(f"\r  Recording... {hrs:02d}:{mins:02d}:{secs:02d}")
            sys.stdout.flush()
            time.sleep(1)
            if args.duration > 0 and elapsed >= args.duration:
                break
    finally:
        cam.stop_encoder()
        cam.stop()
        elapsed = time.time() - start_time
        print(f"\n\nSaved: {filename}")
        print(f"Duration: {int(elapsed)}s")


if __name__ == "__main__":
    main()
