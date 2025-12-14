"""
Voice Trigger System with VAD, Google/Whisper Transcription,
and Firebot process checking.

This script listens for audio, performs voice activity detection,
transcribes recordings using either Google or the Whisper API,
and triggers a URL when certain trigger words are detected.
"""

import atexit
import sys
import threading
import time

# Import shared components and modules
from modules.config_manager import FIREBOT_REQUIRED
from modules.utils import ensure_stdout, cleanup_resources, cleanup_chunks, register_signal_handlers, state
from modules.process_monitor import check_firebot_status
from modules.audio_recorder import vad_based_recording, initialize_pyaudio

# Initial setup
ensure_stdout()
atexit.register(cleanup_resources)
register_signal_handlers()

def main():
    """
    Main entry point:
      - Performs cleanup.
      - Initializes PyAudio.
      - Checks Firebot process if required.
      - Starts the VAD-based recording in a separate thread.
      - Keeps the main thread alive until termination.
    """
    cleanup_chunks()
    print("Starting VAD-based voice trigger system...")

    # Initialize PyAudio
    initialize_pyaudio()

    # Check Firebot process at startup if required
    if FIREBOT_REQUIRED:
        if not check_firebot_status(state):
            print("Firebot process not found. Terminating...")
            cleanup_resources()
            sys.exit(0)

    # Start the recording thread
    record_thread = threading.Thread(target=vad_based_recording, daemon=True)
    record_thread.start()

    print("All systems running. Listening for trigger words...")

    try:
        while state.running:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nKeyboard interrupt received, shutting down...")
    finally:
        state.running = False
        print("Shutting down...")
        # Since this script often runs as a daemon or subprocess, 
        # ensure we exit cleanly.
        sys.exit(0)

if __name__ == "__main__":
    main()
