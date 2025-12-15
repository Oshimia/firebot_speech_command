import subprocess
import os
import sys

def run_command(command):
    print(f"Running: {command}")
    try:
        subprocess.check_call(command, shell=True)
        print("Success.")
    except subprocess.CalledProcessError as e:
        print(f"Error building: {e}")
        sys.exit(1)

def build():
    # Ensure config.json exists
    if not os.path.exists("config.json"):
        print("Error: config.json not found. Please ensure it exists before building.")
        return

    print("Building Executables...")
    
    # Platform specific separator
    sep = ";" if os.name == 'nt' else ":"

    # 1. Build Whisper Service (Windowed/Silent application)
    # The user requested this to be invisible/silent.
    print("\n--- Building Whisper Service ---")
    whisper_cmd = (
        f'pyinstaller --noconfirm --onefile --windowed --name whisper '
        f'--hidden-import=speech_recognition --hidden-import=pyaudio --hidden-import=requests '
        f'--add-data "config.json{sep}." '
        f'whisper.py'
    )
    run_command(whisper_cmd)

    # 2. Build GUI (Windowed application)
    print("\n--- Building GUI ---")
    gui_cmd = (
        f'pyinstaller --noconfirm --onefile --windowed --name GUI '
        f'--hidden-import=tkinter --hidden-import=speech_recognition --hidden-import=requests '
        f'--add-data "config.json{sep}." '
        f'GUI.py'
    )
    run_command(gui_cmd)

    print("\nBuild Complete!")
    print(f"Executables are located in: {os.path.abspath('dist')}")

if __name__ == "__main__":
    build()
