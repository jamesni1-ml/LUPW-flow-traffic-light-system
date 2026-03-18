#!/usr/bin/env python3
"""
Rotameter Flow Meter Reader - Raspberry Pi Inference Script (v3)

Uses YOLOv8 to detect the float position in a rotameter and controls
a 3-state traffic light system via GPIO.

Traffic Light States:
  RED    = No flow (0 GPM)
  AMBER  = Rinse flow (≤10 GPM)
  GREEN  = Online flow (>10 GPM)

Hardware:
  - Raspberry Pi 4
  - Raspberry Pi Camera Module 2
  - Green LED on GPIO 17 (Pin 11)
  - Amber LED on GPIO 22 (Pin 15)
  - Red LED on GPIO 27 (Pin 13)

Dependencies (vision-ml compatible):
  ultralytics, opencv-python, picamera2, RPi.GPIO
"""

import argparse
import csv
import time
from datetime import datetime

import cv2
import numpy as np
from ultralytics import YOLO
from picamera2 import Picamera2
import RPi.GPIO as GPIO

# ── GPIO Pin Configuration ──────────────────────────────────────────
GREEN_LED_PIN = 17   # BCM GPIO 17 = Physical Pin 11
AMBER_LED_PIN = 22   # BCM GPIO 22 = Physical Pin 15
RED_LED_PIN = 27     # BCM GPIO 27 = Physical Pin 13

# ── Flow Configuration ──────────────────────────────────────────────
MAX_FLOW_RATE = 100.0       # Set to your rotameter's max scale reading
RINSE_GPM = 10.0            # Flow ≤ this = rinse (amber), above = online (green)
ZERO_FLOW_THRESHOLD = 0.02  # Below 2% of scale = considered zero flow

# ── Model Configuration ─────────────────────────────────────────────
MODEL_PATH = "best.pt"      # Path to your trained YOLOv8 model
CONFIDENCE_THRESHOLD = 0.5

# ── YOLO Class IDs (must match training data.yaml) ──────────────────
CLASS_TUBE = 0
CLASS_FLOAT = 1

# ── Debounce Configuration ──────────────────────────────────────────
DEBOUNCE_COUNT = 3  # Consecutive same-state readings before switching


def setup_gpio():
    """Initialize GPIO pins for traffic light LEDs."""
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(GREEN_LED_PIN, GPIO.OUT)
    GPIO.setup(AMBER_LED_PIN, GPIO.OUT)
    GPIO.setup(RED_LED_PIN, GPIO.OUT)
    set_traffic_light("RED")  # Start with red (safe default)


def set_traffic_light(state: str):
    """
    Control the 3-state traffic light LEDs.
      RED   → Red on, others off (no flow)
      AMBER → Amber on, others off (rinse ≤10 GPM)
      GREEN → Green on, others off (online >10 GPM)
    """
    GPIO.output(GREEN_LED_PIN, GPIO.HIGH if state == "GREEN" else GPIO.LOW)
    GPIO.output(AMBER_LED_PIN, GPIO.HIGH if state == "AMBER" else GPIO.LOW)
    GPIO.output(RED_LED_PIN, GPIO.HIGH if state == "RED" else GPIO.LOW)


def get_traffic_state(flow_rate: float, rinse_gpm: float) -> str:
    """
    Determine traffic light state from flow rate.
      0 GPM         → RED   (no flow)
      >0 to ≤rinse  → AMBER (rinse)
      >rinse        → GREEN (online)
    """
    if flow_rate <= 0:
        return "RED"
    elif flow_rate <= rinse_gpm:
        return "AMBER"
    else:
        return "GREEN"


def setup_camera(resolution=(640, 480)):
    """Initialize the Raspberry Pi Camera Module 2."""
    picam2 = Picamera2()
    config = picam2.create_preview_configuration(
        main={"size": resolution, "format": "RGB888"}
    )
    picam2.configure(config)
    picam2.start()
    time.sleep(2)  # Camera warm-up
    return picam2


def calculate_flow(results, max_flow_rate, conf_threshold):
    """
    Calculate flow rate from YOLOv8 detection results.

    Detects 'tube' and 'float' bounding boxes, then computes the float's
    vertical position relative to the tube height.

    Position ratio:
      0.0 = float at bottom of tube (no flow)
      1.0 = float at top of tube (max flow)

    Returns:
        tuple: (flow_rate, position_ratio) or (None, None) if detection fails.
    """
    boxes = results[0].boxes
    if boxes is None or len(boxes) == 0:
        return None, None

    tube_box = None
    float_box = None

    for box in boxes:
        cls = int(box.cls[0])
        conf = float(box.conf[0])
        if conf < conf_threshold:
            continue
        xyxy = box.xyxy[0].cpu().numpy()
        if cls == CLASS_TUBE and (tube_box is None or conf > tube_box[1]):
            tube_box = (xyxy, conf)
        elif cls == CLASS_FLOAT and (float_box is None or conf > float_box[1]):
            float_box = (xyxy, conf)

    if tube_box is None or float_box is None:
        return None, None

    tube_xyxy = tube_box[0]
    float_xyxy = float_box[0]

    tube_top = tube_xyxy[1]     # y_min of tube
    tube_bottom = tube_xyxy[3]  # y_max of tube
    float_top_y = float_xyxy[1]  # Top edge of float = reading point

    tube_height = tube_bottom - tube_top
    if tube_height <= 0:
        return None, None

    # Higher in image = smaller y value = more flow
    position_ratio = (tube_bottom - float_top_y) / tube_height
    position_ratio = max(0.0, min(1.0, position_ratio))

    flow_rate = position_ratio * max_flow_rate
    return flow_rate, position_ratio


def draw_overlay(frame, results, flow_rate, position_ratio, state):
    """Draw bounding boxes and flow info on the frame for optional display."""
    annotated = results[0].plot()

    color_map = {"GREEN": (0, 255, 0), "AMBER": (0, 191, 255), "RED": (0, 0, 255)}
    color = color_map.get(state, (255, 255, 255))

    if flow_rate is not None:
        status_text = f"Flow: {flow_rate:.1f} GPM ({position_ratio * 100:.0f}%)"
        label = state
    else:
        status_text = "Flow: NO DETECTION"
        label = "NO DETECTION"

    cv2.putText(annotated, status_text, (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
    cv2.putText(annotated, label, (10, 65),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 3)
    return annotated


def main():
    parser = argparse.ArgumentParser(
        description="Rotameter Flow Meter Reader (3-State Traffic Light)")
    parser.add_argument("--model", default=MODEL_PATH,
                        help="Path to YOLOv8 .pt model")
    parser.add_argument("--max-flow", type=float, default=MAX_FLOW_RATE,
                        help="Max flow rate on rotameter scale (GPM)")
    parser.add_argument("--rinse-gpm", type=float, default=RINSE_GPM,
                        help="Flow threshold for rinse/online boundary (default: 10)")
    parser.add_argument("--threshold", type=float, default=ZERO_FLOW_THRESHOLD,
                        help="Position ratio below which flow is zero (default: 0.02)")
    parser.add_argument("--confidence", type=float, default=CONFIDENCE_THRESHOLD,
                        help="Minimum detection confidence (default: 0.5)")
    parser.add_argument("--display", action="store_true",
                        help="Show live camera feed with overlay (requires monitor)")
    parser.add_argument("--resolution", default="640x480",
                        help="Camera resolution WxH (default: 640x480)")
    parser.add_argument("--interval", type=float, default=0.5,
                        help="Seconds between readings (default: 0.5)")
    parser.add_argument("--log", default="flow_log.csv",
                        help="CSV log file path (default: flow_log.csv)")
    args = parser.parse_args()

    res = tuple(int(x) for x in args.resolution.split("x"))

    print("=" * 60)
    print("  Rotameter Flow Meter Reader")
    print("  LUPW Flow Traffic Light System (v3)")
    print("=" * 60)

    # Load model
    model = YOLO(args.model)
    print(f"  [OK] Model loaded: {args.model}")

    # Setup GPIO
    setup_gpio()
    print(f"  [OK] GPIO ready (Green=GPIO{GREEN_LED_PIN}, "
          f"Amber=GPIO{AMBER_LED_PIN}, Red=GPIO{RED_LED_PIN})")

    # Setup camera
    camera = setup_camera(resolution=res)
    print(f"  [OK] Camera ready ({res[0]}x{res[1]})")
    print(f"  [OK] Rinse threshold: {args.rinse_gpm} GPM")
    print("-" * 60)
    print("  Monitoring flow... Press Ctrl+C to stop.\n")

    current_state = "RED"
    debounce_counter = 0
    pending_state = "RED"

    # CSV logging
    log_file = open(args.log, "w", newline="")
    log_writer = csv.writer(log_file)
    log_writer.writerow(["timestamp", "flow_rate", "position_pct", "state"])

    try:
        while True:
            frame = camera.capture_array()
            results = model(frame, verbose=False)
            flow_rate, position_ratio = calculate_flow(
                results, args.max_flow, args.confidence
            )

            if flow_rate is not None:
                # Apply zero-flow threshold
                if position_ratio <= args.threshold:
                    flow_rate = 0.0

                new_state = get_traffic_state(flow_rate, args.rinse_gpm)

                # Debounce: require consecutive same-state readings
                if new_state == pending_state:
                    debounce_counter += 1
                else:
                    pending_state = new_state
                    debounce_counter = 1

                if debounce_counter >= DEBOUNCE_COUNT and current_state != pending_state:
                    current_state = pending_state
                    set_traffic_light(current_state)

                # Log
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                log_writer.writerow([
                    now,
                    f"{flow_rate:.2f}",
                    f"{position_ratio * 100:.1f}",
                    current_state,
                ])

                print(
                    f"\r  Flow: {flow_rate:6.1f} / {args.max_flow:.0f} GPM "
                    f"({position_ratio * 100:5.1f}%) | {current_state:6s}",
                    end="", flush=True,
                )
            else:
                print("\r  Flow: NO DETECTION                    ",
                      end="", flush=True)

            if args.display:
                overlay = draw_overlay(
                    frame, results, flow_rate, position_ratio, current_state
                )
                cv2.imshow("LUPW Flow Monitor", overlay)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\n\n  Shutting down...")
    finally:
        set_traffic_light("RED")
        GPIO.cleanup()
        camera.stop()
        log_file.close()
        if args.display:
            cv2.destroyAllWindows()
        print(f"  Log saved to {args.log}")
        print("  Goodbye!")


if __name__ == "__main__":
    main()
