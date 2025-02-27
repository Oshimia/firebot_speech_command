import tkinter as tk
import tkinter.font as tkFont
from tkinter import filedialog, messagebox, scrolledtext, simpledialog
from tkinter import ttk
import json
import sys
import subprocess
import threading
import os
import time
import signal

# Windows-specific imports for Job objects
if os.name == 'nt':
    import win32job
    import win32api

# Get the application's base directory (works in both script and exe mode)
def get_base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

def update_text_wrap(event, text_widget):
    # Get the font used by the text widget.
    font = tkFont.Font(font=text_widget.cget("font"))
    # Estimate the average pixel width of a character (using "0" as a sample).
    avg_char_width = font.measure("0")
    # Compute the new number of characters that can fit in the widget's current width.
    new_width = max(20, int(text_widget.winfo_width() / avg_char_width))
    text_widget.config(width=new_width)

CONFIG_FILE = os.path.join(get_base_dir(), "config.json")

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
        except Exception as e:
            print(f"Error reading config.json at {CONFIG_FILE}:", e)
            config = {}
    else:
        print(f"Config file not found at {CONFIG_FILE}, creating default config")
        config = {}
    config.setdefault("program_path", "")
    config.setdefault("trigger_words", [])
    config.setdefault("url_mapping", {})
    config.setdefault("auto_launch", False)
    return config

def save_config(config):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=4)
        print(f"Config saved to {CONFIG_FILE}")
    except Exception as e:
        print(f"Error saving config.json to {CONFIG_FILE}:", e)

class GUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Program Launcher and Terminal")
        self.geometry("800x600")
        
        # Bind close event to our custom handler.
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        base_dir = get_base_dir()
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
        
        self.process = None
        self.read_thread = None
        self.stop_thread = False
        self.is_launching = False  # Flag to prevent double launches
        
        # Job object for Windows (to group the process and its children)
        self.job = None
        
        if not self.program_path_var.get() or not os.path.exists(self.program_path_var.get()):
            self.change_program_path()
        
        if self.config_data.get("auto_launch"):
            self.after(1000, self.launch_program)
    
    def on_closing(self):
        """Ensure the subprocess is terminated before closing the GUI."""
        print("Application closing, terminating any running processes...")
        self.terminate_program()
        # Wait for the output reading thread to finish
        if self.read_thread and self.read_thread.is_alive():
            print("Waiting for output reader thread to finish...")
            self.read_thread.join(timeout=3)
        print("Closing application")
        self.destroy()

    def terminate_program(self):
        """Terminate the running process and cleanup, including all subprocesses via the Job object."""
        if not self.process:
            return
            
        print("Terminating running process and its children via job object...")
        self.stop_thread = True

        try:
            # On Windows, close the Job object handle; this will kill all processes in the job.
            if os.name == 'nt' and self.job:
                win32api.CloseHandle(self.job)
                self.job = None

            # Wait for the process to exit gracefully.
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                print("Process did not terminate within timeout, killing forcefully...")
                self.process.kill()
                self.process.wait(timeout=3)
        except Exception as e:
            print(f"Error terminating process: {e}")

        # Close stdout to unblock the reading thread.
        try:
            if self.process.stdout:
                self.process.stdout.close()
        except Exception as e:
            print(f"Error closing process stdout: {e}")

        self.process = None
        self.terminate_button.config(state=tk.DISABLED)
        print("Process terminated")

        if self.read_thread and self.read_thread.is_alive():
            print("Waiting for output reader thread to complete...")
            self.read_thread.join(timeout=3)
            self.read_thread = None
    
    def auto_launch_changed(self, *args):
        self.config_data["auto_launch"] = self.auto_launch_var.get()
        save_config(self.config_data)
        if self.auto_launch_var.get():
            if not self.process and not self.is_launching:
                self.after(500, self.launch_program)
    
    # --- Modified Dynamic Config Editor (No Tabs) ---
    def open_config_editor(self):
        editor = tk.Toplevel(self)
        editor.title("Edit Configuration")
        editor.geometry("700x500")

        # Create a container with a canvas and scrollbar for complete scrolling.
        container = tk.Frame(editor)
        container.pack(fill=tk.BOTH, expand=True)
        canvas = tk.Canvas(container)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = tk.Scrollbar(container, orient="vertical", command=canvas.yview)
        scrollbar.pack(side=tk.RIGHT, fill="y")
        canvas.configure(yscrollcommand=scrollbar.set)

        # Create a frame inside the canvas to hold the form.
        form_frame = tk.Frame(canvas)
        canvas.create_window((0, 0), window=form_frame, anchor="nw")

        # Bind a function to update the scrollable region.
        form_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        # Define a function to forward mousewheel scrolling to the canvas.
        def _on_mousewheel(event):
            # On Windows, event.delta is a multiple of 120; adjust for other platforms if needed.
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        # Bind the mouse wheel to the canvas for the entire area.
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # Dictionaries to keep track of input widget references.
        self.general_vars = {}   # For booleans, ints, floats using StringVar/BooleanVar.
        self.text_widgets = {}   # For multi-line strings, lists, and dicts.

        row = 0
        for key, value in self.config_data.items():
            tk.Label(form_frame, text=f"{key}:").grid(row=row, column=0, sticky=tk.NW, padx=5, pady=5)
            if isinstance(value, bool):
                var = tk.BooleanVar(value=value)
                chk = tk.Checkbutton(form_frame, variable=var)
                chk.grid(row=row, column=1, sticky=tk.W, padx=5, pady=5)
                self.general_vars[key] = var
            elif isinstance(value, (int, float)):
                var = tk.StringVar(value=str(value))
                ent = tk.Entry(form_frame, textvariable=var)
                ent.grid(row=row, column=1, sticky=tk.EW, padx=5, pady=5)
                self.general_vars[key] = var
            elif isinstance(value, (str, list, dict)):
                # For lists/dicts, display as pretty JSON.
                if isinstance(value, (list, dict)):
                    text_value = json.dumps(value, indent=4)
                else:
                    text_value = value
                # Calculate the initial height based on the number of newlines.
                line_count = text_value.count("\n") + 1
                height = max(line_count, 3)
                # Create the Text widget without an explicit width so it can expand.
                text = tk.Text(form_frame, height=height, wrap="word")
                text.insert("1.0", text_value)
                text.grid(row=row, column=1, sticky="nsew", padx=5, pady=5)
                # Bind <Configure> to update the widget's width based on its pixel size.
                text.bind("<Configure>", lambda event, tw=text: update_text_wrap(event, tw))
                self.text_widgets[key] = text

                # Bind the mouse wheel for the text widget to forward scrolling.
                text.bind("<MouseWheel>", _on_mousewheel)
            row += 1

        # Ensure that the second column expands to take available horizontal space.
        form_frame.grid_columnconfigure(1, weight=1)

        bottom_frame = tk.Frame(editor)
        bottom_frame.pack(fill=tk.X, padx=10, pady=10)
        tk.Button(bottom_frame, text="Save", command=lambda: self.save_config_changes(editor),
                  fg="white", bg="blue").pack(side=tk.RIGHT, padx=5)
        tk.Button(bottom_frame, text="Close", command=editor.destroy).pack(side=tk.RIGHT, padx=5)


    def save_config_changes(self, editor_window):
        for key in self.config_data.keys():
            if key in self.general_vars:
                value = self.general_vars[key].get()
            elif key in self.text_widgets:
                widget = self.text_widgets[key]
                value = widget.get("1.0", tk.END).rstrip()
            else:
                continue

            orig = self.config_data.get(key)
            if isinstance(orig, bool):
                if isinstance(value, bool):
                    self.config_data[key] = value
                else:
                    self.config_data[key] = (value.lower() in ["true", "1", "yes"])
            elif isinstance(orig, (int, float)):
                try:
                    self.config_data[key] = int(value) if isinstance(orig, int) else float(value)
                except ValueError:
                    self.config_data[key] = value
            elif isinstance(orig, (list, dict)):
                try:
                    self.config_data[key] = json.loads(value)
                except Exception as e:
                    print(f"Error parsing JSON for {key}: {e}")
                    self.config_data[key] = value
            else:
                self.config_data[key] = value

        save_config(self.config_data)
        self.program_path_var.set(self.config_data.get("program_path", ""))
        messagebox.showinfo("Info", "Configuration saved successfully.")
        editor_window.destroy()

    # ---------------- Program Launching & Terminal -------------------
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
        if self.process:
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
            # On Windows, set flags to create a new process group and prepare a Job object.
            if os.name == 'nt':
                creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
                # Create the Job object configured to kill all processes on job close.
                self.job = win32job.CreateJobObject(None, "")
                job_info = win32job.QueryInformationJobObject(self.job, win32job.JobObjectExtendedLimitInformation)
                job_info['BasicLimitInformation']['LimitFlags'] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                win32job.SetInformationJobObject(self.job, win32job.JobObjectExtendedLimitInformation, job_info)
            else:
                creation_flags = 0
            
            # Build the command.
            if target.endswith(".py"):
                if getattr(sys, 'frozen', False):
                    cmd = ["python", "-u", target]
                else:
                    cmd = [sys.executable, "-u", target]
            else:
                cmd = [target]
            print(f"Running command: {cmd}")
            
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                bufsize=1,
                universal_newlines=False,
                creationflags=creation_flags,
                cwd=os.path.dirname(target)
            )
            
            # On Windows, assign the process to the Job object.
            if os.name == 'nt' and self.job:
                win32job.AssignProcessToJobObject(self.job, self.process._handle)
            
            self.stop_thread = False
            self.read_thread = threading.Thread(target=self.read_process_output)
            self.read_thread.daemon = True
            self.read_thread.start()
            self.terminate_button.config(state=tk.NORMAL)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to launch program: {e}")
            print(f"Error launching program: {e}")
        finally:
            self.is_launching = False
    
    def read_process_output(self):
        if not self.process:
            return
        print("Output reader thread started")
        try:
            while self.process and not self.stop_thread:
                if self.process.poll() is not None:
                    break
                try:
                    output = self.process.stdout.read(1)
                    if output:
                        try:
                            text = output.decode('utf-8', errors='replace')
                            self.after_idle(self._append_to_terminal, text)
                        except Exception as e:
                            print(f"Decoding error: {e}")
                    else:
                        time.sleep(0.01)
                except Exception as e:
                    print(f"Read error: {e}")
                    time.sleep(0.1)
        except Exception as e:
            print(f"Output reader exception: {e}")
        finally:
            exit_code = None
            if self.process:
                try:
                    exit_code = self.process.poll()
                    if exit_code is None:
                        exit_code = self.process.wait(timeout=1)
                except:
                    pass
            self.after_idle(self._process_ended, exit_code)
            print("Output reader thread ended")
    
    def _append_to_terminal(self, text):
        try:
            self.terminal_output.insert(tk.END, text)
            self.terminal_output.see(tk.END)
        except Exception as e:
            print(f"Terminal update error: {e}")
    
    def _process_ended(self, exit_code):
        self.process = None
        self.terminate_button.config(state=tk.DISABLED)
        print(f"Process terminated with exit code: {exit_code}")

class ConsoleRedirector:
    def __init__(self, text_widget):
        self.text_widget = text_widget

    def write(self, s):
        self.text_widget.insert(tk.END, s)
        self.text_widget.see(tk.END)

    def flush(self):
        pass

def main():
    app = GUI()
    app.mainloop()

if __name__ == "__main__":
    main()
