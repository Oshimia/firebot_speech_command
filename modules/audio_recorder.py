import pyaudio
import webrtcvad
import threading
from collections import deque
from modules.config_manager import SILENCE_DURATION, FIREBOT_REQUIRED
from modules.utils import state
from modules.process_monitor import check_firebot_status
from modules.transcriber import process_recording_async

# Global used in original logic, kept here or in state
continuous_buffer = deque(maxlen=int(16000 * 5 / 480))

def initialize_pyaudio():
    """
    Initialize and return the global PyAudio instance.
    """
    if state.p_audio is None:
        state.p_audio = pyaudio.PyAudio()
    return state.p_audio

def vad_based_recording():
    """
    Start a VAD-based recording system:
      - Uses a prebuffer to capture 1 second before speech detection.
      - Starts recording upon detecting speech.
      - Stops recording after silence is detected or max duration is reached.
    """
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

    while state.running:
        # Check Firebot status periodically
        # Note: firebot status check can modify state.running
        if FIREBOT_REQUIRED and not check_firebot_status(state):
            break
        
        # If state.running became false from external signal, break
        if not state.running:
            break

        # Read the next audio frame
        # exception_on_overflow=False matches original behavior
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
