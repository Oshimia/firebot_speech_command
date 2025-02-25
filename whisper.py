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

# --- Load configuration from config.json ---
def load_config():
    with open("config.json", "r") as config_file:
        return json.load(config_file)

config = load_config()

# Global settings loaded from config.json
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
TRIGGER_COOLDOWN = config.get("TRIGGER_COOLDOWN", 5.0)
URL_CALL_COOLDOWN = config.get("URL_CALL_COOLDOWN", 2.0)
OVERLAP_SECONDS = config.get("OVERLAP_SECONDS", 3.0)
RECORDER_TRANSITION_DELAY = config.get("RECORDER_TRANSITION_DELAY", 0.2)
SILENCE_DURATION = config.get("SILENCE_DURATION", 1.5)
last_url_call_time = config.get("last_url_call_time", 0)

# --- End of config loading ---

# Create a queue for audio chunks
audio_queue = Queue()

# Create a buffer to store the last few seconds of audio continuously
continuous_buffer = deque(maxlen=int(16000 * 5 / 480))  # 5 seconds at 16kHz with 30ms frames

# --- Unified Trigger Tracker ---
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
            
            # Check similarity with recent utterances
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

# Initialize the unified trigger tracker using the config cooldown
trigger_tracker = TriggerTracker(cooldown=TRIGGER_COOLDOWN)

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

def signal_handler(signum, frame):
    global running
    running = False
    print("\nTerminating")
    cleanup_chunks()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def check_firebot():
    """Check if Firebot process is running (case-insensitive)."""
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

def record_audio_dynamic(prebuffer=None, max_duration=30, silence_duration=SILENCE_DURATION, frame_duration_ms=30, aggressiveness=3, return_frames=False):
    global running
    
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

def process_trigger(transcript, source_filename, source_type="main"):
    global running, termination_triggered
    
    if any(f"{word} terminate" in transcript for word in TRIGGER_WORDS):
        if not termination_triggered:
            termination_triggered = True
            print(f"Terminate command received from {source_type}")
            running = False
        return
        
    if any(word in transcript for word in TRIGGER_WORDS):
        detected_words = [word for word in TRIGGER_WORDS if word in transcript]
        if not detected_words:
            return
            
        trigger_word = detected_words[0]
        print(f"Trigger '{trigger_word}' detected in {source_type}! Checking if duplicate...")
        
        if trigger_tracker.should_process(transcript):
            print(f"Processing new trigger from {source_type}")
            whisper_transcript = transcribe_audio(source_filename)
            if whisper_transcript:
                print(f"Whisper transcript from {source_type}:", whisper_transcript)
                try:
                    with open(TRANSCRIPT_FILE, "w", encoding="utf-8") as f:
                        f.write(whisper_transcript)
                    trigger_url_call()
                except Exception as e:
                    print(f"Error writing transcript: {e}")
        else:
            print(f"Trigger from {source_type} deemed duplicate, ignoring")

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
            wf.setsampwidth(2)
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
            print(f"Buffer monitor error: {e}")
        
        try:
            os.remove(temp_filename)
        except Exception:
            pass

def dual_continuous_recording():
    FRAME_DURATION_MS = 30
    frames_per_sec = int(1000 / FRAME_DURATION_MS)
    overlap_frame_count = int(frames_per_sec * OVERLAP_SECONDS)  # Cast to int here

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

def transcribe_audio(filename):
    try:
        with open(filename, 'rb') as audio_file:
            headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
            data = {
                "language": "en"
            }
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

def trigger_url_call():
    global last_url_call_time
    if termination_triggered:
        print("Terminate command active, skipping URL call")
        return
        
    current_time = time.time()
    if current_time - last_url_call_time <= URL_CALL_COOLDOWN:
        print("URL call attempted within cooldown period, ignoring")
        return
        
    try:
        response = requests.get(TRIGGER_URL)
        print("Trigger response:", response.text)
        last_url_call_time = current_time
    except Exception as e:
        print("Error executing trigger:", e)

def main():
    global running
    cleanup_chunks()
    print("Starting improved voice trigger system with robust duplicate prevention...")
    
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
