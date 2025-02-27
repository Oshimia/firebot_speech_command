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

def ensure_stdout():
    # If no console is available (i.e., sys.stdout is None),
    # redirect output to a log file.
    if sys.stdout is None:
        sys.stdout = open("output.log", "w")

ensure_stdout()

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

def load_config():
    with open("config.json", "r") as config_file:
        return json.load(config_file)

config = load_config()

TRIGGER_WORDS = config.get("trigger_words", [])
TRIGGER_URL = config.get("TRIGGER_URL", "YOUR_URL_HERE")
WHISPER_API_URL = config.get("WHISPER_API_URL", "https://api.openai.com/v1/audio/transcriptions")
OPENAI_API_KEY = config.get("OPENAI_API_KEY", "API_KEY_HERE")
TRANSCRIPT_FILE = config.get("TRANSCRIPT_FILE", "whisperTranscript.txt")
USE_GOOGLE_CLOUD = config.get("USE_GOOGLE_CLOUD", False)
GOOGLE_CLOUD_CREDENTIALS = config.get("GOOGLE_CLOUD_CREDENTIALS", "None")
FIREBOT_REQUIRED = config.get("FIREBOT_REQUIRED", True)
MIN_EXTRA_RECORDING_SECONDS = float(config.get("MIN_EXTRA_RECORDING_SECONDS", 3))
running =config.get("running", True)
termination_triggered = config.get("termination_triggered", False)
TRIGGER_COOLDOWN = float(config.get("TRIGGER_COOLDOWN", 5.0))
URL_CALL_COOLDOWN = float(config.get("URL_CALL_COOLDOWN", 2.0))
OVERLAP_SECONDS = float(config.get("OVERLAP_SECONDS", 3.0))
RECORDER_TRANSITION_DELAY = float(config.get("RECORDER_TRANSITION_DELAY", 0.2))
SILENCE_DURATION = float(config.get("SILENCE_DURATION", 1.5))
last_url_call_time = int(config.get("last_url_call_time", 0))

audio_queue = Queue()

continuous_buffer = deque(maxlen=int(16000 * 5 / 480))

class TriggerTracker:
    def __init__(self, cooldown=5):
        self.lock = threading.Lock()
        self.cooldown = cooldown
        self.last_trigger_time = 0
        self.recent_utterances = {}
        
    def should_process(self, utterance):
        current_time = time.time()
        
        with self.lock:
            if current_time - self.last_trigger_time < self.cooldown:
                print(f"Trigger attempted within global cooldown period ({self.cooldown}s), ignoring")
                return False
            
            self.recent_utterances = {
                text: timestamp for text, timestamp in self.recent_utterances.items()
                if current_time - timestamp < self.cooldown * 2  # Keep a longer history for comparison
            }
            
            for text, timestamp in self.recent_utterances.items():
                if self._similarity_check(utterance, text) and current_time - timestamp < self.cooldown * 2:
                    print(f"Similar utterance detected within extended cooldown period, ignoring")
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

def cleanup_chunks():
    patterns = ["chunk_*.wav", "buffer_check_*.wav", "extra_*.wav", "combined_*.wav", "transcript_*.wav"]
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

def record_audio_dynamic(prebuffer=None, max_duration=30, silence_duration=SILENCE_DURATION, frame_duration_ms=30, aggressiveness=2, return_frames=False):
    global running
    
    RATE = 16000
    CHANNELS = 1
    FORMAT = pyaudio.paInt16
    FRAME_DURATION_MS = frame_duration_ms  # in ms
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

def record_extra_audio(min_duration):

    RATE = 16000
    CHANNELS = 1
    FORMAT = pyaudio.paInt16
    FRAME_DURATION_MS = 30
    FRAME_SIZE = int(RATE * FRAME_DURATION_MS / 1000)
    vad = webrtcvad.Vad(2)
    
    p_inst = pyaudio.PyAudio()
    sample_size = p_inst.get_sample_size(FORMAT)
    stream = p_inst.open(format=FORMAT,
                         channels=CHANNELS,
                         rate=RATE,
                         input=True,
                         frames_per_buffer=FRAME_SIZE)
    
    print("Extra recording started...")
    frames = []
    min_frames = int(min_duration * 1000 / FRAME_DURATION_MS)
    silent_frames = 0
    max_silent_frames = int(SILENCE_DURATION * 1000 / FRAME_DURATION_MS)
    frame_count = 0

    while True:
        frame = stream.read(FRAME_SIZE)
        frames.append(frame)
        frame_count += 1
        is_speech = vad.is_speech(frame, RATE)
        if not is_speech:
            silent_frames += 1
        else:
            silent_frames = 0
        if frame_count >= min_frames and silent_frames >= max_silent_frames:
            print("Extra recording: Silence detected after minimum duration.")
            break

    stream.stop_stream()
    stream.close()
    p_inst.terminate()

    extra_filename = f"extra_{int(time.time() * 1000)}.wav"
    with wave.open(extra_filename, 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(sample_size)
        wf.setframerate(RATE)
        wf.writeframes(b"".join(frames))
    
    return extra_filename

def combine_audio_files(file1, file2):
    """
    Combines two WAV files (file1 followed by file2) into one file.
    Returns the filename of the combined audio.
    """
    with wave.open(file1, 'rb') as wf1:
        params = wf1.getparams()
        frames1 = wf1.readframes(wf1.getnframes())
    with wave.open(file2, 'rb') as wf2:
        frames2 = wf2.readframes(wf2.getnframes())
    combined_filename = f"combined_{int(time.time() * 1000)}.wav"
    with wave.open(combined_filename, 'wb') as wf:
        wf.setparams(params)
        wf.writeframes(frames1 + frames2)
    # Clean up the individual files
    try:
        os.remove(file1)
        os.remove(file2)
    except Exception as e:
        print("Error cleaning up temporary files:", e)
    return combined_filename

def record_audio_with_prebuffer(prebuffer, max_duration=30, silence_duration=SILENCE_DURATION, frame_duration_ms=30, aggressiveness=2):
    """
    Records audio starting with an extended prebuffer already included.
    This function will append new audio to the prebuffer until a period of silence is detected.
    """
    RATE = 16000
    CHANNELS = 1
    FORMAT = pyaudio.paInt16
    FRAME_SIZE = int(RATE * frame_duration_ms / 1000)
    vad = webrtcvad.Vad(aggressiveness)
    
    p_inst = pyaudio.PyAudio()
    stream = p_inst.open(format=FORMAT,
                         channels=CHANNELS,
                         rate=RATE,
                         input=True,
                         frames_per_buffer=FRAME_SIZE)
    
    # Start with the provided prebuffer frames
    frames = list(prebuffer) if prebuffer is not None else []
    silent_frames = 0
    max_silent_frames = int(silence_duration * 1000 / frame_duration_ms)
    frame_count = 0
    speech_detected = False

    while frame_count < int(max_duration * 1000 / frame_duration_ms) and running:
        frame = stream.read(FRAME_SIZE)
        frames.append(frame)
        frame_count += 1
        
        if vad.is_speech(frame, RATE):
            speech_detected = True
            silent_frames = 0
        else:
            silent_frames += 1
        
        # Stop recording if enough silence is detected (and we've already detected speech)
        if frame_count > int(0.5 * (1000 / frame_duration_ms)) and speech_detected and silent_frames >= max_silent_frames:
            break

    stream.stop_stream()
    stream.close()
    p_inst.terminate()
    
    # Write the combined frames to a new WAV file
    filename = f"transcript_{int(time.time() * 1000)}.wav"
    with wave.open(filename, 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(p_inst.get_sample_size(FORMAT))
        wf.setframerate(RATE)
        wf.writeframes(b"".join(frames))
    
    return filename

def process_trigger(transcript, source_filename, source_type="main"):
    global running, termination_triggered

    # Immediately check for a termination command.
    for word in TRIGGER_WORDS:
        if f"{word} terminate" in transcript:
            if not termination_triggered:
                termination_triggered = True
                print(f"Terminate command received from {source_type}")
                running = False
            return  # Exit early without further processing

    # Check for any trigger word in the transcript.
    if any(word in transcript for word in TRIGGER_WORDS):
        detected_words = [word for word in TRIGGER_WORDS if word in transcript]
        if not detected_words:
            return

        trigger_word = detected_words[0]
        print(f"Trigger '{trigger_word}' detected in {source_type}! Checking if duplicate...")

        if trigger_tracker.should_process(transcript):
            print(f"Processing new trigger from {source_type}")

            # Define extended prebuffer duration to ensure the trigger word is captured.
            EXTENDED_PREBUFFER_DURATION = 3.0  # Adjust as needed
            FRAME_DURATION_MS = 30
            frames_per_second = int(1000 / FRAME_DURATION_MS)
            prebuffer_frame_count = int(EXTENDED_PREBUFFER_DURATION * frames_per_second)

            # Extract the extended prebuffer from the continuous buffer.
            if len(continuous_buffer) >= prebuffer_frame_count:
                extended_prebuffer = list(continuous_buffer)[-prebuffer_frame_count:]
            else:
                extended_prebuffer = list(continuous_buffer)

            # Record a new audio segment that starts with the extended prebuffer.
            combined_filename = record_audio_with_prebuffer(extended_prebuffer)

            # Transcribe the audio (using Whisper or the Google API fallback).
            final_transcript = transcribe_audio(combined_filename)

            # Immediately delete the file once processed.
            try:
                os.remove(combined_filename)
            except Exception as e:
                print(f"Error removing combined file: {e}")

            if final_transcript:
                print(f"Transcript from {source_type}:", final_transcript)
                try:
                    with open(TRANSCRIPT_FILE, "w", encoding="utf-8") as f:
                        f.write(final_transcript)
                    trigger_url_call()
                except Exception as e:
                    print(f"Error writing transcript: {e}")
        else:
            print(f"Trigger from {source_type} deemed duplicate, ignoring")

def continuous_buffer_monitor():
    """
    Periodically processes the continuous buffer to check for trigger words,
    regardless of the dynamic recording system.
    """
    FRAME_DURATION_MS = 30
    BUFFER_CHECK_INTERVAL = 1.0  # Check the buffer every second
    
    recognizer = sr.Recognizer()
    
    while running:
        # FIX 1: Check if Firebot is running when required
        if stop_if_firebot_not_running():
            break
            
        time.sleep(BUFFER_CHECK_INTERVAL)
        
        if len(continuous_buffer) < 16:  # Skip if buffer is too small
            continue
            
        # Create a temporary file from the continuous buffer
        temp_filename = f"buffer_check_{int(time.time() * 1000)}.wav"
        with wave.open(temp_filename, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # Assuming 16-bit audio
            wf.setframerate(16000)
            wf.writeframes(b"".join(continuous_buffer))
        
        # Now process this file with speech recognition
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
                
                # Only process if a trigger word was detected
                if any(word in transcript for word in TRIGGER_WORDS) or any(f"{word} terminate" in transcript for word in TRIGGER_WORDS):
                    print("Buffer monitor detected potential trigger in: ", transcript)
                    process_trigger(transcript, temp_filename, source_type="buffer_monitor")
            except sr.UnknownValueError:
                pass
            except sr.RequestError:
                pass
        except Exception as e:
            print(f"Buffer monitor error: {e}")
        
        # Clean up temporary file
        try:
            os.remove(temp_filename)
        except Exception:
            pass

def dual_continuous_recording():
    """
    Implements a dual recording system where two recorders alternate to ensure continuous coverage.
    One recorder is always active while the other may be in its silence detection period.
    """
    FRAME_DURATION_MS = 30
    frames_per_sec = int(1000 / FRAME_DURATION_MS)
    overlap_frame_count = int(frames_per_sec * OVERLAP_SECONDS)
    
    # Create two separate prebuffers
    prebuffer_1 = None
    prebuffer_2 = None
    
    # Track which recorder is currently active
    recorder_1_active = True
    
    # Create a lock to synchronize recorder switching
    recorder_lock = threading.Lock()
    
    while running:
        # FIX 1: Check if Firebot is running when required
        if stop_if_firebot_not_running():
            break
            
        # Start recorder 1
        if recorder_1_active:
            # Start recorder 2 in a separate thread after a delay
            def start_recorder_2():
                nonlocal prebuffer_2, recorder_1_active
                # Wait before starting recorder 2 (less than silence detection period)
                time.sleep(RECORDER_TRANSITION_DELAY)  # Reduced delay
                with recorder_lock:
                    if recorder_1_active:  # Double-check it's still recorder 1's turn
                        result = record_audio_dynamic(prebuffer=prebuffer_2, return_frames=True)
                        if result:
                            filename, frames = result
                            audio_queue.put(filename)
                            # Update prebuffer 2
                            if len(frames) >= overlap_frame_count:
                                prebuffer_2 = frames[-overlap_frame_count:]
                            else:
                                prebuffer_2 = frames
                            # Switch to recorder 2
                            recorder_1_active = False
            
            # Start recorder 2 thread
            threading.Thread(target=start_recorder_2, daemon=True).start()
            
            # Run recorder 1
            with recorder_lock:
                if recorder_1_active:  # Check again in case it changed
                    result = record_audio_dynamic(prebuffer=prebuffer_1, return_frames=True)
                    if result:
                        filename, frames = result
                        audio_queue.put(filename)
                        # Update prebuffer 1
                        if len(frames) >= overlap_frame_count:
                            prebuffer_1 = frames[-overlap_frame_count:]
                        else:
                            prebuffer_1 = frames
                        
        # Start recorder 1 in a similar way if recorder 2 is active
        else:
            # Start recorder 1 in a separate thread after a delay
            def start_recorder_1():
                nonlocal prebuffer_1, recorder_1_active
                time.sleep(RECORDER_TRANSITION_DELAY)  # Reduced delay
                with recorder_lock:
                    if not recorder_1_active:  # Double-check it's still recorder 2's turn
                        result = record_audio_dynamic(prebuffer=prebuffer_1, return_frames=True)
                        if result:
                            filename, frames = result
                            audio_queue.put(filename)
                            # Update prebuffer 1
                            if len(frames) >= overlap_frame_count:
                                prebuffer_1 = frames[-overlap_frame_count:]
                            else:
                                prebuffer_1 = frames
                            # Switch back to recorder 1
                            recorder_1_active = True
            
            # Start recorder 1 thread
            threading.Thread(target=start_recorder_1, daemon=True).start()
            
            # Run recorder 2
            with recorder_lock:
                if not recorder_1_active:  # Check again in case it changed
                    result = record_audio_dynamic(prebuffer=prebuffer_2, return_frames=True)
                    if result:
                        filename, frames = result
                        audio_queue.put(filename)
                        # Update prebuffer 2
                        if len(frames) >= overlap_frame_count:
                            prebuffer_2 = frames[-overlap_frame_count:]
                        else:
                            prebuffer_2 = frames
                        
        # Small delay to prevent CPU thrashing
        time.sleep(0.1)

def process_audio_chunk():
    recognizer = sr.Recognizer()
    while running:
        # FIX 1: Check if Firebot is running when required
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

        transcript = ""
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
                
            # Process any detected triggers using the unified function
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
    """Transcribes the given WAV file using the Whisper API if available,
    otherwise falls back to using the Google Speech Recognition API."""
    # Check if a valid Whisper API key is provided
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
        # Fallback: Use Google Speech Recognition
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

def trigger_url_call():
    """Calls the trigger URL with duplicate protection."""
    global last_url_call_time
    
    # FIX 2: Don't trigger URL if termination is in progress
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
    
    # FIX 1: Check Firebot at startup
    if FIREBOT_REQUIRED and not check_firebot():
        print("Firebot process not found. Terminating...")
        sys.exit(0)
    
    # Start the dual recording system
    record_thread = threading.Thread(target=dual_continuous_recording, daemon=True)
    record_thread.start()
    
    # Start the audio chunk processing thread
    process_thread = threading.Thread(target=process_audio_chunk, daemon=True)
    process_thread.start()
    
    # Start the continuous buffer monitor thread
    buffer_monitor_thread = threading.Thread(target=continuous_buffer_monitor, daemon=True)
    buffer_monitor_thread.start()
    
    print("All systems running. Listening for trigger words...")
    
    try:
        while running:
            # Check if Firebot is running periodically in main loop as well
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
