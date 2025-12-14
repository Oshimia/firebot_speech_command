import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk
import sys
import os
import time

from modules.config_manager import load_config, save_config, get_config_path
from modules.utils import get_base_dir
from modules.process_launcher import ProcessManager
from modules.gui.config_editor import ConfigEditor
from modules.gui.utils import ConsoleRedirector

class GUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Program Launcher and Terminal")
        self.geometry("800x600")
        
        # Bind close event to our custom handler.
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        base_dir = get_base_dir()
        CONFIG_FILE = get_config_path()
        print(f"Application base directory: {base_dir}")
        print(f"Using config file at: {CONFIG_FILE}")
        
        self.config_data = load_config()
        
        # --- TOP FRAME: Program Path, Auto Launch, and Buttons ---
        self.top_frame = tk.Frame(self)
        self.top_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=10)
        
        program_frame = tk.Frame(self.top_frame)
        program_frame.pack(side=tk.TOP, fill=tk.X)
        tk.Label(program_frame, text="Program Path:").pack(anchor="w")
        self.program_path_var = tk.StringVar(value=self.config_data.get("program_path", ""))
        self.program_path_label = tk.Label(program_frame, textvariable=self.program_path_var, fg="blue")
        self.program_path_label.pack(anchor="w", padx=5)
        
        auto_frame = tk.Frame(self.top_frame)
        auto_frame.pack(side=tk.TOP, fill=tk.X, pady=(5,0))
        self.auto_launch_var = tk.BooleanVar(value=self.config_data.get("auto_launch", False))
        self.auto_launch_var.trace_add("write", self.auto_launch_changed)
        tk.Checkbutton(auto_frame, text="Auto Launch on Startup", variable=self.auto_launch_var).pack(anchor="w")
        mode_text = "Running as executable" if getattr(sys, 'frozen', False) else "Running as Python script"
        tk.Label(auto_frame, text=mode_text, fg="green").pack(anchor="w", pady=(5,0))
        
        btn_frame = tk.Frame(self.top_frame)
        btn_frame.pack(side=tk.TOP, fill=tk.X, pady=(5,0))
        tk.Button(btn_frame, text="Change", command=self.change_program_path).pack(fill=tk.X, pady=2)
        tk.Button(btn_frame, text="Edit Config", command=self.open_config_editor).pack(fill=tk.X, pady=2)
        tk.Button(btn_frame, text="Launch Program", command=self.launch_program).pack(fill=tk.X, pady=2)
        self.terminate_button = tk.Button(btn_frame, text="Terminate Program", command=self.terminate_program, state=tk.DISABLED)
        self.terminate_button.pack(fill=tk.X, pady=2)
        
        self.terminal_output = scrolledtext.ScrolledText(self, height=30)
        self.terminal_output.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        sys.stdout = ConsoleRedirector(self.terminal_output)
        
        self.is_launching = False
        
        self.process_manager = ProcessManager(
            on_output_callback=self.on_process_output,
            on_exit_callback=self.on_process_exit
        )
        
        if not self.program_path_var.get() or not os.path.exists(self.program_path_var.get()):
            self.change_program_path()
        
        if self.config_data.get("auto_launch"):
            self.after(1000, self.launch_program)
    
    def on_closing(self):
        """Ensure the subprocess is terminated before closing the GUI."""
        print("Application closing, terminating any running processes...")
        self.terminate_program()
        print("Closing application")
        self.destroy()

    def terminate_program(self):
        """Terminate the running process."""
        self.process_manager.terminate()
        self.terminate_button.config(state=tk.DISABLED)
    
    def auto_launch_changed(self, *args):
        self.config_data["auto_launch"] = self.auto_launch_var.get()
        save_config(self.config_data)
        if self.auto_launch_var.get():
             # Only auto-launch if we aren't already running and not currently launching
            if not self.process_manager.process and not self.is_launching:
                self.after(500, self.launch_program)
    
    def open_config_editor(self):
        ConfigEditor(self, self.config_data, self.on_config_saved)
        
    def on_config_saved(self, new_config):
        self.config_data = new_config
        self.program_path_var.set(self.config_data.get("program_path", ""))

    def change_program_path(self):
        filepath = filedialog.askopenfilename(
            title="Select Program",
            filetypes=[("All Files", "*.*"), ("Python Scripts", "*.py"), ("Executables", "*.exe")]
        )
        if filepath:
            abs_path = os.path.abspath(filepath)
            self.program_path_var.set(abs_path)
            self.config_data["program_path"] = abs_path
            save_config(self.config_data)
            print(f"Program path updated to: {abs_path}")
    
    def launch_program(self):
        # Prevent double launches
        if self.is_launching:
            print("Launch already in progress, ignoring duplicate request")
            return
            
        self.is_launching = True
        
        # Only terminate if there's an existing process
        if self.process_manager.process:
            print("Terminating existing process before launching new one")
            self.terminate_program()
        
        target = self.config_data.get("program_path", "")
        if not target or not os.path.exists(target):
            messagebox.showerror("Error", f"Invalid target program path: '{target}'\nPlease set a valid path in the configuration.")
            self.is_launching = False
            return
            
        self.terminal_output.delete(1.0, tk.END)
        print(f"Launching: {target}")
        
        try:
            self.process_manager.launch(target)
            self.terminate_button.config(state=tk.NORMAL)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to launch program: {e}")
            print(f"Error launching program: {e}")
        finally:
            self.is_launching = False

    def on_process_output(self, text):
        self.after_idle(self._append_to_terminal, text)
        
    def _append_to_terminal(self, text):
        try:
            self.terminal_output.insert(tk.END, text)
            self.terminal_output.see(tk.END)
        except Exception as e:
            print(f"Terminal update error: {e}")

    def on_process_exit(self, exit_code):
        self.after_idle(self._process_ended, exit_code)

    def _process_ended(self, exit_code):
        self.terminate_button.config(state=tk.DISABLED)
        print(f"Process terminated with exit code: {exit_code}")

def main():
    app = GUI()
    app.mainloop()

if __name__ == "__main__":
    main()
