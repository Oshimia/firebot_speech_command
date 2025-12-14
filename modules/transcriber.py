import time
import wave
import os
import threading
import requests
import speech_recognition as sr
from modules.config_manager import (
    TRIGGER_WORDS, WHISPER_API_URL, OPENAI_API_KEY, 
    TRANSCRIPT_FILE, USE_GOOGLE_CLOUD, GOOGLE_CLOUD_CREDENTIALS,
    TRANSCRIPT_FILE, USE_GOOGLE_CLOUD, GOOGLE_CLOUD_CREDENTIALS,
    GOOGLE_LANGUAGE, WHISPER_LANGUAGE, WHISPER_HISTORY_FILE, ENABLE_HISTORY,
    HISTORY_LOG_PREFIX
)
from modules.utils import state
from modules.trigger_handler import trigger_url_call
from modules.history_manager import append_to_transcript_history

print(f"DEBUG: transcriber.py loaded. TRIGGER_WORDS: {TRIGGER_WORDS}")

def transcribe_audio(filename):
    """
    Transcribe the given WAV file using the Whisper API if available,
    otherwise fall back to Google Speech Recognition.
    """
    if OPENAI_API_KEY and OPENAI_API_KEY.strip() and OPENAI_API_KEY != "API_KEY_HERE":
        try:
            with open(filename, 'rb') as audio_file:
                headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
                data = {"language": WHISPER_LANGUAGE}
                files = {
                    "file": audio_file,
                    "model": (None, "whisper-1")
                }
                response = requests.post(WHISPER_API_URL, headers=headers, data=data, files=files)
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
            transcript = recognizer.recognize_google(audio, language=GOOGLE_LANGUAGE).lower()
            return transcript
        except sr.UnknownValueError:
            print("Google Speech Recognition could not understand audio")
            return None
        except sr.RequestError as e:
            print("Error with Google Speech Recognition service:", e)
            return None

def process_recording_async(audio_data):
    """
    Process a recording asynchronously:
      - Save the recording as a WAV file.
      - Perform initial transcription using Google (or Google Cloud if configured).
      - If trigger words are detected, optionally use Whisper API for detailed transcription.
      - Write the transcript to a file and trigger the URL.
    """
    frames, channels, sample_width, rate = audio_data

    # Save audio to a unique WAV file
    print(f"DEBUG: Saving WAV - Channels: {channels}, Sample Width: {sample_width}, Rate: {rate}, Frames: {len(frames)}")
    filename = f"recording_{int(time.time() * 1000)}.wav"
    try:
        with wave.open(filename, 'wb') as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(sample_width)
            wf.setframerate(rate)
            wf.writeframes(b"".join(frames))
        print(f"Recording saved: {filename} ({len(frames)} frames, {len(frames) * 30 / 1000:.2f}s)")

        recognizer = sr.Recognizer()
        with sr.AudioFile(filename) as source:
            audio = recognizer.record(source)
        
        # Use Google or Google Cloud for initial transcription
        if USE_GOOGLE_CLOUD:
            google_transcript = recognizer.recognize_google_cloud(
                audio,
                credentials_json=GOOGLE_CLOUD_CREDENTIALS,
                preferred_phrases=TRIGGER_WORDS,
                language=GOOGLE_LANGUAGE
            ).lower()
            print("Initial transcript (Google Cloud):", google_transcript)
        else:
            google_transcript = recognizer.recognize_google(audio, language=GOOGLE_LANGUAGE).lower()
            print("Initial transcript (Google):", google_transcript)

        transcript_for_history = google_transcript
        final_transcript_for_action = google_transcript

        # Check for termination command in the Google transcript
        for word in TRIGGER_WORDS:
            if any(word in google_transcript for word in TRIGGER_WORDS) and ("terminate" in google_transcript or "determinate" in google_transcript):
                if not state.termination_triggered:
                    state.termination_triggered = True
                    term_msg = f"TERMINATION via Google: {google_transcript}"
                    print(term_msg)
                    if ENABLE_HISTORY:
                        append_to_transcript_history(term_msg, WHISPER_HISTORY_FILE, prefix=HISTORY_LOG_PREFIX)
                    state.running = False
                    return

        # Check if any trigger word exists in the transcript
        found_trigger = any(word in google_transcript for word in TRIGGER_WORDS)
        if found_trigger:
            print("Trigger word detected!")
            if OPENAI_API_KEY and OPENAI_API_KEY.strip() and OPENAI_API_KEY != "API_KEY_HERE":
                print("Using Whisper API for detailed transcription...")
                whisper_transcript = transcribe_audio(filename)
                if whisper_transcript:
                    transcript_for_history = whisper_transcript
                    final_transcript_for_action = whisper_transcript
                    
                    # Check termination in Whisper transcript too
                    for word in TRIGGER_WORDS:
                        if any(word in whisper_transcript for word in TRIGGER_WORDS) and ("terminate" in whisper_transcript or "determinate" in whisper_transcript):
                            if not state.termination_triggered:
                                state.termination_triggered = True
                                term_msg = f"TERMINATION via Whisper: {whisper_transcript}"
                                print(term_msg)
                                if ENABLE_HISTORY:
                                    append_to_transcript_history(term_msg, WHISPER_HISTORY_FILE, prefix=HISTORY_LOG_PREFIX)
                                state.running = False
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
            
        # Log to history if enabled and we have a transcript
        if ENABLE_HISTORY and transcript_for_history:
            append_to_transcript_history(transcript_for_history, WHISPER_HISTORY_FILE, prefix=HISTORY_LOG_PREFIX)

    except sr.UnknownValueError:
        print("No speech recognized in recording")
    except sr.RequestError as e:
        print("Google API error:", e)
        if ENABLE_HISTORY:
             append_to_transcript_history(f"[Google API Error: {e}]", WHISPER_HISTORY_FILE, prefix=HISTORY_LOG_PREFIX)
    except Exception as e:
        print(f"Error processing recording: {e}")
        if ENABLE_HISTORY:
             append_to_transcript_history(f"[CRITICAL Processing Error: {e} for {filename}]", WHISPER_HISTORY_FILE, prefix=HISTORY_LOG_PREFIX)
    finally:
        try:
            os.remove(filename)
            print(f"Removed temporary file: {filename}")
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"Error removing file {filename}: {e}")
