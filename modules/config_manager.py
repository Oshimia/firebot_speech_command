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
    config_file_path = CONFIG_FILE
    default_config = {
        "triggers": [],
        "program_path": "",
        "auto_launch": False,
        "trigger_words": [],
        "TRIGGER_URL": "YOUR_URL_HERE",
        "WHISPER_API_URL": "https://api.openai.com/v1/audio/transcriptions",
        "OPENAI_API_KEY": "API_KEY_HERE",
        "TRANSCRIPT_FILE": "whisperTranscript.txt",
        "USE_GOOGLE_CLOUD": False,
        "GOOGLE_CLOUD_CREDENTIALS": "None",
        "FIREBOT_REQUIRED": True,
        "TRIGGER_COOLDOWN": 5.0,
        "URL_CALL_COOLDOWN": 2.0,
        "SILENCE_DURATION": 1.5,
        "GOOGLE_LANGUAGE": "en-US",
        "WHISPER_LANGUAGE": "en",
        "WHISPER_HISTORY_FILE": "whisperHistory.txt",
        "ENABLE_HISTORY": True,
        "HISTORY_LOG_PREFIX": "Oshimia",
        "REQUIRED_PROCESS_NAME": "firebot"
    }

    if not os.path.exists(config_file_path):
        print(f"INFO: {config_file_path} not found. Creating a default one.")
        try:
            with open(config_file_path, "w", encoding="utf-8") as cf: json.dump(default_config, cf, indent=4)
            print(f"Created a default {config_file_path}. Please edit it with your settings and API keys.")
        except Exception as e: print(f"CRITICAL: Could not create default {config_file_path}: {e}. Exiting."); sys.exit(1)
        print("Please configure config.json and restart the script."); sys.exit(0)
    
    try:
        with open(config_file_path, "r", encoding="utf-8") as config_file:
            config = json.load(config_file)
            
            # --- Auto-Migration Logic ---
            # 1. Migrate legacy trigger_words to new triggers list
            if "triggers" not in config:
                config["triggers"] = []
                # Only migrate if old keys exist
                legacy_words = config.get("trigger_words", [])
                legacy_url = config.get("TRIGGER_URL", "")
                
                if legacy_words or legacy_url:
                    print(f"DEBUG: Migrating legacy trigger_words to new 'triggers' format.")
                    new_rule = {
                        "phrases": legacy_words if legacy_words else ["computer"],
                        "url": legacy_url,
                        "cooldown": float(config.get("URL_CALL_COOLDOWN", 2.0))
                    }
                    config["triggers"].append(new_rule)
                    # We don't remove the old keys to avoid breaking generic get() calls elsewhere immediately,
                    # but the new system will prioritize 'triggers'.
                    # Optimally, we save the migrated config back immediately?
                    # For now, let's just use it in memory. If user saves via GUI, it persists.
            
            # 2. Add defaults if missing (for new fields)
            for key, value in default_config.items():
                config.setdefault(key, value)

            return config

    except json.JSONDecodeError as e: print(f"CRITICAL: Error decoding {config_file_path}: {e}. Exiting."); sys.exit(1)
    except Exception as e: print(f"CRITICAL: Could not read {config_file_path}: {e}. Exiting."); sys.exit(1)

def save_config(config):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=4)
        print(f"Config saved to {CONFIG_FILE}")
    except Exception as e:
        print(f"Error saving config.json to {CONFIG_FILE}:", e)

config = load_config()

# Configurable settings exposed as constants for compatibility
TRIGGER_WORDS = config.get("trigger_words", ["computer"])
TRIGGER_URL = config.get("TRIGGER_URL", "")
WHISPER_API_URL = config.get("WHISPER_API_URL", "https://api.openai.com/v1/audio/transcriptions")
OPENAI_API_KEY = config.get("OPENAI_API_KEY", "")
TRANSCRIPT_FILE = config.get("TRANSCRIPT_FILE", "whisperTranscript.txt")
WHISPER_HISTORY_FILE = config.get("WHISPER_HISTORY_FILE", "whisperHistory.txt")
ENABLE_HISTORY = config.get("ENABLE_HISTORY", True)
HISTORY_LOG_PREFIX = config.get("HISTORY_LOG_PREFIX", "")
USE_GOOGLE_CLOUD = config.get("USE_GOOGLE_CLOUD", False)
GOOGLE_CLOUD_CREDENTIALS = config.get("GOOGLE_CLOUD_CREDENTIALS", "")
FIREBOT_REQUIRED = config.get("FIREBOT_REQUIRED", False)
REQUIRED_PROCESS_NAME = config.get("REQUIRED_PROCESS_NAME", "firebot")
URL_CALL_COOLDOWN = float(config.get("URL_CALL_COOLDOWN", 2.0))
SILENCE_DURATION = float(config.get("SILENCE_DURATION", 1.5))
GOOGLE_LANGUAGE = config.get("GOOGLE_LANGUAGE", "en-US")
WHISPER_LANGUAGE = config.get("WHISPER_LANGUAGE", "en")
TRIGGERS = config.get("triggers", [])
FIREBOT_CHECK_INTERVAL = 5
