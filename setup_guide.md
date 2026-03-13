# Hardware Setup Guide — LUPW Flow Traffic Light System (v3)

## Components Required

| Component | Quantity | Notes |
|---|---|---|
| Raspberry Pi 4 (2GB+ RAM) | 1 | 4GB recommended |
| Raspberry Pi Camera Module 2 | 1 | 12MP, CSI ribbon cable |
| Red LED (5mm, standard) | 1 | ~20mA, ~2V forward voltage |
| Amber/Yellow LED (5mm, standard) | 1 | ~20mA, ~2.1V forward voltage |
| Green LED (5mm, standard) | 1 | ~20mA, ~2.2V forward voltage |
| 150Ω resistor | 3 | Current limiting for LEDs (see calculation below) |
| 2N2222 NPN transistor | 3 | To drive LEDs over 5m cable |
| 1kΩ resistor | 3 | Base resistor for transistors |
| 2-core cable (0.75mm²) | ~18m | 3×5m runs + spare (e.g. speaker wire or bell wire) |
| Breadboard or strip board | 1 | For Pi-side circuit |
| Screw terminal block | 1 | To connect cables cleanly |
| MicroSD card (32GB+) | 1 | With Raspberry Pi OS |
| USB-C power supply (5V 3A) | 1 | Official Pi 4 PSU recommended |

---

## Traffic Light States

| State | Condition | LED | GPIO Pin |
|---|---|---|---|
| **RED** | No flow (0 GPM) | Red on, others off | GPIO 27 (Pin 13) |
| **AMBER** | Rinse flow (≤10 GPM) | Amber on, others off | GPIO 22 (Pin 15) |
| **GREEN** | Online flow (>10 GPM) | Green on, others off | GPIO 17 (Pin 11) |

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
 ►  GPIO22 (15) (16) GPIO23        ◄── AMBER LED pin (BCM 22)
        3V3 (17) (18) GPIO24
      GPIO10 (19) (20) GND
      GPIO9  (21) (22) GPIO25
      GPIO11 (23) (24) GPIO8
        GND (25) (26) GPIO7
      ...
```

### Important: 5-Metre Cable Run

The LEDs are mounted **~5 metres away** from the Raspberry Pi (Pi + camera sit at the rotameter, LEDs are visible from a distance). Over 5m of cable, the Pi's 3.3V GPIO cannot reliably drive LEDs directly due to voltage drop. **Use the transistor driver circuit below.**

### Recommended Wiring: Transistor Driver (5m cable)

Each LED is driven by an **NPN transistor (2N2222)** switching the Pi's **5V rail**, which has more headroom for the voltage drop over 5m.

**Circuit at the Pi (for EACH LED — repeat for green, amber, and red):**

```
                        Pi 5V (Pin 2 or 4)
                            │
                     ┌──────┘
                     │
              ───── 5m cable (wire 1) ─────►── [ 150Ω Resistor ] ──►── LED (+) anode
              │                                                         │
              │                                                      LED (-) cathode
              │                                                         │
              ───── 5m cable (wire 2) ─────►────────────────────────────┘
              │                                          (return to Pi)
              │
         ┌────┘
         │
    Collector (C)
         │
    [2N2222 NPN]
         │
    Emitter (E) ──►── GND
         │
    Base (B) ──[ 1kΩ ]──►── GPIO pin
```

**Green LED:**
```
  GPIO 17 (Pin 11) ──[ 1kΩ ]──► 2N2222 Base
                                 Emitter → GND (Pin 9)
                                 Collector → 5m cable → 150Ω → Green LED → 5m return → GND
  Pi 5V (Pin 2) ──────────────→ 5m cable (power wire)
```

**Amber LED:**
```
  GPIO 22 (Pin 15) ──[ 1kΩ ]──► 2N2222 Base
                                 Emitter → GND (Pin 20)
                                 Collector → 5m cable → 150Ω → Amber LED → 5m return → GND
  Pi 5V (Pin 2) ──────────────→ 5m cable (power wire)
```

**Red LED:**
```
  GPIO 27 (Pin 13) ──[ 1kΩ ]──► 2N2222 Base
                                 Emitter → GND (Pin 14)
                                 Collector → 5m cable → 150Ω → Red LED → 5m return → GND
  Pi 5V (Pin 4) ──────────────→ 5m cable (power wire)
```

### Resistor Calculation

```
Vsupply = 5V (Pi 5V rail)
Vdrop_cable ≈ 0.7V (10m round trip of 0.75mm² copper at 15mA)
Vdrop_transistor ≈ 0.2V (2N2222 Vce_sat)
Vled ≈ 2.0V (red) / 2.1V (amber) / 2.2V (green)
I_led = 15mA (bright enough for indicator)

Red:   R = (5V - 0.7V - 0.2V - 2.0V) / 0.015A = 140Ω → use 150Ω standard
Amber: R = (5V - 0.7V - 0.2V - 2.1V) / 0.015A = 133Ω → use 150Ω (fine)
Green: R = (5V - 0.7V - 0.2V - 2.2V) / 0.015A = 127Ω → use 150Ω (slightly dimmer)
```

### Alternative: Direct GPIO (short cable only)

If you later move the LEDs closer to the Pi (< 0.5m), you can skip the transistors:
```
  GPIO 17 (Pin 11) ── [ 150Ω ] ── Green LED (+)  ── GND (Pin 9)
  GPIO 22 (Pin 15) ── [ 150Ω ] ── Amber LED (+)  ── GND (Pin 20)
  GPIO 27 (Pin 13) ── [ 150Ω ] ── Red LED (+)    ── GND (Pin 14)
```
⚠️ This will NOT work reliably over 5m cable.

### Wiring Summary Table

| Signal | BCM GPIO | Physical Pin | Pi-Side Component | Cable | LED-Side |
|---|---|---|---|---|---|
| Green LED | GPIO 17 | Pin 11 | 1kΩ → 2N2222 base | 5m 2-core | 150Ω → Green LED → return |
| Amber LED | GPIO 22 | Pin 15 | 1kΩ → 2N2222 base | 5m 2-core | 150Ω → Amber LED → return |
| Red LED | GPIO 27 | Pin 13 | 1kΩ → 2N2222 base | 5m 2-core | 150Ω → Red LED → return |
| 5V Power | — | Pin 2 + Pin 4 | Transistor collector | Via cable | Powers LEDs |
| Ground | — | Pin 9, 14, 20 | Transistor emitter | Via return cable | LED cathode |

### Cable Tips for 5m Run

- Use **0.75mm² 2-core cable** (speaker wire, bell wire, or alarm cable all work)
- Each LED needs its own 2-core run: one wire for +5V, one for GND return
- That's **3 cables × 5m = 15m total cable** (plus spare)
- Solder connections at the LED end, or use screw terminals
- Keep the cable away from mains/high-voltage wiring to avoid interference
- Label your cables (green/amber/red) at both ends

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

After training on your WSL2 workstation (vision-ml environment), copy `best.pt` to the Pi:
```bash
# From your training machine:
scp runs/detect/rotameter/weights/best.pt pi@<PI_IP_ADDRESS>:~/lupw-project/best.pt

# Or use a USB drive
```

---

## Running the System

### Basic Usage (headless, no display)
```bash
cd ~/lupw-project
source ~/lupw-env/bin/activate
python3 inference.py --model best.pt --max-flow 100 --rinse-gpm 10
```

### With Live Display (requires monitor/VNC)
```bash
python3 inference.py --model best.pt --max-flow 100 --rinse-gpm 10 --display
```

### All Options
```bash
python3 inference.py \
    --model best.pt \
    --max-flow 100 \
    --rinse-gpm 10 \
    --threshold 0.02 \
    --confidence 0.5 \
    --resolution 640x480 \
    --interval 0.5 \
    --log flow_log.csv \
    --display
```

| Flag | Default | Description |
|---|---|---|
| `--model` | `best.pt` | Path to trained YOLOv8 model weights |
| `--max-flow` | `100.0` | Maximum flow reading on your rotameter scale |
| `--rinse-gpm` | `10.0` | Rinse/online threshold in GPM |
| `--threshold` | `0.02` | Position ratio below which flow = zero (2%) |
| `--confidence` | `0.5` | Minimum YOLOv8 detection confidence |
| `--resolution` | `640x480` | Camera capture resolution |
| `--interval` | `0.5` | Seconds between each reading |
| `--log` | `flow_log.csv` | CSV log file for all readings |
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
ExecStart=/home/pi/lupw-env/bin/python3 inference.py --model best.pt --max-flow 100 --rinse-gpm 10
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
| LEDs not lighting up | Verify polarity (long leg = anode = +). Check transistor wiring. Test with `python3 test_gpio.py`. |
| Only 2 LEDs work | Check the third transistor base resistor and GPIO pin connection. |
| Model runs slowly | Use 640x480 resolution. Consider exporting to TorchScript for faster inference. |
| "No detection" in output | Ensure camera is pointed at the rotameter. Check lighting conditions. May need more training data. |
| GPIO permission error | Run with `sudo` or add user to gpio group: `sudo usermod -aG gpio $USER` |
| Wrong light colour | Check `--rinse-gpm` threshold. Run `test_gpio.py` to verify which GPIO controls which LED. |

---
