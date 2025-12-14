import time
import requests
import threading
from modules.config_manager import TRIGGER_URL, URL_CALL_COOLDOWN
from modules.utils import state

print(f"DEBUG: trigger_handler.py loaded. TRIGGER_URL: {TRIGGER_URL}")

# State for trigger throttling (Dictionary: url -> timestamp)
last_call_times = {}

def trigger_url_call(target_url=TRIGGER_URL, cooldown=URL_CALL_COOLDOWN):
    """
    Call the target URL in a separate thread.
    Throttles calls based on a cooldown period specific to that URL.
    """
    if not target_url or target_url == "YOUR_URL_HERE":
        return

    if state.termination_triggered:
        print("Terminate command active, skipping URL call")
        return

    current_time = time.time()
    last_time = last_call_times.get(target_url, 0)

    if current_time - last_time <= cooldown:
        print(f"URL call to {target_url} attempted within cooldown period, ignoring")
        return

    try:
        response = requests.get(target_url, timeout=3)
        print(f"Trigger response ({target_url}):", response.text)
        last_call_times[target_url] = current_time
    except requests.Timeout:
        print(f"Trigger URL request timed out: {target_url}")
        last_call_times[target_url] = current_time
    except Exception as e:
        print(f"Error executing trigger {target_url}:", e)
