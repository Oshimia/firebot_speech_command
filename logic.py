import time
import threading
import subprocess
import sys
import wave
import requests
import pyaudio
import speech_recognition as sr
import psutil
import signal
import webrtcvad
import os
import atexit
import glob
import json
from queue import Queue
from collections import deque

# --- Unbuffered stdout Wrapper ---
class Unbuffered(object):
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

# --- CONFIGURATION & GLOBALS ---

# Default trigger words (will be overwritten if provided in config.json)
TRIGGER_WORDS = [
    "modbot",
    "mudbutt",
    "not but",
    "modbod",
    "mudblood",
    "mudbug",
    "mud ball",
    "mud bath",
    "mobot",
    "mudbox",
    "motherboard",
    "modot",
    "mud butt",
    "mud bog",
    "mud bot",
    "mudbone",
    "motorbike",
    "mothball",
    "not what",
    "motorboat",
    "modwot",
    "what about",
    "outboard",
    "how about",
    "not about",
    "muppet",
    "moderator",
    "motorized"
]

# Remove Whisper-specific variables
# TRIGGER_URL is no longer used since we trigger based on phrase mapping.
# Instead, URL mapping is loaded from config.json.
url_mapping = {}  # to be loaded from config.json

# Use Google Speech API if desired
USE_GOOGLE_CLOUD = False
GOOGLE_CLOUD_CREDENTIALS = None

# Set to True if the Firebot process must be running.
FIREBOT_REQUIRED = True

# Global control flags
running = True
termination_triggered = False

# Improved duplicate prevention using a unified trigger tracker
TRIGGER_COOLDOWN = 5  # seconds
class TriggerTracker:
    def __init__(self, cooldown=5):
        self.lock = threading.Lock()
        self.cooldown = cooldown
        self.last_trigger_time = 0
        self.recent_utterances = {}  # Store utterances with timestamps
        
    def should_process(self, utterance):
        current_time = time.time()
        with self.lock:
            if current_time - self.last_trigger_time < self.cooldown:
                print(f"Trigger attempted within global cooldown period ({self.cooldown}s), ignoring")
                return False
            
            # Clean up old utterances
            self.recent_utterances = {
                text: timestamp for text, timestamp in self.recent_utterances.items()
                if current_time - timestamp < self.cooldown * 2
            }
            
            # Check for similarity with recent utterances
            for text, timestamp in self.recent_utterances.items():
                if self._similarity_check(utterance, text) and current_time - timestamp < self.cooldown * 2:
                    print("Similar utterance detected within extended cooldown period, ignoring")
                    return False
            
            self.last_trigger_time = current_time
            self.recent_utterances[utterance] = current_time
            return True
    
    def _similarity_check(self, text1, text2):
        t1 = text1.lower().strip()
        t2 = text2.lower().strip()
        if t1 == t2:
            return True
        if t1 in t2 or t2 in t1:
            return True
        words1 = set(t1.split())
        words2 = set(t2.split())
        common_words = words1.intersection(words2)
        if len(common_words) / max(len(words1), len(words2)) > 0.7:
            return True
        return False

trigger_tracker = TriggerTracker(cooldown=TRIGGER_COOLDOWN)

# Audio recording parameters
OVERLAP_SECONDS = 3
RECORDER_TRANSITION_DELAY = 0.2
SILENCE_DURATION = 1.5

audio_queue = Queue()
continuous_buffer = deque(maxlen=int(16000 * 5 / 480))  # 5 seconds buffer

# Cleanup leftover audio chunk files on exit
def cleanup_chunks():
    # Look for both chunk files and buffer files
    patterns = ["chunk_*.wav", "buffer_check_*.wav"]
    for pattern in patterns:
        for f in glob.glob(pattern):
            try:
                os.remove(f)
                print(f"Deleted leftover file: {f}")
            except Exception as e:
                print(f"Error deleting {f}: {e}")

atexit.register(cleanup_chunks)

# Signal handling for graceful termination
def signal_handler(signum, frame):
    global running
    running = False
    print("\nTerminating")
    cleanup_chunks()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# --- CONFIG LOADING & URL TRIGGERING ---

def load_config():
    with open("config.json", "r") as config_file:
        return json.load(config_file)

def trigger_url(url):
    try:
        # You can use subprocess to call curl or simply use requests.get
        response = requests.get(url)
        print("Triggered URL response:", response.text)
    except Exception as e:
        print("Error triggering URL:", e)

# --- PROCESS CHECK ---

def check_firebot():
    for process in psutil.process_iter(['name']):
        try:
            proc_name = process.info['name']
            if proc_name and "firebot" in proc_name.lower():
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False

def stop_if_firebot_not_running():
    global running
    if FIREBOT_REQUIRED and not check_firebot():
        print("Firebot is no longer running. Terminating...")
        running = False
        return True
    return False

# --- AUDIO RECORDING ---

def record_audio_dynamic(prebuffer=None, max_duration=30, silence_duration=SILENCE_DURATION, frame_duration_ms=30, aggressiveness=3, return_frames=False):
    RATE = 16000
    CHANNELS = 1
    FORMAT = pyaudio.paInt16
    FRAME_DURATION_MS = frame_duration_ms
    FRAME_SIZE = int(RATE * FRAME_DURATION_MS / 1000)
    vad = webrtcvad.Vad(aggressiveness)
    
    p_inst = pyaudio.PyAudio()
    stream = p_inst.open(format=FORMAT,
                         channels=CHANNELS,
                         rate=RATE,
                         input=True,
                         frames_per_buffer=FRAME_SIZE)
    
    print("Dynamic recording started...")
    frames = [] if prebuffer is None else list(prebuffer)
    silent_frames = 0
    max_silent_frames = int(silence_duration * 1000 / FRAME_DURATION_MS)
    total_frames = int(max_duration * 1000 / FRAME_DURATION_MS)
    frame_count = 0
    speech_detected = False

    while frame_count < total_frames and running:
        if stop_if_firebot_not_running():
            break
        
        frame = stream.read(FRAME_SIZE)
        frames.append(frame)
        continuous_buffer.append(frame)
        frame_count += 1
        
        is_speech = vad.is_speech(frame, RATE)
        if is_speech:
            speech_detected = True
            silent_frames = 0
        else:
            silent_frames += 1
        
        if silent_frames >= max_silent_frames and frame_count > int(0.5 * (1000 / FRAME_DURATION_MS)) and speech_detected:
            print("Silence detected. Ending recording.")
            break

    stream.stop_stream()
    stream.close()
    p_inst.terminate()

    filename = f"chunk_{int(time.time() * 1000)}.wav"
    with wave.open(filename, 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(p_inst.get_sample_size(FORMAT))
        wf.setframerate(RATE)
        wf.writeframes(b"".join(frames))
    
    if return_frames:
        return filename, frames
    else:
        return filename

def continuous_buffer_monitor():
    FRAME_DURATION_MS = 30
    BUFFER_CHECK_INTERVAL = 1.0
    recognizer = sr.Recognizer()
    
    while running:
        if stop_if_firebot_not_running():
            break
            
        time.sleep(BUFFER_CHECK_INTERVAL)
        
        if len(continuous_buffer) < 16:
            continue
            
        temp_filename = f"buffer_check_{int(time.time() * 1000)}.wav"
        with wave.open(temp_filename, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit audio
            wf.setframerate(16000)
            wf.writeframes(b"".join(continuous_buffer))
        
        try:
            with sr.AudioFile(temp_filename) as source:
                audio = recognizer.record(source)
            try:
                if USE_GOOGLE_CLOUD:
                    transcript = recognizer.recognize_google_cloud(
                        audio,
                        credentials_json=GOOGLE_CLOUD_CREDENTIALS,
                        preferred_phrases=TRIGGER_WORDS
                    ).lower()
                else:
                    transcript = recognizer.recognize_google(audio).lower()
                
                if any(word in transcript for word in TRIGGER_WORDS) or any(f"{word} terminate" in transcript for word in TRIGGER_WORDS):
                    print("Buffer monitor detected potential trigger in:", transcript)
                    process_trigger(transcript, temp_filename, source_type="buffer_monitor")
            except sr.UnknownValueError:
                pass
            except sr.RequestError:
                pass
        except Exception as e:
            print("Buffer monitor error:", e)
        
        try:
            os.remove(temp_filename)
        except Exception:
            pass

def dual_continuous_recording():
    FRAME_DURATION_MS = 30
    frames_per_sec = int(1000 / FRAME_DURATION_MS)
    overlap_frame_count = frames_per_sec * OVERLAP_SECONDS
    
    prebuffer_1 = None
    prebuffer_2 = None
    recorder_1_active = True
    recorder_lock = threading.Lock()
    
    while running:
        if stop_if_firebot_not_running():
            break
            
        if recorder_1_active:
            def start_recorder_2():
                nonlocal prebuffer_2, recorder_1_active
                time.sleep(RECORDER_TRANSITION_DELAY)
                with recorder_lock:
                    if recorder_1_active:
                        result = record_audio_dynamic(prebuffer=prebuffer_2, return_frames=True)
                        if result:
                            filename, frames = result
                            audio_queue.put(filename)
                            prebuffer_2 = frames[-overlap_frame_count:] if len(frames) >= overlap_frame_count else frames
                            recorder_1_active = False
            threading.Thread(target=start_recorder_2, daemon=True).start()
            
            with recorder_lock:
                if recorder_1_active:
                    result = record_audio_dynamic(prebuffer=prebuffer_1, return_frames=True)
                    if result:
                        filename, frames = result
                        audio_queue.put(filename)
                        prebuffer_1 = frames[-overlap_frame_count:] if len(frames) >= overlap_frame_count else frames
        else:
            def start_recorder_1():
                nonlocal prebuffer_1, recorder_1_active
                time.sleep(RECORDER_TRANSITION_DELAY)
                with recorder_lock:
                    if not recorder_1_active:
                        result = record_audio_dynamic(prebuffer=prebuffer_1, return_frames=True)
                        if result:
                            filename, frames = result
                            audio_queue.put(filename)
                            prebuffer_1 = frames[-overlap_frame_count:] if len(frames) >= overlap_frame_count else frames
                            recorder_1_active = True
            threading.Thread(target=start_recorder_1, daemon=True).start()
            
            with recorder_lock:
                if not recorder_1_active:
                    result = record_audio_dynamic(prebuffer=prebuffer_2, return_frames=True)
                    if result:
                        filename, frames = result
                        audio_queue.put(filename)
                        prebuffer_2 = frames[-overlap_frame_count:] if len(frames) >= overlap_frame_count else frames
                        
        time.sleep(0.1)

def process_audio_chunk():
    recognizer = sr.Recognizer()
    while running:
        if stop_if_firebot_not_running():
            break
            
        try:
            filename = audio_queue.get(timeout=1)
        except Exception:
            continue

        try:
            with sr.AudioFile(filename) as source:
                audio = recognizer.record(source)
        except Exception as e:
            print("Error loading audio file:", e)
            try:
                os.remove(filename)
            except:
                pass
            audio_queue.task_done()
            continue

        try:
            if USE_GOOGLE_CLOUD:
                transcript = recognizer.recognize_google_cloud(
                    audio,
                    credentials_json=GOOGLE_CLOUD_CREDENTIALS,
                    preferred_phrases=TRIGGER_WORDS
                ).lower()
                print("Transcript (Cloud):", transcript)
            else:
                transcript = recognizer.recognize_google(audio).lower()
                print("Transcript:", transcript)
                
            if any(word in transcript for word in TRIGGER_WORDS) or any(f"{word} terminate" in transcript for word in TRIGGER_WORDS):
                process_trigger(transcript, filename, source_type="main_recorder")
                
        except sr.UnknownValueError:
            pass
        except sr.RequestError as e:
            print("Google API error:", e)

        try:
            os.remove(filename)
        except Exception as e:
            print("Error removing file:", e)
        audio_queue.task_done()

# --- TRIGGER PROCESSING (NO WHISPER) ---

def process_trigger(transcript, source_filename, source_type="main"):
    """
    Process a detected trigger by extracting the phrase after the trigger word.
    If the phrase matches a mapping (from config.json), trigger the corresponding URL.
    Also handles termination commands.
    """
    global running, termination_triggered
    
    for trigger in TRIGGER_WORDS:
        if trigger in transcript:
            index = transcript.find(trigger) + len(trigger)
            phrase = transcript[index:].strip()
            print(f"Trigger '{trigger}' detected in {source_type} with phrase: '{phrase}'")
            
            if not trigger_tracker.should_process(transcript):
                print(f"Duplicate trigger detected from {source_type}, ignoring.")
                return
            
            if phrase.lower() == "terminate":
                termination_triggered = True
                print("Terminate command received. Shutting down.")
                running = False
                return
            
            if phrase:
                if phrase in url_mapping:
                    url = url_mapping[phrase]
                    trigger_url(url)
                else:
                    print(f"No action defined for phrase: '{phrase}'")
            else:
                print(f"No phrase detected after trigger word '{trigger}'.")
            return  # Process only the first matching trigger

# --- MAIN LOOP ---

def main():
    global running, url_mapping, TRIGGER_WORDS
    
    cleanup_chunks()
    print("Starting improved voice trigger system (without Whisper)...")
    
    # Load configuration (expects a config.json with "trigger_words" and "url_mapping")
    try:
        config = load_config()
        url_mapping = config.get("url_mapping", {})
        if "trigger_words" in config:
            TRIGGER_WORDS = config["trigger_words"]
        print("Configuration loaded.")
    except Exception as e:
        print("Error loading config.json:", e)
        sys.exit(1)
    
    if FIREBOT_REQUIRED and not check_firebot():
        print("Firebot process not found. Terminating...")
        sys.exit(0)
    
    record_thread = threading.Thread(target=dual_continuous_recording, daemon=True)
    record_thread.start()
    
    process_thread = threading.Thread(target=process_audio_chunk, daemon=True)
    process_thread.start()
    
    buffer_monitor_thread = threading.Thread(target=continuous_buffer_monitor, daemon=True)
    buffer_monitor_thread.start()
    
    print("All systems running. Listening for trigger words...")
    
    try:
        while running:
            if stop_if_firebot_not_running():
                break
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nKeyboard interrupt received, shutting down...")
    finally:
        running = False
        print("Shutting down...")
        cleanup_chunks()
        sys.exit(0)

if __name__ == "__main__":
    main()
