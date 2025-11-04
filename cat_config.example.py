# cat_config.example.py

"""
Configuration template for the AI Cat Window Controller.
Copy this file to cat_config.py and fill in your credentials.
"""

# Telegram Configuration
TELEGRAM_CONFIG = {
    # Get your bot token from @BotFather on Telegram
    'token': 'YOUR_BOT_TOKEN_HERE',  # Example: '1234567890:ABCdefGHIjklMNOpqrsTUVwxyz'

    # Your chat ID or group chat ID (negative number for groups)
    # Get it from @userinfobot or forward a message from your group to it
    'chat_id': 'YOUR_CHAT_ID_HERE',  # Example: '123456789' or '-1001234567890'
}

# Window Configuration
WINDOW_CONFIG = {
    'closed_angle': 77,  # Servo angle when window is closed
    'open_angle': 130,   # Servo angle when window is open
}

# Detection Configuration
DETECTION_CONFIG = {
    'min_confidence': 0.7,              # Minimum confidence for cat detection (0.0-1.0)
    'required_detection_time': 10,      # Seconds cat must be present before opening
    'required_no_detection_time': 3,    # Seconds without detection before closing
    'detection_filter_window': 3,       # Time window for detection filtering (seconds)
    'left_boundary': 0.0,              # Left boundary of detection zone (0.0 = left edge)
    'right_boundary': 0.5,             # Right boundary of detection zone (1.0 = right edge)
}

# Image Capture Configuration
IMAGE_CONFIG = {
    'save_dir': 'detected_cats',        # Directory to save captured images
    'capture_cooldown': 30,            # Seconds between image captures
    'capture_confidence': 0.7,         # Minimum confidence to capture image
}