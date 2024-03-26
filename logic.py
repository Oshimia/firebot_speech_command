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

# Function to load configuration from config.json
def load_config():
    with open("config.json", "r") as config_file:
        config = json.load(config_file)
    return config

# Initialize recognizer outside the loop
recognizer = sr.Recognizer()

# Function to listen to microphone
def listen_microphone(config):
    with sr.Microphone() as source:
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
    while True:
        listen_microphone(config)
        if not check_firebot():
            print("Firebot process not found. Terminating...")
            terminate_process()

if __name__ == "__main__":
    main()