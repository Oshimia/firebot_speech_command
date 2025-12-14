import json
import os
import sys

def get_config_path():
    # First try the executable's directory for a config file
    executable_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
    # Go up one level if we are in modules/config_manager.py and not frozen
    if not getattr(sys, 'frozen', False):
         # current file is in modules/config_manager.py, we want project root
         executable_dir = os.path.dirname(executable_dir)
    
    config_path = os.path.join(executable_dir, "config.json")
    
    # If config doesn't exist in executable directory, check the bundled config
    if not os.path.exists(config_path) and getattr(sys, 'frozen', False):
        bundled_config = os.path.join(sys._MEIPASS, "config.json")
        if os.path.exists(bundled_config):
            # Copy the bundled config to the executable directory if possible
            try:
                import shutil
                shutil.copy2(bundled_config, config_path)
                print(f"Copied bundled config to: {config_path}")
                # Re-verify path after copy, though it should be same
            except Exception as e:
                print(f"Could not copy bundled config: {e}")
                config_path = bundled_config
    
    return config_path

CONFIG_FILE = get_config_path()

def load_config():
    """
    Load configuration from config.json.
    """
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
        except Exception as e:
            print(f"Error reading config.json at {CONFIG_FILE}:", e)
            config = {}
    else:
        # print(f"Config file not found at {CONFIG_FILE}, creating default config")
        config = {}
    
    print(f"DEBUG: config_manager loading from: {CONFIG_FILE}")
    print(f"DEBUG: Loaded TRIGGER_URL: {config.get('TRIGGER_URL', 'Not Set')}")
    
    # Migration: Check for legacy config and migrate to "triggers" list
    if "triggers" not in config:
        if "trigger_words" in config and config["trigger_words"]:
            print("DEBUG: Migrating legacy trigger_words to new 'triggers' format.")
            legacy_rule = {
                "phrases": config["trigger_words"],
                "url": config.get("TRIGGER_URL", "YOUR_URL_HERE"),
                "cooldown": float(config.get("URL_CALL_COOLDOWN", 2.0))
            }
            config["triggers"] = [legacy_rule]
        else:
            config["triggers"] = []

    # Defaults
    config.setdefault("triggers", [])
    config.setdefault("program_path", "")
    config.setdefault("auto_launch", False)
    # Legacy defaults (kept to prevent errors if referenced, but triggers list is primary)
    config.setdefault("trigger_words", []) 
    config.setdefault("TRIGGER_URL", "YOUR_URL_HERE")
    
    config.setdefault("WHISPER_API_URL", "https://api.openai.com/v1/audio/transcriptions")
    config.setdefault("OPENAI_API_KEY", "API_KEY_HERE")
    config.setdefault("TRANSCRIPT_FILE", "whisperTranscript.txt")
    config.setdefault("USE_GOOGLE_CLOUD", False)
    config.setdefault("GOOGLE_CLOUD_CREDENTIALS", "None")
    config.setdefault("FIREBOT_REQUIRED", True)
    config.setdefault("TRIGGER_COOLDOWN", 5.0)
    config.setdefault("URL_CALL_COOLDOWN", 2.0)
    config.setdefault("SILENCE_DURATION", 1.5)
    config.setdefault("GOOGLE_LANGUAGE", "en-US")
    config.setdefault("WHISPER_LANGUAGE", "en")
    config.setdefault("WHISPER_HISTORY_FILE", "whisperHistory.txt")
    config.setdefault("ENABLE_HISTORY", True)
    config.setdefault("HISTORY_LOG_PREFIX", "Oshimia")
    
    return config

def save_config(config):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=4)
        print(f"Config saved to {CONFIG_FILE}")
    except Exception as e:
        print(f"Error saving config.json to {CONFIG_FILE}:", e)

config = load_config()

# Configurable settings exposed as constants for compatibility
TRIGGER_WORDS = config.get("trigger_words", [])
TRIGGER_URL = config.get("TRIGGER_URL", "YOUR_URL_HERE")
WHISPER_API_URL = config.get("WHISPER_API_URL", "https://api.openai.com/v1/audio/transcriptions")
OPENAI_API_KEY = config.get("OPENAI_API_KEY", "API_KEY_HERE")
TRANSCRIPT_FILE = config.get("TRANSCRIPT_FILE", "whisperTranscript.txt")
USE_GOOGLE_CLOUD = config.get("USE_GOOGLE_CLOUD", False)
GOOGLE_CLOUD_CREDENTIALS = config.get("GOOGLE_CLOUD_CREDENTIALS", "None")
FIREBOT_REQUIRED = config.get("FIREBOT_REQUIRED", True)
TRIGGER_COOLDOWN = float(config.get("TRIGGER_COOLDOWN", 5.0))
URL_CALL_COOLDOWN = float(config.get("URL_CALL_COOLDOWN", 2.0))
SILENCE_DURATION = float(config.get("SILENCE_DURATION", 1.5))
GOOGLE_LANGUAGE = config.get("GOOGLE_LANGUAGE", "en-US")
WHISPER_LANGUAGE = config.get("WHISPER_LANGUAGE", "en")
WHISPER_HISTORY_FILE = config.get("WHISPER_HISTORY_FILE", "whisperHistory.txt")
ENABLE_HISTORY = config.get("ENABLE_HISTORY", True)
HISTORY_LOG_PREFIX = config.get("HISTORY_LOG_PREFIX", "Oshimia")
TRIGGERS = config.get("triggers", [])
FIREBOT_CHECK_INTERVAL = 5
