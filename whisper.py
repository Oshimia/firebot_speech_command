"""
Voice Trigger System with VAD, Google/Whisper Transcription,
and Firebot process checking.

This script listens for audio, performs voice activity detection,
transcribes recordings using either Google or the Whisper API,
and triggers a URL when certain trigger words are detected.
"""

import atexit
import collections
import glob
import json
import os
import signal
import sys
import threading
import time
import wave
from collections import deque
from queue import Queue

import psutil
import pyaudio
import requests
import speech_recognition as sr
import webrtcvad

# =============================================================================
# Setup for Logging and Output
# =============================================================================

def ensure_stdout():
    """
    Ensure that sys.stdout is available.
    If not, redirect output to a log file.
    """
    if sys.stdout is None:
        sys.stdout = open("output.log", "w")

ensure_stdout()


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

sys.stdout = Unbuffered(sys.stdout)

# =============================================================================
# Configuration Loading and Global Variables
# =============================================================================

def load_config():
    """
    Load configuration from config.json.
    """
    with open("config.json", "r") as config_file:
        return json.load(config_file)

config = load_config()

# Configurable settings from config.json
TRIGGER_WORDS = config.get("trigger_words", [])
TRIGGER_URL = config.get("TRIGGER_URL", "YOUR_URL_HERE")
WHISPER_API_URL = config.get("WHISPER_API_URL", "https://api.openai.com/v1/audio/transcriptions")
OPENAI_API_KEY = config.get("OPENAI_API_KEY", "API_KEY_HERE")
TRANSCRIPT_FILE = config.get("TRANSCRIPT_FILE", "whisperTranscript.txt")
USE_GOOGLE_CLOUD = config.get("USE_GOOGLE_CLOUD", False)
GOOGLE_CLOUD_CREDENTIALS = config.get("GOOGLE_CLOUD_CREDENTIALS", "None")
FIREBOT_REQUIRED = config.get("FIREBOT_REQUIRED", True)
running = config.get("running", True)
termination_triggered = config.get("termination_triggered", False)
TRIGGER_COOLDOWN = float(config.get("TRIGGER_COOLDOWN", 5.0))
URL_CALL_COOLDOWN = float(config.get("URL_CALL_COOLDOWN", 2.0))
SILENCE_DURATION = float(config.get("SILENCE_DURATION", 1.5))
last_url_call_time = int(config.get("last_url_call_time", 0))
FIREBOT_CHECK_INTERVAL = 5  # seconds

# Global instances and buffers
p_audio = None  # Global PyAudio instance
firebot_running = True
firebot_lock = threading.Lock()
last_firebot_check = 0
continuous_buffer = deque(maxlen=int(16000 * 5 / 480))  # 5 seconds buffer

# =============================================================================
# Cleanup Functions and Signal Handling
# =============================================================================

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


def cleanup_resources():
    """
    Clean up temporary files and terminate PyAudio if initialized.
    """
    global p_audio
    cleanup_chunks()
    if p_audio:
        p_audio.terminate()
        print("PyAudio terminated")

atexit.register(cleanup_resources)


def signal_handler(signum, frame):
    """
    Handle termination signals.
    """
    global running
    running = False
    print("\nTerminating")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# =============================================================================
# Firebot Process Checking
# =============================================================================

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


def check_firebot_status():
    """
    Periodically check if Firebot is running.
    If FIREBOT_REQUIRED is set and Firebot is not running, signal termination.
    """
    global firebot_running, running, last_firebot_check

    current_time = time.time()
    if current_time - last_firebot_check < FIREBOT_CHECK_INTERVAL:
        return firebot_running

    last_firebot_check = current_time

    with firebot_lock:
        if FIREBOT_REQUIRED:
            firebot_running = check_firebot()
            if not firebot_running:
                print("Firebot is no longer running. Terminating...")
                running = False

    return firebot_running

# =============================================================================
# PyAudio Initialization
# =============================================================================

def initialize_pyaudio():
    """
    Initialize and return the global PyAudio instance.
    Unreachable legacy code has been removed for clarity.
    """
    global p_audio
    if p_audio is None:
        p_audio = pyaudio.PyAudio()
    return p_audio

# =============================================================================
# Voice Activity Detection (VAD) and Recording
# =============================================================================

def vad_based_recording():
    """
    Start a VAD-based recording system:
      - Uses a prebuffer to capture 1 second before speech detection.
      - Starts recording upon detecting speech.
      - Stops recording after silence is detected or max duration is reached.
    """
    global running, continuous_buffer

    # Audio and VAD configuration
    RATE = 16000
    CHANNELS = 1
    FORMAT = pyaudio.paInt16
    FRAME_DURATION_MS = 30  # milliseconds per frame
    FRAME_SIZE = int(RATE * FRAME_DURATION_MS / 1000)
    PREBUFFER_DURATION = 1.0  # seconds
    PREBUFFER_FRAMES = int(PREBUFFER_DURATION * 1000 / FRAME_DURATION_MS)
    MAX_RECORDING_DURATION_MS = 30 * 1000  # 30 seconds

    # Set up VAD with moderate aggressiveness
    vad = webrtcvad.Vad(2)

    # Initialize PyAudio stream
    p_inst = initialize_pyaudio()
    stream = p_inst.open(format=FORMAT,
                         channels=CHANNELS,
                         rate=RATE,
                         input=True,
                         frames_per_buffer=FRAME_SIZE)

    prebuffer = deque(maxlen=PREBUFFER_FRAMES)

    # State variables for recording
    is_recording = False
    current_frames = []
    silent_frames = 0
    speech_frames = 0
    min_speech_frames = 3   # minimum consecutive speech frames to trigger recording
    max_silent_frames = int(SILENCE_DURATION * 1000 / FRAME_DURATION_MS)

    print("Optimized VAD-based recording started. Waiting for speech...")

    while running:
        # Check Firebot status periodically
        if not check_firebot_status() and FIREBOT_REQUIRED:
            break

        # Read the next audio frame
        frame = stream.read(FRAME_SIZE, exception_on_overflow=False)
        continuous_buffer.append(frame)
        prebuffer.append(frame)

        try:
            is_speech = vad.is_speech(frame, RATE)
        except Exception as e:
            print(f"VAD error: {e}")
            is_speech = False

        if not is_recording:
            if is_speech:
                speech_frames += 1
                if speech_frames >= min_speech_frames:
                    print("Speech detected, starting recording...")
                    is_recording = True
                    current_frames = list(prebuffer)
                    silent_frames = 0
                    speech_frames = 0
            else:
                speech_frames = 0
        else:
            current_frames.append(frame)
            silent_frames = silent_frames + 1 if not is_speech else 0

            # Stop recording if silence persists or max duration reached
            if (silent_frames >= max_silent_frames) or (len(current_frames) >= int(MAX_RECORDING_DURATION_MS / FRAME_DURATION_MS)):
                audio_data = (current_frames, CHANNELS, p_inst.get_sample_size(FORMAT), RATE)
                threading.Thread(
                    target=process_recording_async,
                    args=(audio_data,),
                    daemon=True
                ).start()
                is_recording = False
                current_frames = []
                silent_frames = 0
                speech_frames = 0

    stream.stop_stream()
    stream.close()
    print("VAD-based recording stopped.")

# =============================================================================
# Audio Processing and Transcription
# =============================================================================

def process_recording_async(audio_data):
    """
    Process a recording asynchronously:
      - Save the recording as a WAV file.
      - Perform initial transcription using Google (or Google Cloud if configured).
      - If trigger words are detected, optionally use Whisper API for detailed transcription.
      - Write the transcript to a file and trigger the URL.
    """
    global running, termination_triggered
    frames, channels, sample_width, rate = audio_data

    # Save audio to a unique WAV file
    filename = f"recording_{int(time.time() * 1000)}.wav"
    with wave.open(filename, 'wb') as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        wf.writeframes(b"".join(frames))
    print(f"Recording saved: {filename} ({len(frames)} frames, {len(frames) * 30 / 1000:.2f}s)")

    recognizer = sr.Recognizer()
    try:
        with sr.AudioFile(filename) as source:
            audio = recognizer.record(source)
        # Use Google or Google Cloud for initial transcription
        if USE_GOOGLE_CLOUD:
            google_transcript = recognizer.recognize_google_cloud(
                audio,
                credentials_json=GOOGLE_CLOUD_CREDENTIALS,
                preferred_phrases=TRIGGER_WORDS
            ).lower()
            print("Initial transcript (Google Cloud):", google_transcript)
        else:
            google_transcript = recognizer.recognize_google(audio).lower()
            print("Initial transcript (Google):", google_transcript)

        # Check for termination command in the Google transcript
        for word in TRIGGER_WORDS:
            if any(word in google_transcript for word in TRIGGER_WORDS) and ("terminate" in google_transcript or "determinate" in google_transcript):
                if not termination_triggered:
                    termination_triggered = True
                    print("Terminate command received from Google recognition")
                    running = False
                    return

        # Check if any trigger word exists in the transcript
        found_trigger = any(word in google_transcript for word in TRIGGER_WORDS)
        if found_trigger:
            print("Trigger word detected!")
            if OPENAI_API_KEY and OPENAI_API_KEY.strip() and OPENAI_API_KEY != "API_KEY_HERE":
                print("Using Whisper API for detailed transcription...")
                whisper_transcript = transcribe_audio(filename)
                if whisper_transcript:
                    for word in TRIGGER_WORDS:
                        if any(word in whisper_text for word in TRIGGER_WORDS) and ("terminate" in whisper_text or "determinate" in whisper_text):
                            if not termination_triggered:
                                termination_triggered = True
                                print("Terminate command received from Whisper recognition")
                                running = False
                                return
                    print("Detailed transcript (Whisper):", whisper_transcript)
                    try:
                        with open(TRANSCRIPT_FILE, "w", encoding="utf-8") as f:
                            f.write(whisper_transcript)
                        threading.Thread(target=trigger_url_call, daemon=True).start()
                        print("Triggered URL with Whisper transcript")
                    except Exception as e:
                        print(f"Error writing Whisper transcript: {e}")
                else:
                    print("Whisper transcription failed, using Google transcript")
                    try:
                        with open(TRANSCRIPT_FILE, "w", encoding="utf-8") as f:
                            f.write(google_transcript)
                        threading.Thread(target=trigger_url_call, daemon=True).start()
                        print("Triggered URL with Google transcript (Whisper fallback)")
                    except Exception as e:
                        print(f"Error writing Google transcript: {e}")
            else:
                print("No Whisper API key, using Google transcript")
                try:
                    with open(TRANSCRIPT_FILE, "w", encoding="utf-8") as f:
                        f.write(google_transcript)
                    threading.Thread(target=trigger_url_call, daemon=True).start()
                    print("Triggered URL with Google transcript")
                except Exception as e:
                    print(f"Error writing Google transcript: {e}")
        else:
            print("No trigger word found in transcript")

    except sr.UnknownValueError:
        print("No speech recognized in recording")
    except sr.RequestError as e:
        print("Google API error:", e)
    except Exception as e:
        print(f"Error processing recording: {e}")

    finally:
        try:
            os.remove(filename)
            print(f"Removed temporary file: {filename}")
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"Error removing file {filename}: {e}")


def transcribe_audio(filename):
    """
    Transcribe the given WAV file using the Whisper API if available,
    otherwise fall back to Google Speech Recognition.
    """
    if OPENAI_API_KEY and OPENAI_API_KEY.strip():
        try:
            with open(filename, 'rb') as audio_file:
                headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
                data = {"language": "en"}
                files = {
                    "file": audio_file,
                    "model": (None, "whisper-1")
                }
                response = requests.post(WHISPER_API_URL, headers=headers, files=files)
                response.raise_for_status()
                return response.json().get("text", "").strip()
        except Exception as e:
            print("Whisper transcription error:", e)
            return None
    else:
        recognizer = sr.Recognizer()
        try:
            with sr.AudioFile(filename) as source:
                audio = recognizer.record(source)
            transcript = recognizer.recognize_google(audio).lower()
            return transcript
        except sr.UnknownValueError:
            print("Google Speech Recognition could not understand audio")
            return None
        except sr.RequestError as e:
            print("Error with Google Speech Recognition service:", e)
            return None

# =============================================================================
# Trigger URL Call
# =============================================================================

def trigger_url_call():
    """
    Call the trigger URL in a separate thread.
    Throttles calls based on a cooldown period.
    """
    global last_url_call_time

    if termination_triggered:
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

# =============================================================================
# Main Execution Loop
# =============================================================================

def main():
    """
    Main entry point:
      - Performs cleanup.
      - Initializes PyAudio.
      - Checks Firebot process if required.
      - Starts the VAD-based recording in a separate thread.
      - Keeps the main thread alive until termination.
    """
    global running, p_audio
    cleanup_chunks()
    print("Starting VAD-based voice trigger system...")

    # Initialize PyAudio
    p_audio = initialize_pyaudio()

    # Check Firebot process at startup if required
    if FIREBOT_REQUIRED:
        if not check_firebot_status():
            print("Firebot process not found. Terminating...")
            cleanup_resources()
            sys.exit(0)

    # Start the recording thread
    record_thread = threading.Thread(target=vad_based_recording, daemon=True)
    record_thread.start()

    print("All systems running. Listening for trigger words...")

    try:
        while running:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nKeyboard interrupt received, shutting down...")
    finally:
        running = False
        print("Shutting down...")
        sys.exit(0)


if __name__ == "__main__":
    main()
