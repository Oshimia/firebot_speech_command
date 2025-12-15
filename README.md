# Voice Control for Firebot

A modular, configurable voice control system designed for Firebot and streaming setups. It listens for specific trigger words using Google's free Speech Recognition API and then transcribes the command—optionally using OpenAI's Whisper API for superior accuracy—before triggering specific URLs (e.g., Firebot effects).

## Features

-   **Hybrid Transcription**: Uses lightweight Google Speech Recognition for always-on trigger detection (free) and optionally switches to OpenAI Whisper for detailed command transcription.
-   **Unified Modular Triggers**: Define multiple independent sets of trigger words. Each set can:
    -   Listen for different phrases (e.g., "Computer", "Lights", "Chat").
    -   Call a specific URL unique to that functionality.
    -   Have its own independent cooldown timer.
-   **GUI Config Editor**: A user-friendly interface to manage settings. includes a dedicated **Trigger Manager** to easily add, edit, or remove trigger rules without touching JSON files.
-   **History Logging**: Keeps a robust history of all transcripts and system events in `whisperHistory.txt`.
    -   Configurable log names (e.g., "Oshimia", "Jarvis").
    -   Automatic pruning of old entries (default: 1 hour).
-   **Configurable Process Monitor**: Check for any specific process (e.g., "Firebot.exe", "OBS.exe") to automatically terminate if the parent app closes.
-   **Silent Operation**: The core `whisper.exe` service runs silently in the background without a console window.

## Requirements

-   Python 3.x
-   `pip install -r requirements.txt` (Dependencies include: `SpeechRecognition`, `pyaudio`, `requests`, `tkinter`, `pyinstaller`, `psutil`)

## Configuration

The application uses `config.json` to store settings. This is managed via the GUI.

### Key Settings:
-   **Triggers**: Managed via the "Manage Triggers" button in the GUI.
-   **API Keys**: Add your OpenAI API Key for Whisper support.
-   **History**: Enable/Disable history logging and set your preferred log name (Prefix).
-   **Process Monitor**: Set `FIREBOT_REQUIRED` to true and `REQUIRED_PROCESS_NAME` to the executable name (e.g. `firebot`) you want to monitor.

## Usage

### Running from Source
Run the GUI to start the application and manage configuration:
```bash
python GUI.py
```
From the GUI, you can:
-   **Launch Program**: Starts the voice listener (executes `whisper.py`).
-   **Edit Config**: Opens the configuration editor.

### Building Executables
An automated build script is included to generate standalone `.exe` files for Windows.

1.  Ensure you have `pyinstaller` installed.
2.  Run the build script:
    ```bash
    python build.py
    ```
3.  The executables will be created in the `dist/` folder:
    -   `GUI.exe`: The visible management interface.
    -   `whisper.exe`: The silent background service. It will run indefinitely until the monitored process closes or you issue the termination voice command.

## Structure

-   `GUI.py`: The management interface.
-   `whisper.py`: The core voice listening service.
-   `modules/`: Contains the modular logic for transcription, configuration, history, and trigger handling.
