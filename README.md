# 🐱 AI Cat Window Controller

An intelligent cat detection system that automatically controls a motorized window based on cat presence and position, with Telegram bot integration for remote monitoring and control.

## 🌟 Features

- **Smart Cat Detection**: Uses Hailo AI accelerator with YOLO11m (2024) for highly accurate real-time cat detection
- **Automatic Window Control**: Opens window when cat is detected
- **Telegram Integration**:
  - Real-time notifications with photos
  - Remote window control
  - Group chat support for family sharing
  - System status monitoring
- **Robust Connection Management**:
  - Automatic bot reconnection with watchdog
  - USB serial auto-recovery for Arduino
  - Network error handling with exponential backoff
- **Advanced Features**:
  - Window lock/unlock mechanism
  - Adaptive confidence thresholds
  - Image capture with cooldown
  - Manual/automatic mode switching

## 📋 Requirements

### Hardware
- Raspberry Pi 5
- Hailo-8L AI accelerator
- USB camera
- Arduino (ATMEGA2560) with servo motors
- USB serial connection (`/dev/ttyUSB0`)

### Software
- Python 3.11+
- Hailo SDK for Raspberry Pi
- Required Python packages (see `requirements.txt`)

## 🚀 Installation

1. **Clone the repository**
```bash
git clone <repository-url>
cd hailo-rpi5-examples/basic_pipelines
```

2. **Create and activate virtual environment**
```bash
python3 -m venv venv
source venv/bin/activate
```

3. **Install dependencies**
```bash
pip install -r requirements.txt
```

4. **Configure Telegram Bot**
   - Create a bot via [@BotFather](https://t.me/botfather)
   - Get your chat ID or group ID
   - Edit `cat_config.py` with your credentials

5. **Setup Arduino**
   - Upload the provided Arduino sketch to ATMEGA2560
   - Connect via USB (should appear as `/dev/ttyUSB0`)
   - Create symlink: `sudo ln -s /dev/ttyUSB0 /dev/ttyCAT`

## ⚙️ Configuration

Edit `cat_config.py` to customize:

```python
# Telegram Configuration
TELEGRAM_CONFIG = {
    'token': 'YOUR_BOT_TOKEN',
    'chat_id': 'YOUR_CHAT_ID',  # Use negative number for groups
}

# Window Configuration
WINDOW_CONFIG = {
    'closed_angle': 77,   # Closed position angle
    'open_angle': 130,    # Open position angle
}

# Detection Configuration
DETECTION_CONFIG = {
    'min_confidence_closed': 0.7,       # Confidence when window closed
    'min_confidence_open': 0.5,         # Lower threshold when open
    'required_detection_time': 10,      # Seconds before opening
    'required_no_detection_time': 3,    # Seconds before closing
}
```

## 🤖 AI Model

The system uses **YOLO11m** (November 2024) for object detection:
- **Model**: YOLO11 Medium (33 MB HEF file)
- **Accuracy**: High precision with minimal false positives
- **Performance**: ~23 FPS on Raspberry Pi 5 with Hailo-8
- **Version**: Compiled from Hailo Model Zoo v2.14.0

**Alternative Models** (available in `resources/`):
- `yolov11n.hef` (7 MB) - Faster but less accurate
- `yolov11s.hef` (18 MB) - Balanced speed/accuracy
- `yolov8m.hef` (27 MB) - Previous version (2023)

To use a different model, modify the `--hef-path` argument in the startup script.

## 🎮 Usage

### Start the System

**IMPORTANT: The system starts automatically at boot via cron job**

The system uses:
- **Cron job**: `@reboot /home/pi/start-cat-window.sh`
- **Startup script**: `/home/pi/start-cat-window.sh`
- **Main application**: `headless_detection.py` (launched by startup script)

To start manually:
```bash
cd /home/pi/hailo-rpi5-examples
source venv_hailo_rpi5_examples/bin/activate
python basic_pipelines/headless_detection.py --input /dev/video0
```

Or use the startup script:
```bash
/home/pi/start-cat-window.sh
```

### Telegram Bot Commands

- `/start` - Initialize bot and get welcome message
- `/status` - Get current window status
- `/open` - Manually open window
- `/close` - Manually close window
- `/auto` - Enable automatic mode
- `/manual` - Disable automatic mode
- `/lock` - Lock the window
- `/unlock` - Unlock the window

### Manual Window Control (CLI)

```bash
python3 cat_window.py <command>

Commands:
  apri              - Unlock and fully open window
  chiudi            - Close and lock window
  finestra <angle>  - Set window angle (77-135 degrees)
  serratura <angle> - Set lock angle (0-90 degrees)
  sblocca           - Unlock window
  blocca            - Lock window
```

## 🏗️ Architecture

### Main Components (Current System)

The system currently in production uses these files:

```
basic_pipelines/
├── headless_detection.py      # ⭐ Main entry point (CURRENT)
├── cat_detector_callback.py   # Detection logic and window control
├── cat_config.py              # Configuration file
├── cat_window.py              # CLI tool for manual window control
├── window_controller.py       # Window/lock servo controller
├── telegram_base.py           # Telegram bot base with watchdog
├── telegram_handler.py        # Telegram message handler
├── telegram_commands.py       # Bot command handlers
├── telegram_notifications.py  # Notification system
└── backup_unused/             # Alternative implementations (not used)
    ├── cat_detector.py        # Alternative main with ROI detection
    ├── file_manager.py        # File management (alternative system)
    ├── system_monitor.py      # System monitoring (alternative system)
    └── README_BACKUP.md       # Documentation for backup files
```

**Note**: The system is launched by `/home/pi/start-cat-window.sh` via cron `@reboot`.

### System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  headless_detection.py                   │
│                    (Main Process)                        │
└───────────────┬─────────────────────────┬────────────────┘
                │                         │
        ┌───────▼─────────┐      ┌────────▼─────────┐
        │ cat_detector_   │      │  telegram_       │
        │   callback.py   │      │  handler.py      │
        │                 │      │                  │
        │ • Detection     │      │ • Bot commands   │
        │ • Time filter   │      │ • Notifications  │
        │ • Image capture │      │ • Watchdog       │
        └────────┬────────┘      └──────────────────┘
                 │
        ┌────────▼─────────┐
        │  window_         │
        │  controller.py   │
        │                  │
        │ • Servo control  │
        │ • Lock control   │
        │ • State mgmt     │
        └──────────────────┘
```

### Detection Flow

```
Camera → GStreamer → Hailo AI → Cat Detection → Time Filter → Window Control
                                      ↓                            ↓
                              Image Capture                 Telegram Notify
                                      ↓
                               Telegram Photo
```

## 🔧 Advanced Features

### Watchdog System

**Multi-Layer Protection Against System Freeze:**

1. **Hardware Watchdog** (BCM2835):
   - Timeout: 10 seconds
   - Automatically resets Raspberry Pi if kernel hangs
   - Configured via `/etc/watchdog.conf`

2. **Kernel Hung Task Detection**:
   - Detects tasks blocked for >120 seconds
   - Triggers kernel panic → automatic reboot
   - Configured via `/etc/sysctl.d/99-watchdog-panic.conf`

3. **Hailo Health Monitor**:
   - Runs every 5 minutes via cron
   - Logs temperature, load, detection process status
   - Log file: `/var/log/hailo-monitor.log`
   - Alerts if temperature >80°C

4. **Telegram Bot Watchdog**:
   - Monitors connection health every 5 minutes
   - Auto-restarts on disconnect (15-minute timeout)
   - Updates heartbeat on successful operations
   - Logs connection issues for debugging

**Note**: These protections prevent Hailo driver freezes from permanently locking the system.

### USB Auto-Recovery

If Arduino connection is lost, the system will:
1. Kill processes holding the port
2. Reset USB device (unbind/bind)
3. Retry connection up to 5 times
4. Wait with exponential backoff

### Detection Logic

- **Position-Based Control**:
  - Left side of frame (<50%): Opens window for cat entry
  - Right side of frame (≥50%): Photo only, no window action
- **Temporal Persistence** (5 seconds):
  - Ignores brief detection gaps (missing frames)
  - Maintains position tracking across temporary occlusions
- **Window Opens**: Cat detected on LEFT continuously for 10+ seconds AND no cats on right
- **Window Closes**: No qualifying cat detected for 3+ seconds
- **Adaptive Thresholds**:
  - Closed window: 0.8 confidence (high to reduce false positives)
  - Open window: 0.7 confidence (slightly lower when cat already detected)
- **Photo Capture**:
  - All cats detected (left OR right) above 0.8 confidence
  - Includes position data (center X coordinate 0-100%)
  - Cooldown: 30 seconds between captures
  - Caption: confidence, position (LEFT/RIGHT %), total cats count

## 📊 Monitoring

### Logs

```bash
# Real-time log viewing
tail -f /tmp/cat_detector_output.log

# Detection log
tail -f basic_pipelines/cat_detector.log

# Hailo health monitor
tail -f /var/log/hailo-monitor.log
```

### Status Files

- `cat_window_state.json` - Current window state
- `cats_database.json` - Detected cats database
- `system_stats.json` - System statistics

### Hailo Health Monitoring

Monitor Hailo module temperature and system health:
```bash
# Check current temperature
cat /sys/class/hwmon/hwmon*/temp*_input | awk '{print $1/1000 "°C"}'

# View health log
tail -20 /var/log/hailo-monitor.log

# Manual monitoring test
/home/pi/hailo-monitor.sh
```

## 🐛 Troubleshooting

### Arduino Not Responding

```bash
# Manual USB reset
sudo usbresetusb /dev/ttyUSB0

# Or reboot
sudo reboot
```

### Bot Not Responding

Check logs for watchdog activity:
```bash
grep "Watchdog" /tmp/cat_detector_output.log
```

### Detection Issues

- Adjust `min_confidence` in `cat_config.py`
- Check camera with: `v4l2-ctl --list-devices`
- Verify Hailo model is loaded

### System Freeze / Hailo Lockup

If the system becomes completely unresponsive (SSH not working):

**Cause**: Hailo PCIe driver can occasionally cause kernel deadlock

**Protection Mechanisms** (automatically enabled):
1. **Hardware watchdog**: Resets system after 10s of kernel hang
2. **Hung task detector**: Triggers panic if tasks blocked >120s
3. **Health monitor**: Logs Hailo temperature every 5 minutes

**Check after reboot**:
```bash
# View last boot time
uptime

# Check Hailo health history
tail -50 /var/log/hailo-monitor.log

# Verify watchdog is running
sudo systemctl status watchdog

# Check kernel panic settings
sysctl kernel.hung_task_panic kernel.panic
```

**Manual intervention** (if system is still responsive):
```bash
# Check Hailo temperature
cat /sys/class/hwmon/hwmon*/temp*_input | awk '{print $1/1000 "°C"}'

# Restart detection process
sudo pkill -f headless_detection
/home/pi/start-cat-window.sh

# Force Hailo driver reload (last resort)
sudo rmmod hailo_pci && sudo modprobe hailo_pci
```

## 📦 Backup

Before major changes, create a backup:

```bash
tar -czf cat_detector_backup_$(date +%Y%m%d).tar.gz \
  basic_pipelines/cat_*.py \
  basic_pipelines/telegram_*.py \
  basic_pipelines/window_controller.py \
  cat_classifier.h5 \
  cats_database.json \
  cat_window_state.json
```

## 🤝 Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## 📝 License

This project is licensed under the MIT License - see LICENSE file for details.

## 🙏 Acknowledgments

- Hailo AI for the excellent accelerator
- python-telegram-bot for Telegram integration
- pymodbus for serial communication

## 👨‍👩‍👧‍👦 Family-Friendly Features

This project was designed for families to:
- Monitor their cats remotely
- Share updates in a family group chat
- Control the window from anywhere
- Keep cats safe while parents are away (perfect for university students missing their pets!)

---

**Made with ❤️ for cats and their families**