import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.simpledialog import askstring
import json
import sys
from logic import listen_microphone, load_config
import threading

class GUI(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Voice Command Interface")
        self.geometry("800x400")

        self.config = load_config()

        self.label = tk.Label(self, text="Voice Command Interface", font=("Arial", 16))
        self.label.pack(pady=10)

        self.frame = tk.Frame(self)
        self.frame.pack(pady=10)

        self.trigger_frame = tk.Frame(self.frame)
        self.trigger_frame.pack(side=tk.LEFT, padx=10)

        self.trigger_label = tk.Label(self.trigger_frame, text="Trigger Words:", font=("Arial", 12))
        self.trigger_label.pack()

        self.trigger_listbox = tk.Listbox(self.trigger_frame, selectmode=tk.SINGLE)
        self.trigger_listbox.pack(fill=tk.BOTH, expand=True)

        self.trigger_button_frame = tk.Frame(self.trigger_frame)
        self.trigger_button_frame.pack(pady=5)

        self.trigger_add_button = tk.Button(self.trigger_button_frame, text="Add", command=self.add_trigger_word)
        self.trigger_add_button.pack(side=tk.LEFT, padx=5)

        self.trigger_edit_button = tk.Button(self.trigger_button_frame, text="Edit", command=self.edit_trigger_word)
        self.trigger_edit_button.pack(side=tk.LEFT, padx=5)

        self.trigger_remove_button = tk.Button(self.trigger_button_frame, text="Remove", command=self.remove_trigger_word)
        self.trigger_remove_button.pack(side=tk.LEFT, padx=5)

        self.command_frame = tk.Frame(self.frame)
        self.command_frame.pack(side=tk.RIGHT, padx=10)

        self.command_label = tk.Label(self.command_frame, text="Commands:", font=("Arial", 12))
        self.command_label.pack()

        self.command_listbox = tk.Listbox(self.command_frame, selectmode=tk.SINGLE)
        self.command_listbox.pack(fill=tk.BOTH, expand=True)

        self.command_button_frame = tk.Frame(self.command_frame)
        self.command_button_frame.pack(pady=5)

        self.command_add_button = tk.Button(self.command_button_frame, text="Add", command=self.add_command)
        self.command_add_button.pack(side=tk.LEFT, padx=5)

        self.command_edit_button = tk.Button(self.command_button_frame, text="Edit", command=self.edit_command)
        self.command_edit_button.pack(side=tk.LEFT, padx=5)

        self.command_remove_button = tk.Button(self.command_button_frame, text="Remove", command=self.remove_command)
        self.command_remove_button.pack(side=tk.LEFT, padx=5)

        self.terminate_button = tk.Button(self, text="Terminate", command=self.terminate_command)
        self.terminate_button.pack(pady=5)

        self.console_output = tk.Text(self, height=10, width=60)
        self.console_output.pack(pady=10, padx=10, fill=tk.BOTH, expand=True)

        # Redirect stdout to the console output text area
        sys.stdout = ConsoleRedirector(self.console_output)

        # Load initial trigger words and commands
        self.load_trigger_words()
        self.load_commands()

        # Start continuous listening
        self.listen_command()

    def load_trigger_words(self):
        self.trigger_listbox.delete(0, tk.END)
        for word in self.config["trigger_words"]:
            self.trigger_listbox.insert(tk.END, word)

    def load_commands(self):
        self.command_listbox.delete(0, tk.END)
        for command in self.config["url_mapping"]:
            self.command_listbox.insert(tk.END, command)

    def add_trigger_word(self):
        new_word = askstring("Add Trigger Word", "Enter a single word:")
        if new_word:
            self.config["trigger_words"].append(new_word)
            self.trigger_listbox.insert(tk.END, new_word)
            self.update_config()

    def edit_trigger_word(self):
        selected_index = self.trigger_listbox.curselection()
        if selected_index:
            selected_word = self.trigger_listbox.get(selected_index)
            edited_word = askstring("Edit Trigger Word", "Edit word:", initialvalue=selected_word)
            if edited_word:
                self.config["trigger_words"][selected_index[0]] = edited_word
                self.trigger_listbox.delete(selected_index)
                self.trigger_listbox.insert(selected_index[0], edited_word)
                self.update_config()

    def remove_trigger_word(self):
        selected_index = self.trigger_listbox.curselection()
        if selected_index:
            selected_word = self.trigger_listbox.get(selected_index)
            self.config["trigger_words"].remove(selected_word)
            self.trigger_listbox.delete(selected_index)
            self.update_config()

    def add_command(self):
        command_name = askstring("Add Command", "Enter command name:")
        if command_name:
            command_url = askstring("Add Command", "Enter URL for command:")
            if command_url:
                self.config["url_mapping"][command_name] = command_url
                self.command_listbox.insert(tk.END, command_name)
                self.update_config()

    def edit_command(self):
        selected_index = self.command_listbox.curselection()
        if selected_index:
            selected_command = self.command_listbox.get(selected_index)
            edited_name = askstring("Edit Command", "Edit command name:", initialvalue=selected_command)
            if edited_name:
                edited_url = askstring("Edit Command", "Edit URL for command:", initialvalue=self.config["url_mapping"][selected_command])
                if edited_url:
                    self.config["url_mapping"].pop(selected_command)
                    self.config["url_mapping"][edited_name] = edited_url
                    self.command_listbox.delete(selected_index)
                    self.command_listbox.insert(selected_index[0], edited_name)
                    self.update_config()

    def remove_command(self):
        selected_index = self.command_listbox.curselection()
        if selected_index:
            selected_command = self.command_listbox.get(selected_index)
            self.config["url_mapping"].pop(selected_command)
            self.command_listbox.delete(selected_index)
            self.update_config()

    def listen_command(self):
        def run_listen_microphone():
            while True:
                try:
                    listen_microphone(self.config)
                except Exception as e:
                    messagebox.showerror("Error", f"An error occurred: {str(e)}")

        # Create a new thread for running listen_microphone function
        listen_thread = threading.Thread(target=run_listen_microphone)
        listen_thread.daemon = True  # Daemonize the thread so it exits when the GUI closes
        listen_thread.start()

    def terminate_command(self):
        if messagebox.askokcancel("Terminate", "Are you sure you want to terminate the application?"):
            self.destroy()

    def update_config(self):
        with open("config.json", "w") as config_file:
            json.dump(self.config, config_file, indent=4)

class ConsoleRedirector:
    def __init__(self, console_output):
        self.console_output = console_output

    def write(self, text):
        self.console_output.insert(tk.END, text)
        self.console_output.see(tk.END)  # Scroll to the end of the text area

def main():
    app = GUI()
    app.mainloop()

if __name__ == "__main__":
    main()
