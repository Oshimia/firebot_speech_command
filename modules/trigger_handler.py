import time
import requests
import threading
from modules.config_manager import TRIGGER_URL, URL_CALL_COOLDOWN
from modules.utils import state

print(f"DEBUG: trigger_handler.py loaded. TRIGGER_URL: {TRIGGER_URL}")

# State for trigger throttling
last_url_call_time = 0

def trigger_url_call():
    """
    Call the trigger URL in a separate thread.
    Throttles calls based on a cooldown period.
    """
    global last_url_call_time

    if state.termination_triggered:
        print("Terminate command active, skipping URL call")
        return

    current_time = time.time()
    if current_time - last_url_call_time <= URL_CALL_COOLDOWN:
        print("URL call attempted within cooldown period, ignoring")
        return

    try:
        response = requests.get(TRIGGER_URL, timeout=3)
        print("Trigger response:", response.text)
        last_url_call_time = current_time
    except requests.Timeout:
        print("Trigger URL request timed out")
        last_url_call_time = current_time
    except Exception as e:
        print("Error executing trigger:", e)
