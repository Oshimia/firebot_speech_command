import glob
import os
import signal
import sys
import threading
import time

class Unbuffered:
    """
    Wrapper to flush sys.stdout immediately.
    """
    def __init__(self, stream):
        self.stream = stream

    def write(self, data):
        self.stream.write(data)
        self.stream.flush()

    def writelines(self, datas):
        self.stream.writelines(datas)
        self.stream.flush()

    def __getattr__(self, attr):
        return getattr(self.stream, attr)

def ensure_stdout():
    """
    Ensure that sys.stdout is available.
    If not, redirect output to a log file.
    """
    if sys.stdout is None:
        sys.stdout = open("output.log", "w")
    sys.stdout = Unbuffered(sys.stdout)

def get_base_dir():
    """
    Get the application's base directory (works in both script and exe mode)
    """
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS  # PyInstaller's temporary directory
    else:
        # If running as script, return the parent of the modules directory (project root)
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def cleanup_chunks():
    """
    Delete any leftover temporary audio files matching specific patterns.
    """
    patterns = ["chunk_*.wav", "extra_*.wav", "combined_*.wav", "transcript_*.wav", "recording_*.wav"]
    for pattern in patterns:
        for f in glob.glob(pattern):
            try:
                os.remove(f)
                print(f"Deleted leftover file: {f}")
            except Exception as e:
                print(f"Error deleting {f}: {e}")

class AppState:
    def __init__(self):
        self.running = True
        self.termination_triggered = False
        self.p_audio = None

state = AppState()

def cleanup_resources():
    """
    Clean up temporary files and terminate PyAudio if initialized.
    """
    cleanup_chunks()
    if state.p_audio:
        state.p_audio.terminate()
        print("PyAudio terminated")

def signal_handler(signum, frame):
    """
    Handle termination signals.
    """
    state.running = False
    print("\nTerminating")
    sys.exit(0)

def register_signal_handlers():
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
