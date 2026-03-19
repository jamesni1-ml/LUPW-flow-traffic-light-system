#!/usr/bin/env python3
"""
Rotameter Flow Meter Reader — Monitor Display Mode (v4)

Alternative to the GPIO traffic light setup. Uses the Raspberry Pi's
HDMI output to show a fullscreen traffic light display on a monitor.

Same detection and calibration logic as inference.py, but displays
the state on-screen instead of driving physical LEDs.

Display shows:
  - Large colour indicator matching the traffic light state
  - Flow position percentage
  - State label:
      GREEN  → "ONLINE"
      BLUE   → "UPW RINSE (25 GPM)"
      AMBER  → "LUPW RINSE (10 GPM)"
      RED    → "OFFLINE"
  - Live camera feed (small inset)

Hardware:
  - Raspberry Pi 4 (HDMI connected to monitor)
  - Raspberry Pi Camera Module 2

Dependencies:
  ultralytics, opencv-python, numpy, picamera2
  (No RPi.GPIO needed)
"""

import argparse
import csv
import time
from datetime import datetime

import cv2
import numpy as np
from ultralytics import YOLO
from picamera2 import Picamera2

# ── Calibration Defaults ────────────────────────────────────────────
ZERO_POS = 0.05
RINSE1_POS = 0.22
RINSE2_POS = 0.45

# ── Model Configuration ─────────────────────────────────────────────
MODEL_PATH = "best.pt"
CONFIDENCE_THRESHOLD = 0.5

# ── YOLO Class IDs ──────────────────────────────────────────────────
CLASS_TUBE = 0
CLASS_FLOAT = 1

# ── Debounce ────────────────────────────────────────────────────────
DEBOUNCE_COUNT = 3

# ── Display Configuration ───────────────────────────────────────────
DISPLAY_WIDTH = 1280
DISPLAY_HEIGHT = 720

# Colours in BGR for OpenCV
STATE_CONFIG = {
    "GREEN": {
        "colour": (0, 200, 0),
        "label": "ONLINE",
        "text_colour": (255, 255, 255),
    },
    "BLUE": {
        "colour": (200, 100, 0),
        "label": "UPW RINSE (25 GPM)",
        "text_colour": (255, 255, 255),
    },
    "AMBER": {
        "colour": (0, 191, 255),
        "label": "LUPW RINSE (10 GPM)",
        "text_colour": (0, 0, 0),
    },
    "RED": {
        "colour": (0, 0, 200),
        "label": "OFFLINE",
        "text_colour": (255, 255, 255),
    },
}


def setup_camera(resolution=(640, 480)):
    """Initialize the Raspberry Pi Camera Module 2."""
    picam2 = Picamera2()
    config = picam2.create_preview_configuration(
        main={"size": resolution, "format": "RGB888"}
    )
    picam2.configure(config)
    picam2.start()
    time.sleep(2)
    return picam2


def get_traffic_state(position_ratio, zero_pos, rinse1_pos, rinse2_pos):
    """Determine traffic light state from float position ratio."""
    if position_ratio <= zero_pos:
        return "RED"
    elif position_ratio <= rinse1_pos:
        return "AMBER"
    elif position_ratio <= rinse2_pos:
        return "BLUE"
    else:
        return "GREEN"


def calculate_position(results, conf_threshold):
    """Calculate the float's position ratio from YOLOv8 detections."""
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

    tube_top = tube_box[0][1]
    tube_bottom = tube_box[0][3]
    float_top_y = float_box[0][1]
    tube_height = tube_bottom - tube_top

    if tube_height <= 0:
        return None

    position_ratio = (tube_bottom - float_top_y) / tube_height
    return max(0.0, min(1.0, position_ratio))


def draw_display(frame, results, position_ratio, state, display_size):
    """
    Build the fullscreen monitor display.

    Layout:
      ┌─────────────────────────────────────┐
      │                                     │
      │         STATE LABEL (large)         │
      │                                     │
      │       Position: XX.X%               │
      │                                     │
      │   ┌──────────┐                      │
      │   │  camera   │                     │
      │   │   feed    │                     │
      │   └──────────┘                      │
      └─────────────────────────────────────┘
    """
    dw, dh = display_size
    config = STATE_CONFIG.get(state, STATE_CONFIG["RED"])
    bg_colour = config["colour"]
    text_colour = config["text_colour"]
    label = config["label"]

    # Fill background with state colour
    display = np.full((dh, dw, 3), bg_colour, dtype=np.uint8)

    # ── State label (large, centered) ───────────────────────────────
    font = cv2.FONT_HERSHEY_SIMPLEX
    label_scale = 2.5 if len(label) < 12 else 1.8
    label_thickness = 5
    (tw, th), _ = cv2.getTextSize(label, font, label_scale, label_thickness)
    label_x = (dw - tw) // 2
    label_y = int(dh * 0.30)
    cv2.putText(display, label, (label_x, label_y),
                font, label_scale, text_colour, label_thickness, cv2.LINE_AA)

    # ── Position percentage ─────────────────────────────────────────
    if position_ratio is not None:
        pos_text = f"Position: {position_ratio * 100:.1f}%"
    else:
        pos_text = "NO DETECTION"
    pos_scale = 1.5
    pos_thickness = 3
    (pw, ph), _ = cv2.getTextSize(pos_text, font, pos_scale, pos_thickness)
    pos_x = (dw - pw) // 2
    pos_y = label_y + th + 60
    cv2.putText(display, pos_text, (pos_x, pos_y),
                font, pos_scale, text_colour, pos_thickness, cv2.LINE_AA)

    # ── Camera feed inset (bottom-left) ─────────────────────────────
    if frame is not None:
        cam_h, cam_w = frame.shape[:2]
        # Scale camera feed to fit in bottom-left area
        inset_h = int(dh * 0.40)
        inset_w = int(inset_h * cam_w / cam_h)
        if inset_w > int(dw * 0.45):
            inset_w = int(dw * 0.45)
            inset_h = int(inset_w * cam_h / cam_w)

        # Draw detection boxes on the camera feed
        annotated = results[0].plot() if results is not None else frame.copy()
        annotated_bgr = cv2.cvtColor(annotated, cv2.COLOR_RGB2BGR)
        cam_resized = cv2.resize(annotated_bgr, (inset_w, inset_h))

        # Position: centered horizontally, near bottom
        margin = 20
        inset_x = (dw - inset_w) // 2
        inset_y = dh - inset_h - margin

        # Border around camera feed
        cv2.rectangle(display,
                      (inset_x - 3, inset_y - 3),
                      (inset_x + inset_w + 2, inset_y + inset_h + 2),
                      text_colour, 3)
        display[inset_y:inset_y + inset_h,
                inset_x:inset_x + inset_w] = cam_resized

    return display


def main():
    parser = argparse.ArgumentParser(
        description="Rotameter Flow Meter Reader — Monitor Display Mode")
    parser.add_argument("--model", default=MODEL_PATH,
                        help="Path to YOLOv8 .pt model")
    parser.add_argument("--zero-pos", type=float, default=ZERO_POS,
                        help="Position ratio for no flow / RED (default: 0.05)")
    parser.add_argument("--rinse1-pos", type=float, default=RINSE1_POS,
                        help="Position ratio for rinse 1 / AMBER (default: 0.22)")
    parser.add_argument("--rinse2-pos", type=float, default=RINSE2_POS,
                        help="Position ratio for rinse 2 / BLUE (default: 0.45)")
    parser.add_argument("--confidence", type=float, default=CONFIDENCE_THRESHOLD,
                        help="Minimum detection confidence (default: 0.5)")
    parser.add_argument("--resolution", default="640x480",
                        help="Camera resolution WxH (default: 640x480)")
    parser.add_argument("--display-size", default=f"{DISPLAY_WIDTH}x{DISPLAY_HEIGHT}",
                        help="Monitor display resolution (default: 1280x720)")
    parser.add_argument("--fullscreen", action="store_true",
                        help="Run in fullscreen mode")
    parser.add_argument("--interval", type=float, default=0.5,
                        help="Seconds between readings (default: 0.5)")
    parser.add_argument("--log", default="flow_log.csv",
                        help="CSV log file path (default: flow_log.csv)")
    parser.add_argument("--calibrate", action="store_true",
                        help="Run in calibration mode (shows live position ratio)")
    args = parser.parse_args()

    cam_res = tuple(int(x) for x in args.resolution.split("x"))
    disp_res = tuple(int(x) for x in args.display_size.split("x"))

    print("=" * 60)
    print("  Rotameter Flow Meter Reader")
    print("  LUPW Flow Traffic Light System (v4)")
    print("  ** Monitor Display Mode **")
    print("=" * 60)

    # Load model
    model = YOLO(args.model)
    print(f"  [OK] Model loaded: {args.model}")

    # Setup camera
    camera = setup_camera(resolution=cam_res)
    print(f"  [OK] Camera ready ({cam_res[0]}x{cam_res[1]})")
    print(f"  [OK] Display: {disp_res[0]}x{disp_res[1]}"
          f"{' (fullscreen)' if args.fullscreen else ''}")
    print(f"  [OK] Thresholds: zero={args.zero_pos:.2f}, "
          f"rinse1={args.rinse1_pos:.2f}, rinse2={args.rinse2_pos:.2f}")

    # Create display window
    window_name = "LUPW Flow Monitor"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    if args.fullscreen:
        cv2.setWindowProperty(window_name, cv2.WND_PROP_FULLSCREEN,
                              cv2.WINDOW_FULLSCREEN)
    else:
        cv2.resizeWindow(window_name, disp_res[0], disp_res[1])

    # ── Calibration Mode ────────────────────────────────────────────
    if args.calibrate:
        print("-" * 60)
        print("  CALIBRATION MODE")
        print("  Note the position ratio at:")
        print("    - 0 GPM (no flow)   → use as --zero-pos")
        print("    - 10 GPM (rinse 1)  → use as --rinse1-pos")
        print("    - 25 GPM (rinse 2)  → use as --rinse2-pos")
        print("  Press 'q' or Ctrl+C to stop.\n")

        try:
            while True:
                frame = camera.capture_array()
                results = model(frame, verbose=False)
                position_ratio = calculate_position(results, args.confidence)

                state = get_traffic_state(
                    position_ratio or 0.0,
                    args.zero_pos, args.rinse1_pos, args.rinse2_pos)
                display = draw_display(
                    frame, results, position_ratio, state, disp_res)

                if position_ratio is not None:
                    # Add calibration overlay
                    cal_text = f"CALIBRATION  |  Position: {position_ratio:.4f} ({position_ratio * 100:.1f}%)"
                    cv2.putText(display, cal_text, (20, disp_res[1] - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                                (255, 255, 255), 2, cv2.LINE_AA)
                    print(f"\r  Position ratio: {position_ratio:.4f} "
                          f"({position_ratio * 100:.1f}%)    ",
                          end="", flush=True)
                else:
                    print("\r  NO DETECTION                         ",
                          end="", flush=True)

                cv2.imshow(window_name, display)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n\n  Calibration ended.")
        finally:
            camera.stop()
            cv2.destroyAllWindows()
        return

    # ── Normal Monitoring Mode ──────────────────────────────────────
    print("-" * 60)
    print("  Monitoring flow... Press 'q' or Ctrl+C to stop.\n")

    current_state = "RED"
    pending_state = "RED"
    debounce_counter = 0

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
                    args.rinse1_pos, args.rinse2_pos)

                # Debounce
                if new_state == pending_state:
                    debounce_counter += 1
                else:
                    pending_state = new_state
                    debounce_counter = 1

                if debounce_counter >= DEBOUNCE_COUNT and current_state != pending_state:
                    current_state = pending_state

                # Log
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                log_writer.writerow([
                    now,
                    f"{position_ratio * 100:.1f}",
                    current_state,
                ])

                print(
                    f"\r  Position: {position_ratio * 100:5.1f}% | {current_state:6s}",
                    end="", flush=True)
            else:
                print("\r  NO DETECTION                         ",
                      end="", flush=True)

            # Draw and show display
            display = draw_display(
                frame, results, position_ratio, current_state, disp_res)
            cv2.imshow(window_name, display)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\n\n  Shutting down...")
    finally:
        camera.stop()
        log_file.close()
        cv2.destroyAllWindows()
        print(f"  Log saved to {args.log}")
        print("  Goodbye!")


if __name__ == "__main__":
    main()
