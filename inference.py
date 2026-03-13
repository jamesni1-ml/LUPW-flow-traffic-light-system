#!/usr/bin/env python3
"""
Rotameter Flow Meter Reader - Raspberry Pi Inference Script

Uses YOLOv8 to detect the float position in a rotameter and controls
traffic light LEDs via GPIO.

Traffic light states:
  RED    = No flow (zero GPM)
  AMBER  = Rinse mode (≤10 GPM)
  GREEN  = Online (>10 GPM)

Hardware:
  - Raspberry Pi 4
  - Raspberry Pi Camera Module 2
  - Green LED on GPIO 17 (Pin 11)
  - Amber LED on GPIO 22 (Pin 15)
  - Red LED on GPIO 27 (Pin 13)
"""

import argparse
import time

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
ZERO_FLOW_THRESHOLD = 0.05  # Below 5% of scale = considered zero flow
RINSE_GPM = 10.0            # At or below this GPM = rinse (amber)

# ── Model Configuration ─────────────────────────────────────────────
MODEL_PATH = "best.pt"      # Path to your trained YOLOv8 model
CONFIDENCE_THRESHOLD = 0.5

# ── YOLO Class IDs (must match training data.yaml) ──────────────────
CLASS_TUBE = 0
CLASS_FLOAT = 1


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
    Control the traffic light LEDs.
      'RED'   → RED on, AMBER off, GREEN off  (no flow)
      'AMBER' → RED off, AMBER on, GREEN off  (rinse ≤10 GPM)
      'GREEN' → RED off, AMBER off, GREEN on  (online >10 GPM)
    """
    GPIO.output(GREEN_LED_PIN, GPIO.HIGH if state == "GREEN" else GPIO.LOW)
    GPIO.output(AMBER_LED_PIN, GPIO.HIGH if state == "AMBER" else GPIO.LOW)
    GPIO.output(RED_LED_PIN, GPIO.HIGH if state == "RED" else GPIO.LOW)


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


def calculate_flow(results, max_flow_rate):
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
        if conf < CONFIDENCE_THRESHOLD:
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
    float_center_y = (float_xyxy[1] + float_xyxy[3]) / 2.0

    tube_height = tube_bottom - tube_top
    if tube_height <= 0:
        return None, None

    # Higher in image = smaller y value = more flow
    position_ratio = (tube_bottom - float_center_y) / tube_height
    position_ratio = max(0.0, min(1.0, position_ratio))

    flow_rate = position_ratio * max_flow_rate
    return flow_rate, position_ratio


def get_traffic_state(flow_rate):
    """
    Determine traffic light state from flow rate in GPM.
      flow_rate == 0 (or None) → 'RED'    (no flow)
      0 < flow_rate <= 10 GPM  → 'AMBER'  (rinse)
      flow_rate > 10 GPM       → 'GREEN'  (online)
    """
    if flow_rate is None or flow_rate <= 0:
        return "RED"
    elif flow_rate <= RINSE_GPM:
        return "AMBER"
    else:
        return "GREEN"


STATE_COLORS = {
    "RED": (0, 0, 255),
    "AMBER": (0, 165, 255),
    "GREEN": (0, 255, 0),
}

STATE_LABELS = {
    "RED": "NO FLOW",
    "AMBER": "RINSE (<=10 GPM)",
    "GREEN": "ONLINE (>10 GPM)",
}


def draw_overlay(frame, results, flow_rate, position_ratio, traffic_state):
    """Draw bounding boxes and flow info on the frame for optional display."""
    annotated = results[0].plot()

    if flow_rate is not None:
        status_text = f"Flow: {flow_rate:.1f} GPM ({position_ratio * 100:.0f}%)"
        color = STATE_COLORS[traffic_state]
        label = STATE_LABELS[traffic_state]
    else:
        status_text = "Flow: NO DETECTION"
        color = (0, 0, 255)
        label = "NO DETECTION"

    cv2.putText(annotated, status_text, (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
    cv2.putText(annotated, label, (10, 65),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 3)
    return annotated


def main():
    parser = argparse.ArgumentParser(description="Rotameter Flow Meter Reader")
    parser.add_argument("--model", default=MODEL_PATH, help="Path to YOLOv8 .pt model")
    parser.add_argument("--max-flow", type=float, default=MAX_FLOW_RATE,
                        help="Max flow rate on rotameter scale")
    parser.add_argument("--threshold", type=float, default=ZERO_FLOW_THRESHOLD,
                        help="Position ratio below which flow is considered zero")
    parser.add_argument("--rinse-gpm", type=float, default=RINSE_GPM,
                        help="GPM threshold for rinse/amber (default: 10)")
    parser.add_argument("--display", action="store_true",
                        help="Show live camera feed with overlay (requires monitor)")
    parser.add_argument("--resolution", default="640x480",
                        help="Camera resolution WxH (default: 640x480)")
    parser.add_argument("--interval", type=float, default=0.5,
                        help="Seconds between readings (default: 0.5)")
    args = parser.parse_args()

    res = tuple(int(x) for x in args.resolution.split("x"))

    print("=" * 55)
    print("  Rotameter Flow Meter Reader")
    print("  LUPW Flow Traffic Light System")
    print("=" * 55)

    # Load model
    model = YOLO(args.model)
    print(f"  [OK] Model loaded: {args.model}")

    # Setup GPIO
    setup_gpio()
    print(f"  [OK] GPIO ready (Green=GPIO{GREEN_LED_PIN}, Amber=GPIO{AMBER_LED_PIN}, Red=GPIO{RED_LED_PIN})")

    # Setup camera
    camera = setup_camera(resolution=res)
    print(f"  [OK] Camera ready ({res[0]}x{res[1]})")
    print("-" * 55)
    print("  Monitoring flow... Press Ctrl+C to stop.\n")

    try:
        while True:
            frame = camera.capture_array()
            results = model(frame, verbose=False)
            flow_rate, position_ratio = calculate_flow(results, args.max_flow)

            if flow_rate is not None:
                traffic_state = get_traffic_state(flow_rate)
                set_traffic_light(traffic_state)
                status = f"{STATE_LABELS[traffic_state]} ({traffic_state})"
                print(
                    f"\r  Flow: {flow_rate:6.1f} / {args.max_flow:.0f} GPM "
                    f"({position_ratio * 100:5.1f}%) | {status}       ",
                    end="", flush=True,
                )
            else:
                set_traffic_light("RED")
                print(
                    "\r  Flow: ------- (no detection) | NO DETECTION (RED)       ",
                    end="", flush=True,
                )

            # Optional live display
            if args.display:
                traffic_state = get_traffic_state(flow_rate) if flow_rate else "RED"
                overlay = draw_overlay(
                    frame, results, flow_rate, position_ratio,
                    traffic_state,
                )
                cv2.imshow("Rotameter Reader", overlay)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\n\n  Shutting down...")
    finally:
        set_traffic_light("RED")
        GPIO.cleanup()
        camera.stop()
        if args.display:
            cv2.destroyAllWindows()
        print("  Cleanup complete. Goodbye!")


if __name__ == "__main__":
    main()
