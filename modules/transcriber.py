import time
import wave
import os
import threading
import requests
import speech_recognition as sr
from modules.config_manager import (
    TRIGGER_WORDS, WHISPER_API_URL, OPENAI_API_KEY, 
    TRANSCRIPT_FILE, USE_GOOGLE_CLOUD, GOOGLE_CLOUD_CREDENTIALS,
    GOOGLE_LANGUAGE, WHISPER_LANGUAGE, WHISPER_HISTORY_FILE, ENABLE_HISTORY,
    HISTORY_LOG_PREFIX, TRIGGERS
)
from modules.utils import state
from modules.trigger_handler import trigger_url_call
from modules.history_manager import append_to_transcript_history

print(f"DEBUG: transcriber.py loaded. TRIGGERS count: {len(TRIGGERS)}")

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
        
        # Flatten all trigger words for Google Cloud hints
        all_trigger_phrases = []
        for trigger_set in TRIGGERS:
            all_trigger_phrases.extend(trigger_set.get("phrases", []))

        # Use Google or Google Cloud for initial transcription
        if USE_GOOGLE_CLOUD:
            google_transcript = recognizer.recognize_google_cloud(
                audio,
                credentials_json=GOOGLE_CLOUD_CREDENTIALS,
                preferred_phrases=all_trigger_phrases,
                language=GOOGLE_LANGUAGE
            ).lower()
            print("Initial transcript (Google Cloud):", google_transcript)
        else:
            google_transcript = recognizer.recognize_google(audio, language=GOOGLE_LANGUAGE).lower()
            print("Initial transcript (Google):", google_transcript)

        transcript_for_history = google_transcript
        
        # Helper detection function
        def check_termination(text):
            for t_set in TRIGGERS:
                for phrase in t_set.get("phrases", []):
                    if phrase in text and ("terminate" in text or "determinate" in text):
                        return True
            return False

        # Check termination on Google transcript
        if check_termination(google_transcript):
             if not state.termination_triggered:
                state.termination_triggered = True
                term_msg = f"TERMINATION via Google: {google_transcript}"
                print(term_msg)
                if ENABLE_HISTORY:
                    append_to_transcript_history(term_msg, WHISPER_HISTORY_FILE, prefix=HISTORY_LOG_PREFIX)
                state.running = False
                return

        # Check detection on Google transcript
        detected_triggers = []
        any_trigger_found = False
        
        for t_set in TRIGGERS:
            if any(phrase in google_transcript for phrase in t_set.get("phrases", [])):
                detected_triggers.append(t_set)
                any_trigger_found = True

        final_transcript = google_transcript

        if any_trigger_found:
            print("Trigger word detected (Google)!")
            if OPENAI_API_KEY and OPENAI_API_KEY.strip() and OPENAI_API_KEY != "API_KEY_HERE":
                print("Using Whisper API for detailed transcription...")
                whisper_transcript = transcribe_audio(filename)
                if whisper_transcript:
                     final_transcript = whisper_transcript
                     transcript_for_history = whisper_transcript
                     print("Detailed transcript (Whisper):", whisper_transcript)
                     
                     # Re-check termination on Whisper
                     if check_termination(whisper_transcript):
                         if not state.termination_triggered:
                            state.termination_triggered = True
                            term_msg = f"TERMINATION via Whisper: {whisper_transcript}"
                            print(term_msg)
                            if ENABLE_HISTORY:
                                append_to_transcript_history(term_msg, WHISPER_HISTORY_FILE, prefix=HISTORY_LOG_PREFIX)
                            state.running = False
                            return
                     
                     # Re-detect triggers on Whisper (more accurate)
                     detected_triggers = []
                     for t_set in TRIGGERS:
                        if any(phrase in whisper_transcript for phrase in t_set.get("phrases", [])):
                            detected_triggers.append(t_set)
                else:
                     print("Whisper transcription failed, using Google transcript")
            else:
                 print("No Whisper API key, using Google transcript")

            # Execute actions for detected triggers
            if detected_triggers:
                try:
                    with open(TRANSCRIPT_FILE, "w", encoding="utf-8") as f:
                        f.write(final_transcript)
                    
                    for t_set in detected_triggers:
                        url = t_set.get("url")
                        cooldown = t_set.get("cooldown", 2.0)
                        if url:
                            threading.Thread(target=trigger_url_call, args=(url, cooldown), daemon=True).start()
                            print(f"Triggered URL: {url} (Cooldown: {cooldown}s)")
                except Exception as e:
                    print(f"Error processing actions: {e}")
            else:
                print("No trigger words found in final transcript.")

        else:
            print("No trigger word found in initial transcript")
            
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
