#!/usr/bin/env python3
"""
Rotameter Flow Meter Reader - Raspberry Pi Inference Script (v4)

Uses YOLOv8 to detect the float position in a rotameter and controls
a 4-state traffic light system via GPIO.

Traffic Light States:
  RED    = No flow (float below zero-pos threshold)
  AMBER  = Rinse 1 (float between zero-pos and rinse1-pos, ~≤10 GPM)
  BLUE   = Rinse 2 (float between rinse1-pos and rinse2-pos, ~≤25 GPM)
  GREEN  = Online  (float above rinse2-pos, >25 GPM)

The system uses position-based calibration rather than GPM calculation,
which handles non-linear rotameter scales correctly. Calibrate once per
rotameter type by measuring where the 10 GPM and 25 GPM marks fall as
a ratio of the total tube height (see README for calibration steps).

Hardware:
  - Raspberry Pi 4
  - Raspberry Pi Camera Module 2
  - Green LED on GPIO 17 (Pin 11)
  - Amber LED on GPIO 22 (Pin 15)
  - Blue LED on GPIO 23 (Pin 16)
  - Red LED on GPIO 27 (Pin 13)

Dependencies:
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
BLUE_LED_PIN = 23    # BCM GPIO 23 = Physical Pin 16
RED_LED_PIN = 27     # BCM GPIO 27 = Physical Pin 13

# ── Calibration Defaults ────────────────────────────────────────────
# Position ratios (0.0 = bottom of tube, 1.0 = top of tube)
# Calibrate per rotameter type — see README for instructions
ZERO_POS = 0.05     # Below this = no flow (RED)
RINSE1_POS = 0.22   # Below this = rinse 1 (AMBER, ~10 GPM)
RINSE2_POS = 0.45   # Below this = rinse 2 (BLUE, ~25 GPM)
                     # Above this = online (GREEN)

# ── Model Configuration ─────────────────────────────────────────────
MODEL_PATH = "best.pt"      # Path to your trained YOLOv8 model
CONFIDENCE_THRESHOLD = 0.5

# ── YOLO Class IDs (must match training data.yaml) ──────────────────
CLASS_TUBE = 0
CLASS_FLOAT = 1

# ── Debounce Configuration ──────────────────────────────────────────
DEBOUNCE_COUNT = 3  # Consecutive same-state readings before switching


def setup_gpio():
    """Initialize GPIO pins for 4-state traffic light LEDs."""
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(GREEN_LED_PIN, GPIO.OUT)
    GPIO.setup(AMBER_LED_PIN, GPIO.OUT)
    GPIO.setup(BLUE_LED_PIN, GPIO.OUT)
    GPIO.setup(RED_LED_PIN, GPIO.OUT)
    set_traffic_light("RED")  # Start with red (safe default)


def set_traffic_light(state: str):
    """
    Control the 4-state traffic light LEDs.
      RED   → Red on, others off (no flow)
      AMBER → Amber on, others off (rinse 1, ≤10 GPM)
      BLUE  → Blue on, others off (rinse 2, ≤25 GPM)
      GREEN → Green on, others off (online, >25 GPM)
    """
    GPIO.output(GREEN_LED_PIN, GPIO.HIGH if state == "GREEN" else GPIO.LOW)
    GPIO.output(AMBER_LED_PIN, GPIO.HIGH if state == "AMBER" else GPIO.LOW)
    GPIO.output(BLUE_LED_PIN, GPIO.HIGH if state == "BLUE" else GPIO.LOW)
    GPIO.output(RED_LED_PIN, GPIO.HIGH if state == "RED" else GPIO.LOW)


def get_traffic_state(position_ratio: float, zero_pos: float,
                      rinse1_pos: float, rinse2_pos: float) -> str:
    """
    Determine traffic light state from float position ratio.
    Uses calibrated position thresholds instead of GPM values,
    which handles non-linear rotameter scales correctly.

      position ≤ zero_pos   → RED   (no flow)
      position ≤ rinse1_pos → AMBER (rinse 1, ~10 GPM)
      position ≤ rinse2_pos → BLUE  (rinse 2, ~25 GPM)
      position > rinse2_pos → GREEN (online)
    """
    if position_ratio <= zero_pos:
        return "RED"
    elif position_ratio <= rinse1_pos:
        return "AMBER"
    elif position_ratio <= rinse2_pos:
        return "BLUE"
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


def calculate_position(results, conf_threshold):
    """
    Calculate the float's position ratio from YOLOv8 detection results.

    Detects 'tube' and 'float' bounding boxes, then computes the float's
    top edge position relative to the tube height.

    Position ratio:
      0.0 = float at bottom of tube (no flow)
      1.0 = float at top of tube (max flow)

    Returns:
        float or None: position_ratio (0.0–1.0), or None if detection fails.
    """
    boxes = results[0].boxes
    if boxes is None or len(boxes) == 0:
        return None

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
        return None

    tube_xyxy = tube_box[0]
    float_xyxy = float_box[0]

    tube_top = tube_xyxy[1]     # y_min of tube
    tube_bottom = tube_xyxy[3]  # y_max of tube
    float_top_y = float_xyxy[1]  # Top edge of float = reading point

    tube_height = tube_bottom - tube_top
    if tube_height <= 0:
        return None

    # Higher in image = smaller y value = more flow
    position_ratio = (tube_bottom - float_top_y) / tube_height
    position_ratio = max(0.0, min(1.0, position_ratio))

    return position_ratio


def draw_overlay(frame, results, position_ratio, state):
    """Draw bounding boxes and flow info on the frame for optional display."""
    annotated = results[0].plot()

    color_map = {
        "GREEN": (0, 255, 0),
        "BLUE": (255, 191, 0),
        "AMBER": (0, 191, 255),
        "RED": (0, 0, 255),
    }
    color = color_map.get(state, (255, 255, 255))

    if position_ratio is not None:
        status_text = f"Position: {position_ratio * 100:.1f}%"
        label = state
    else:
        status_text = "NO DETECTION"
        label = "NO DETECTION"

    cv2.putText(annotated, status_text, (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
    cv2.putText(annotated, label, (10, 65),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 3)
    return annotated


def main():
    parser = argparse.ArgumentParser(
        description="Rotameter Flow Meter Reader (4-State Traffic Light)")
    parser.add_argument("--model", default=MODEL_PATH,
                        help="Path to YOLOv8 .pt model")
    parser.add_argument("--zero-pos", type=float, default=ZERO_POS,
                        help="Position ratio below which = no flow / RED (default: 0.05)")
    parser.add_argument("--rinse1-pos", type=float, default=RINSE1_POS,
                        help="Position ratio for rinse 1 / AMBER threshold (default: 0.22)")
    parser.add_argument("--rinse2-pos", type=float, default=RINSE2_POS,
                        help="Position ratio for rinse 2 / BLUE threshold (default: 0.45)")
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
    parser.add_argument("--calibrate", action="store_true",
                        help="Run in calibration mode (prints live position ratio)")
    args = parser.parse_args()

    res = tuple(int(x) for x in args.resolution.split("x"))

    print("=" * 60)
    print("  Rotameter Flow Meter Reader")
    print("  LUPW Flow Traffic Light System (v4)")
    print("=" * 60)

    # Load model
    model = YOLO(args.model)
    print(f"  [OK] Model loaded: {args.model}")

    # Setup GPIO
    setup_gpio()
    print(f"  [OK] GPIO ready (Green=GPIO{GREEN_LED_PIN}, "
          f"Blue=GPIO{BLUE_LED_PIN}, "
          f"Amber=GPIO{AMBER_LED_PIN}, Red=GPIO{RED_LED_PIN})")

    # Setup camera
    camera = setup_camera(resolution=res)
    print(f"  [OK] Camera ready ({res[0]}x{res[1]})")
    print(f"  [OK] Thresholds: zero={args.zero_pos:.2f}, "
          f"rinse1={args.rinse1_pos:.2f}, rinse2={args.rinse2_pos:.2f}")

    if args.calibrate:
        print("-" * 60)
        print("  CALIBRATION MODE")
        print("  Showing live position ratio. Note the values at:")
        print("    - 0 GPM (no flow)   → use as --zero-pos")
        print("    - 10 GPM (rinse 1)  → use as --rinse1-pos")
        print("    - 25 GPM (rinse 2)  → use as --rinse2-pos")
        print("  Press Ctrl+C to stop.\n")

        try:
            while True:
                frame = camera.capture_array()
                results = model(frame, verbose=False)
                position_ratio = calculate_position(results, args.confidence)

                if position_ratio is not None:
                    print(f"\r  Position ratio: {position_ratio:.4f} "
                          f"({position_ratio * 100:.1f}%)    ",
                          end="", flush=True)
                else:
                    print("\r  NO DETECTION                         ",
                          end="", flush=True)

                if args.display:
                    state = get_traffic_state(position_ratio or 0.0,
                                             args.zero_pos, args.rinse1_pos,
                                             args.rinse2_pos)
                    overlay = draw_overlay(frame, results, position_ratio, state)
                    cv2.imshow("LUPW Calibration", overlay)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break

                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n\n  Calibration ended.")
        finally:
            camera.stop()
            if args.display:
                cv2.destroyAllWindows()
        return

    print("-" * 60)
    print("  Monitoring flow... Press Ctrl+C to stop.\n")

    current_state = "RED"
    debounce_counter = 0
    pending_state = "RED"

    # CSV logging
    log_file = open(args.log, "w", newline="")
    log_writer = csv.writer(log_file)
    log_writer.writerow(["timestamp", "position_pct", "state"])

    try:
        while True:
            frame = camera.capture_array()
            results = model(frame, verbose=False)
            position_ratio = calculate_position(results, args.confidence)

            if position_ratio is not None:
                new_state = get_traffic_state(
                    position_ratio, args.zero_pos,
                    args.rinse1_pos, args.rinse2_pos
                )

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
                    f"{position_ratio * 100:.1f}",
                    current_state,
                ])

                print(
                    f"\r  Position: {position_ratio * 100:5.1f}% | {current_state:6s}",
                    end="", flush=True,
                )
            else:
                print("\r  NO DETECTION                         ",
                      end="", flush=True)

            if args.display:
                overlay = draw_overlay(
                    frame, results, position_ratio, current_state
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
