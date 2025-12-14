import time
import psutil
import threading
from modules.config_manager import FIREBOT_REQUIRED, FIREBOT_CHECK_INTERVAL

# Global instances (module-level state)
firebot_running = True
firebot_lock = threading.Lock()
last_firebot_check = 0

def check_firebot():
    """
    Check if any running process has 'firebot' in its name.
    """
    for process in psutil.process_iter(['name']):
        try:
            proc_name = process.info['name']
            if proc_name and "firebot" in proc_name.lower():
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False

def check_firebot_status(running_state):
    """
    Periodically check if Firebot is running.
    If FIREBOT_REQUIRED is set and Firebot is not running, signal termination.
    
    Args:
        running_state: An object or scope with a 'running' attribute that can be set to False.
    """
    global firebot_running, last_firebot_check

    current_time = time.time()
    if current_time - last_firebot_check < FIREBOT_CHECK_INTERVAL:
        return firebot_running

    last_firebot_check = current_time

    with firebot_lock:
        if FIREBOT_REQUIRED:
            firebot_running = check_firebot()
            if not firebot_running:
                print("Firebot is no longer running. Terminating...")
                running_state.running = False

    return firebot_running
