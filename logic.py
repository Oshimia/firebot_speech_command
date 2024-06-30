import json
import subprocess
import sys
import speech_recognition as sr
import psutil


# Function to trigger URL using curl
def trigger_url(url):
    try:
        subprocess.Popen(["curl", url], shell=True)
    except Exception as e:
        print("Error executing curl command:", e)

# Function to terminate the process
def terminate_process():
    print("Terminating...")
    sys.exit()

def save_config(config):
    with open("config.json", "w") as config_file:
        json.dump(config, config_file, indent=4)

# Function to load configuration from config.json
def load_config():
    with open("config.json", "r") as config_file:
        config = json.load(config_file)
    return config

def select_microphone():
    mic_list = sr.Microphone.list_microphone_names()
    unique_mic_names = set()  # Use a set to store unique microphone names
    active_mics = []

    for index, name in enumerate(mic_list):
        if name not in unique_mic_names:
            unique_mic_names.add(name)
            try:
                with sr.Microphone(device_index=index) as mic:
                    # Attempt to initialize each microphone to check if it's active
                    pass
                active_mics.append((index, name))
                print(f"{index}: {name}")
            except:
                # If initialization fails, the microphone is not available
                pass

    if not active_mics:
        print("No active microphones found.")
        return None

    selected_index = int(input("Select the microphone index: "))
    while selected_index not in [idx for idx, _ in active_mics]:
        print("Invalid microphone index. Please select from the available options.")
        selected_index = int(input("Select the microphone index: "))

    return selected_index

# Initialize recognizer outside the loop
recognizer = sr.Recognizer()
mic = sr.Microphone()

# Function to listen to microphone
def listen_microphone(config):
    mic_list = sr.Microphone.list_microphone_names()
    microphone_name = config.get("microphone", "")
    selected_mic_index = config.get("microphone_index", 0)
    mic = sr.Microphone()

    if selected_mic_index < len(mic_list):
        mic_name = mic_list[selected_mic_index]
        mic = sr.Microphone(device_index=selected_mic_index)
    else:
        print("Selected microphone index is out of range.")
        return

    with mic as source:
        print("Listening...")

        # Adjust ambient noise for better recognition
        recognizer.adjust_for_ambient_noise(source)

        try:
            # Capture audio from the microphone
            audio = recognizer.listen(source)

            # Use Google Web Speech API to recognize the audio
            text = recognizer.recognize_google(audio)

            print("You said:", text)

            # Check if trigger word is spoken
            trigger_words = config["trigger_words"]
            for trigger_word in trigger_words:
                if trigger_word in text.lower():
                    print("Trigger word detected!")
                    index = text.lower().find(trigger_word) + len(trigger_word)
                    phrase = text[index:].strip()
                    if phrase:
                        print("Phrase after trigger word:", phrase)
                        url_mapping = config["url_mapping"]
                        if phrase in url_mapping:
                            trigger_url(url_mapping[phrase])
                        elif phrase == "terminate":
                            terminate_process()
                        else:
                            print("No action defined for '{}'".format(phrase))
                    else:
                        print("No phrase detected after '{}'".format(trigger_word))

        except sr.UnknownValueError:
            print("Sorry, could not understand audio.")
        except sr.RequestError as e:
            print("Error fetching results from Google Speech Recognition service:", e)

# Check if Firebot process is running
def check_firebot():
    for process in psutil.process_iter():
        if "Firebot" in process.name():
            return True
    return False

# Continuous listening loop
def main():
    config = load_config()

    # Check if microphone configuration exists in config file
    if "microphone_index" not in config:
        print("No microphone configuration found in config file.")
        selected_mic_index = select_microphone()
        config["microphone_index"] = selected_mic_index
        save_config(config)
    else:
        selected_mic_index = config["microphone_index"]
        print(f"Using microphone index {selected_mic_index} from config file.")

    while True:
        listen_microphone(config)
        if not check_firebot():
            print("Firebot process not found. Terminating...")
            terminate_process()

if __name__ == "__main__":
    main()
