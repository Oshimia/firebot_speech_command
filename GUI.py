import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, simpledialog
from tkinter import ttk
import json
import sys
import subprocess
import threading
import os
import time

# Get the application's base directory (works in both script and exe mode)
def get_base_dir():
    if getattr(sys, 'frozen', False):
        # Running as compiled exe
        return os.path.dirname(sys.executable)
    else:
        # Running as script
        return os.path.dirname(os.path.abspath(__file__))

# CONFIG_FILE should be a full path relative to the executable or script
CONFIG_FILE = os.path.join(get_base_dir(), "config.json")

def load_config():
    """Load configuration from config.json. If not found, return a default config."""
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
    # Ensure required keys exist, including auto_launch.
    config.setdefault("program_path", "")
    config.setdefault("trigger_words", [])
    config.setdefault("url_mapping", {})
    config.setdefault("auto_launch", False)
    return config

def save_config(config):
    """Save the configuration to config.json."""
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
        
        # Output base directory information for debugging
        base_dir = get_base_dir()
        print(f"Application base directory: {base_dir}")
        print(f"Using config file at: {CONFIG_FILE}")
        
        # Load configuration data.
        self.config_data = load_config()
        
        # --- TOP FRAME: Program Path, Auto Launch, and Buttons ---
        self.top_frame = tk.Frame(self)
        self.top_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=10)
        
        # Program path display.
        program_frame = tk.Frame(self.top_frame)
        program_frame.pack(side=tk.TOP, fill=tk.X)
        tk.Label(program_frame, text="Program Path:").pack(anchor="w")
        self.program_path_var = tk.StringVar(value=self.config_data.get("program_path", ""))
        self.program_path_label = tk.Label(program_frame, textvariable=self.program_path_var, fg="blue")
        self.program_path_label.pack(anchor="w", padx=5)
        
        # Auto Launch checkbutton (stored in config).
        auto_frame = tk.Frame(self.top_frame)
        auto_frame.pack(side=tk.TOP, fill=tk.X, pady=(5,0))
        self.auto_launch_var = tk.BooleanVar(value=self.config_data.get("auto_launch", False))
        # Bind a trace callback to update config and trigger launch if needed.
        self.auto_launch_var.trace_add("write", self.auto_launch_changed)
        tk.Checkbutton(auto_frame, text="Auto Launch on Startup", variable=self.auto_launch_var).pack(anchor="w")
        
        # Current running mode indicator
        mode_text = "Running as executable" if getattr(sys, 'frozen', False) else "Running as Python script"
        tk.Label(auto_frame, text=mode_text, fg="green").pack(anchor="w", pady=(5,0))
        
        # Vertical button column under program path.
        btn_frame = tk.Frame(self.top_frame)
        btn_frame.pack(side=tk.TOP, fill=tk.X, pady=(5,0))
        tk.Button(btn_frame, text="Change", command=self.change_program_path).pack(fill=tk.X, pady=2)
        tk.Button(btn_frame, text="Edit Config", command=self.open_config_editor).pack(fill=tk.X, pady=2)
        tk.Button(btn_frame, text="Launch Program", command=self.launch_program).pack(fill=tk.X, pady=2)
        self.terminate_button = tk.Button(btn_frame, text="Terminate Program", command=self.terminate_program, state=tk.DISABLED)
        self.terminate_button.pack(fill=tk.X, pady=2)
        
        # --- TERMINAL OUTPUT TEXT AREA ---
        self.terminal_output = scrolledtext.ScrolledText(self, height=30)
        self.terminal_output.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Redirect stdout to the terminal.
        sys.stdout = ConsoleRedirector(self.terminal_output)
        
        self.process = None    # Holds the subprocess.Popen object.
        self.read_thread = None  # Thread for reading process output.
        self.stop_thread = False  # Flag to signal thread termination
        
        # If no valid program path is set, ask the user to choose one.
        if not self.program_path_var.get() or not os.path.exists(self.program_path_var.get()):
            self.change_program_path()
        
        # If auto_launch is set in config, schedule launching the program after a short delay.
        if self.config_data.get("auto_launch"):
            self.after(1000, self.launch_program)
    
    def auto_launch_changed(self, *args):
        """Callback triggered when the Auto Launch checkbutton is toggled."""
        # Update the config setting and save immediately.
        self.config_data["auto_launch"] = self.auto_launch_var.get()
        save_config(self.config_data)
        # If auto_launch is turned on and the program is not running, schedule launching.
        if self.auto_launch_var.get():
            if not self.process:
                self.after(500, self.launch_program)
    
    # ---------------- Dynamic Config Editor -------------------
    def open_config_editor(self):
        """Open a dynamic configuration editor window based on the config file structure."""
        editor = tk.Toplevel(self)
        editor.title("Edit Configuration")
        editor.geometry("700x500")
        
        # Create a container frame for the scrollable area.
        container = tk.Frame(editor)
        container.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        
        # Create a canvas and attach a vertical scrollbar to it.
        canvas = tk.Canvas(container)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = tk.Scrollbar(container, orient="vertical", command=canvas.yview)
        scrollbar.pack(side=tk.RIGHT, fill="y")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Create a frame inside the canvas that will contain the notebook.
        scrollable_frame = tk.Frame(canvas)
        # Save the canvas window ID to update its width later.
        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        
        # Update the scroll region when the size of the scrollable frame changes.
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        # Bind the canvas configuration to update the width of the inner frame.
        def on_canvas_configure(event):
            canvas.itemconfig(canvas_window, width=event.width)
        canvas.bind("<Configure>", on_canvas_configure)
        
        # Create the Notebook inside the scrollable frame.
        notebook = ttk.Notebook(scrollable_frame)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Dictionaries to hold widget references for later retrieval.
        self.general_vars = {}  # For general key:value pairs.
        self.array_widgets = {}  # For keys whose value is a list.
        self.object_widgets = {}  # For keys whose value is an object.
        
        config = self.config_data
        # Categorize the config keys.
        arrays = {k: v for k, v in config.items() if isinstance(v, list)}
        objects = {k: v for k, v in config.items() if isinstance(v, dict)}
        general = {k: v for k, v in config.items() if not isinstance(v, (list, dict))}
        
        # Create a tab for each array key.
        for key, arr in arrays.items():
            frame = tk.Frame(notebook)
            notebook.add(frame, text=key)
            listbox = tk.Listbox(frame)
            listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
            for item in arr:
                listbox.insert(tk.END, item)
            self.array_widgets[key] = listbox
            
            btn_frame = tk.Frame(frame)
            btn_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=5, pady=5)
            tk.Button(btn_frame, text="Add", command=lambda k=key: self.add_array_item(k)).pack(pady=2)
            tk.Button(btn_frame, text="Edit", command=lambda k=key: self.edit_array_item(k)).pack(pady=2)
            tk.Button(btn_frame, text="Remove", command=lambda k=key: self.remove_array_item(k)).pack(pady=2)
        
        # Create a tab for each object key.
        for key, obj in objects.items():
            frame = tk.Frame(notebook)
            notebook.add(frame, text=key)
            columns = ("key", "value")
            tree = ttk.Treeview(frame, columns=columns, show="headings")
            tree.heading("key", text="Key")
            tree.heading("value", text="Value")
            tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
            for k, v in obj.items():
                tree.insert("", tk.END, values=(k, v))
            self.object_widgets[key] = tree
            
            btn_frame = tk.Frame(frame)
            btn_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=5, pady=5)
            tk.Button(btn_frame, text="Add", command=lambda k=key: self.add_object_item(k)).pack(pady=2)
            tk.Button(btn_frame, text="Edit", command=lambda k=key: self.edit_object_item(k)).pack(pady=2)
            tk.Button(btn_frame, text="Remove", command=lambda k=key: self.remove_object_item(k)).pack(pady=2)
        
        # Create a "General Settings" tab for remaining key:value pairs.
        if general:
            frame = tk.Frame(notebook)
            notebook.add(frame, text="General Settings")
            row = 0
            for key, value in general.items():
                tk.Label(frame, text=key+":").grid(row=row, column=0, sticky=tk.W, padx=5, pady=5)
                if isinstance(value, bool):
                    var = tk.BooleanVar(value=value)
                    chk = tk.Checkbutton(frame, variable=var)
                    chk.grid(row=row, column=1, sticky=tk.W, padx=5, pady=5)
                    self.general_vars[key] = var
                else:
                    var = tk.StringVar(value=str(value))
                    ent = tk.Entry(frame, textvariable=var, width=50)
                    ent.grid(row=row, column=1, sticky=tk.W, padx=5, pady=5)
                    self.general_vars[key] = var
                row += 1
        
        # Fixed bottom frame for Save and Close buttons.
        bottom_frame = tk.Frame(editor)
        bottom_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=10)
        save_btn = tk.Button(bottom_frame, text="Save", command=lambda: self.save_config_changes(editor),
                             fg="white", bg="blue")
        save_btn.pack(side=tk.RIGHT, padx=5)
        close_btn = tk.Button(bottom_frame, text="Close", command=editor.destroy)
        close_btn.pack(side=tk.RIGHT, padx=5)
    
    def add_array_item(self, key):
        item = simpledialog.askstring("Add Item", f"Enter a new item for '{key}':")
        if item:
            listbox = self.array_widgets[key]
            listbox.insert(tk.END, item)
    
    def edit_array_item(self, key):
        listbox = self.array_widgets[key]
        sel = listbox.curselection()
        if not sel:
            messagebox.showerror("Error", "Please select an item to edit.")
            return
        index = sel[0]
        current_item = listbox.get(index)
        new_item = simpledialog.askstring("Edit Item", f"Edit item for '{key}':", initialvalue=current_item)
        if new_item:
            listbox.delete(index)
            listbox.insert(index, new_item)
    
    def remove_array_item(self, key):
        listbox = self.array_widgets[key]
        sel = listbox.curselection()
        if not sel:
            messagebox.showerror("Error", "Please select an item to remove.")
            return
        index = sel[0]
        listbox.delete(index)
    
    def add_object_item(self, key):
        new_key = simpledialog.askstring("Add Item", f"Enter new key for '{key}':")
        if not new_key:
            return
        new_value = simpledialog.askstring("Add Item", f"Enter value for '{new_key}':")
        if new_value is None:
            return
        tree = self.object_widgets[key]
        tree.insert("", tk.END, values=(new_key, new_value))
    
    def edit_object_item(self, key):
        tree = self.object_widgets[key]
        selected = tree.selection()
        if not selected:
            messagebox.showerror("Error", "Please select an item to edit.")
            return
        item = tree.item(selected[0])
        old_key, old_value = item["values"]
        new_key = simpledialog.askstring("Edit Item", "Edit key:", initialvalue=old_key)
        if new_key is None:
            return
        new_value = simpledialog.askstring("Edit Item", "Edit value:", initialvalue=old_value)
        if new_value is None:
            return
        tree.item(selected[0], values=(new_key, new_value))
    
    def remove_object_item(self, key):
        tree = self.object_widgets[key]
        selected = tree.selection()
        if not selected:
            messagebox.showerror("Error", "Please select an item to remove.")
            return
        tree.delete(selected[0])
    
    def save_config_changes(self, editor_window):
        """Gather values from all tabs and update the config file."""
        # Update general settings:
        for key, var in self.general_vars.items():
            value = var.get()
            orig = self.config_data.get(key)
            if isinstance(orig, bool):
                self.config_data[key] = bool(value)
            elif isinstance(orig, (int, float)):
                try:
                    if isinstance(orig, int):
                        self.config_data[key] = int(value)
                    else:
                        self.config_data[key] = float(value)
                except ValueError:
                    self.config_data[key] = value
            else:
                self.config_data[key] = value
        # Update array settings:
        for key, listbox in self.array_widgets.items():
            self.config_data[key] = list(listbox.get(0, tk.END))
        # Update object settings:
        for key, tree in self.object_widgets.items():
            new_obj = {}
            for item in tree.get_children():
                vals = tree.item(item)["values"]
                if len(vals) >= 2:
                    new_obj[vals[0]] = vals[1]
            self.config_data[key] = new_obj
        save_config(self.config_data)
        # Update the program path display if needed.
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
            # Store the absolute path to ensure it works in all contexts
            abs_path = os.path.abspath(filepath)
            self.program_path_var.set(abs_path)
            self.config_data["program_path"] = abs_path
            save_config(self.config_data)
            print(f"Program path updated to: {abs_path}")
    
    def launch_program(self):
        # Stop any existing process and thread
        self.terminate_program()
        
        # Use the stored program path from config (should be absolute path)
        target = self.config_data.get("program_path", "")
        
        if not target or not os.path.exists(target):
            messagebox.showerror("Error", f"Invalid target program path: '{target}'\nPlease set a valid path in the configuration.")
            return
        
        # Clear terminal output
        self.terminal_output.delete(1.0, tk.END)
        print(f"Launching: {target}")
        
        try:
            # Setup subprocess with appropriate arguments
            startupinfo = None
            creation_flags = 0
            
            # Windows-specific settings to hide console
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0  # SW_HIDE
                creation_flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            
            # Prepare command based on target type
            if target.endswith(".py"):
                if getattr(sys, 'frozen', False):
                    # If we're running as an executable, we need to use python
                    cmd = ["python", "-u", target]
                else:
                    # If we're running as a script, use the current Python interpreter
                    cmd = [sys.executable, "-u", target]
            else:
                cmd = [target]
            
            print(f"Running command: {cmd}")
                
            # Start the process with explicit pipe redirection
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                bufsize=1,  # Line buffered
                universal_newlines=False,  # We'll handle decoding manually
                creationflags=creation_flags,
                startupinfo=startupinfo,
                cwd=os.path.dirname(target)  # Set working directory to target's directory
            )
            
            # Reset thread control flag
            self.stop_thread = False
            
            # Create and start output reading thread
            self.read_thread = threading.Thread(target=self.read_process_output)
            self.read_thread.daemon = True
            self.read_thread.start()
            
            # Enable terminate button
            self.terminate_button.config(state=tk.NORMAL)
                
        except Exception as e:
            messagebox.showerror("Error", f"Failed to launch program: {e}")
            print(f"Error launching program: {e}")
    
    def read_process_output(self):
        """Read process output and update the terminal."""
        if not self.process:
            return
            
        print("Output reader thread started")
        
        try:
            while self.process and not self.stop_thread:
                # Check if process has terminated
                if self.process.poll() is not None:
                    break
                    
                # Read output in binary mode and decode it
                try:
                    output = self.process.stdout.read(1)
                    if output:
                        try:
                            text = output.decode('utf-8', errors='replace')
                            # Update terminal on main thread
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
        """Append text to terminal (called on main thread)."""
        try:
            self.terminal_output.insert(tk.END, text)
            self.terminal_output.see(tk.END)
        except Exception as e:
            print(f"Terminal update error: {e}")
    
    def _process_ended(self, exit_code):
        """Handle process termination (called on main thread)."""
        self.process = None
        self.terminate_button.config(state=tk.DISABLED)
        print(f"Process terminated with exit code: {exit_code}")
    
    def terminate_program(self):
        """Terminate the running process and cleanup."""
        self.stop_thread = True
        
        if self.process:
            try:
                self.process.terminate()
                try:
                    self.process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    if self.process:
                        self.process.kill()
            except Exception as e:
                print(f"Error terminating process: {e}")
                
            self.process = None
            self.terminate_button.config(state=tk.DISABLED)
            print("Process terminated by user")
            
        if self.read_thread and self.read_thread.is_alive():
            self.read_thread.join(timeout=1)
            self.read_thread = None

class ConsoleRedirector:
    """Redirects stdout to a Tkinter Text widget."""
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
