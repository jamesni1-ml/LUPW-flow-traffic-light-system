# Hardware Setup Guide — LUPW Flow Traffic Light System

## Components Required

| Component | Quantity | Notes |
|---|---|---|
| Raspberry Pi 4 (2GB+ RAM) | 1 | 4GB recommended for YOLOv8 |
| Raspberry Pi Camera Module 2 | 1 | 12MP, CSI ribbon cable |
| Red LED (5mm or traffic light module) | 1 | Standard through-hole LED |
| Green LED (5mm or traffic light module) | 1 | Standard through-hole LED |
| 330Ω resistor | 2 | Current limiting for LEDs |
| Breadboard | 1 | For prototyping |
| Jumper wires (M-F) | 4+ | GPIO to breadboard |
| MicroSD card (32GB+) | 1 | With Raspberry Pi OS |
| USB-C power supply (5V 3A) | 1 | Official Pi 4 PSU recommended |

---

## GPIO Wiring Diagram

```
Raspberry Pi 4 GPIO Header (BCM numbering)
─────────────────────────────────────────────

        3V3  (1) (2)  5V
      GPIO2  (3) (4)  5V
      GPIO3  (5) (6)  GND
      GPIO4  (7) (8)  GPIO14
        GND  (9) (10) GPIO15
 ►  GPIO17 (11) (12) GPIO18        ◄── GREEN LED pin (BCM 17)
 ►  GPIO27 (13) (14) GND           ◄── RED LED pin (BCM 27)
      GPIO22 (15) (16) GPIO23
        3V3 (17) (18) GPIO24
      GPIO10 (19) (20) GND
      GPIO9  (21) (22) GPIO25
      GPIO11 (23) (24) GPIO8
        GND (25) (26) GPIO7
      ...
```

### Wiring Connections

**Green LED (flow ON indicator):**
```
  GPIO 17 (Pin 11) ──►──[ 330Ω Resistor ]──►──[ Green LED + (long leg) ]
                                                [ Green LED - (short leg) ]──►── GND (Pin 9)
```

**Red LED (flow OFF / zero flow indicator):**
```
  GPIO 27 (Pin 13) ──►──[ 330Ω Resistor ]──►──[ Red LED + (long leg) ]
                                                [ Red LED - (short leg) ]──►── GND (Pin 14)
```

### Wiring Summary Table

| Signal | BCM GPIO | Physical Pin | Connects To |
|---|---|---|---|
| Green LED | GPIO 17 | Pin 11 | 330Ω → Green LED anode → GND |
| Red LED | GPIO 27 | Pin 13 | 330Ω → Red LED anode → GND |
| Ground (Green) | — | Pin 9 | Green LED cathode |
| Ground (Red) | — | Pin 14 | Red LED cathode |

> **Note:** If using a traffic light LED module (3-in-1 tower), it typically has GND, R, Y, G pins.
> Connect R → GPIO 27, G → GPIO 17, GND → any Pi GND pin.
> The module usually has built-in resistors — check its datasheet.

---

## Camera Setup

### 1. Connect the Camera

1. Power off the Pi
2. Locate the CSI camera port (between the HDMI and audio jack)
3. Lift the plastic clip on the CSI connector
4. Insert the ribbon cable with the blue side facing the USB/Ethernet ports
5. Press the clip back down to secure

### 2. Enable the Camera

On Raspberry Pi OS (Bookworm / Bullseye):
```bash
# Camera is enabled by default on newer Pi OS
# Verify with:
libcamera-hello --timeout 5000

# If you see a 5-second preview, the camera works
```

If using legacy camera stack:
```bash
sudo raspi-config
# Navigate to: Interface Options → Camera → Enable
sudo reboot
```

### 3. Test the Camera
```bash
# Take a test photo
libcamera-jpeg -o test.jpg --width 640 --height 480

# Or test with Python
python3 -c "
from picamera2 import Picamera2
cam = Picamera2()
cam.start()
import time; time.sleep(2)
cam.capture_file('test.jpg')
cam.stop()
print('Saved test.jpg')
"
```

---

## Raspberry Pi Software Setup

### 1. Install Raspberry Pi OS

Use **Raspberry Pi OS (64-bit)** — the 64-bit version is required for best YOLOv8 performance.

Download from: https://www.raspberrypi.com/software/

### 2. Update the System
```bash
sudo apt update && sudo apt upgrade -y
```

### 3. Install Python Dependencies
```bash
# Install pip if not present
sudo apt install -y python3-pip python3-venv

# Create a virtual environment
python3 -m venv ~/lupw-env
source ~/lupw-env/bin/activate

# Install picamera2 (system package, link into venv)
sudo apt install -y python3-picamera2

# Install project dependencies
pip install -r requirements_pi.txt
```

### 4. Transfer the Trained Model

After training on your PC/workstation, copy `best.pt` to the Pi:
```bash
# From your training machine:
scp runs/detect/rotameter_model/weights/best.pt pi@<PI_IP_ADDRESS>:~/lupw-project/best.pt

# Or use a USB drive
```

---

## Running the System

### Basic Usage (headless, no display)
```bash
cd ~/lupw-project
source ~/lupw-env/bin/activate
python3 inference.py --model best.pt --max-flow 100
```

### With Live Display (requires monitor/VNC)
```bash
python3 inference.py --model best.pt --max-flow 100 --display
```

### All Options
```bash
python3 inference.py \
    --model best.pt \
    --max-flow 100 \
    --threshold 0.05 \
    --resolution 640x480 \
    --interval 0.5 \
    --display
```

| Flag | Default | Description |
|---|---|---|
| `--model` | `best.pt` | Path to trained YOLOv8 model weights |
| `--max-flow` | `100.0` | Maximum flow reading on your rotameter scale |
| `--threshold` | `0.05` | Position ratio below which flow = zero (0.05 = 5%) |
| `--resolution` | `640x480` | Camera capture resolution |
| `--interval` | `0.5` | Seconds between each reading |
| `--display` | off | Show live annotated camera feed |

### Run on Boot (systemd service)

Create `/etc/systemd/system/lupw-flow.service`:
```ini
[Unit]
Description=LUPW Flow Traffic Light System
After=multi-user.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/lupw-project
Environment="PATH=/home/pi/lupw-env/bin:/usr/bin"
ExecStart=/home/pi/lupw-env/bin/python3 inference.py --model best.pt --max-flow 100
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable it:
```bash
sudo systemctl enable lupw-flow.service
sudo systemctl start lupw-flow.service

# Check status
sudo systemctl status lupw-flow.service
```

---

## Troubleshooting

| Issue | Solution |
|---|---|
| Camera not detected | Check ribbon cable orientation and seating. Run `libcamera-hello` to test. |
| LEDs not lighting up | Verify polarity (long leg = anode = +). Check resistor connections. Test with `gpio -g write 17 1`. |
| Model runs slowly | Use 640x480 resolution. Consider exporting to NCNN format for faster Pi inference. |
| "No detection" in output | Ensure camera is pointed at the rotameter. Check lighting conditions. May need more training data. |
| GPIO permission error | Run with `sudo` or add user to gpio group: `sudo usermod -aG gpio $USER` |

---

## Camera Mounting Tips

- Mount the camera **directly facing** the rotameter tube, perpendicular to the scale
- Ensure **consistent lighting** — avoid direct sunlight causing reflections on the glass tube
- Keep the camera at a fixed distance matching your training images (~15-30cm typical)
- Use a 3D-printed or simple bracket to hold the camera steady
