# 🐱 AI Cat Window Controller

An intelligent cat detection system that automatically controls a motorized window based on cat presence and position, with Telegram bot integration for remote monitoring and control.

## 🌟 Features

- **Smart Cat Detection**: Uses Hailo AI accelerator for real-time cat detection
- **Position-Based Control**: Opens window only when cat is detected in specific area (left half)
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
  - Configurable detection zones
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
    'min_confidence': 0.7,              # Minimum detection confidence
    'required_detection_time': 10,      # Seconds before opening
    'required_no_detection_time': 3,    # Seconds before closing
    'left_boundary': 0.0,               # Left boundary (0% = left edge)
    'right_boundary': 0.5,              # Right boundary (50% = middle)
}
```

### Detection Zone

The system can be configured to detect cats in specific areas:
- `left_boundary: 0.0, right_boundary: 0.5` - Left half only (default)
- `left_boundary: 0.0, right_boundary: 1.0` - Full frame
- `left_boundary: 0.3, right_boundary: 0.7` - Center area only

## 🎮 Usage

### Start the System

```bash
cd /home/pi/hailo-rpi5-examples
source venv_hailo_rpi5_examples/bin/activate
python basic_pipelines/headless_detection.py --input /dev/video0
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

### Main Components

```
basic_pipelines/
├── cat_detector.py           # Main detection application
├── cat_config.py             # Configuration file
├── cat_window.py             # Window control script
├── window_controller.py      # Window controller class
├── telegram_base.py          # Telegram bot base with watchdog
├── telegram_handler.py       # Telegram message handler
├── telegram_commands.py      # Bot command handlers
├── telegram_notifications.py # Notification system
├── file_manager.py           # Image and file management
├── system_monitor.py         # System monitoring
└── headless_detection.py     # Headless detection pipeline
```

### Detection Flow

```
Camera → Hailo AI → Cat Detection → Position Check → Time Filter → Window Control
                                                    ↓
                                            Telegram Notification
                                                    ↓
                                              Image Capture
```

## 🔧 Advanced Features

### Watchdog System

The bot includes an intelligent watchdog that:
- Monitors connection health every 5 minutes
- Auto-restarts on disconnect (15-minute timeout)
- Updates heartbeat on successful operations
- Logs connection issues for debugging

### USB Auto-Recovery

If Arduino connection is lost, the system will:
1. Kill processes holding the port
2. Reset USB device (unbind/bind)
3. Retry connection up to 5 times
4. Wait with exponential backoff

### Detection Logic

- **Window Opens**: Cat detected in zone for 10+ seconds
- **Window Closes**: No cat detected for 3+ seconds
- **Images Captured**: All cats detected (any position)
- **Cooldown**: 30 seconds between captures

## 📊 Monitoring

### Logs

```bash
# Real-time log viewing
tail -f /tmp/cat_detector_output.log

# Detection log
tail -f basic_pipelines/cat_detector.log
```

### Status Files

- `cat_window_state.json` - Current window state
- `cats_database.json` - Detected cats database
- `system_stats.json` - System statistics

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