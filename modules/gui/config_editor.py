import tkinter as tk
from tkinter import messagebox
import json
from modules.config_manager import save_config
from modules.gui.utils import update_text_wrap
from modules.gui.trigger_editor import TriggerEditor

class ConfigEditor:
    def __init__(self, parent_window, config_data, on_save_callback):
        self.parent = parent_window
        self.config_data = config_data
        self.on_save = on_save_callback

        self.editor = tk.Toplevel(self.parent)
        self.editor.title("Edit Configuration")
        self.editor.geometry("700x500")

        # Create a container with a canvas and scrollbar for complete scrolling.
        container = tk.Frame(self.editor)
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
            # On Windows, event.delta is a multiple of 120
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        # Bind the mouse wheel to the canvas for the entire area.
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        self.editor.protocol("WM_DELETE_WINDOW", lambda: [canvas.unbind_all("<MouseWheel>"), self.editor.destroy()])

        # Dictionaries to keep track of input widget references.
        self.general_vars = {}   # For booleans, ints, floats using StringVar/BooleanVar.
        self.text_widgets = {}   # For multi-line strings, lists, and dicts.

        # Define key ordering and visibility
        priority_keys = ['triggers', 'ENABLE_HISTORY', 'HISTORY_LOG_PREFIX', 'WHISPER_HISTORY_FILE']
        hidden_keys = ['trigger_words', 'TRIGGER_URL', 'URL_CALL_COOLDOWN', 'program_path', 'auto_launch', 'running', 'termination_triggered', 'last_url_call_time']

        # Sort keys: priority first, then others alphabetically, excluding hidden
        sorted_keys = []
        # 1. Add priority keys if they exist
        for key in priority_keys:
            if key in self.config_data:
                sorted_keys.append(key)
        
        # 2. Add remaining keys if not hidden and not already added
        remaining_keys = sorted(self.config_data.keys())
        for key in remaining_keys:
            if key not in sorted_keys and key not in hidden_keys:
                sorted_keys.append(key)

        row = 0
        for key in sorted_keys:
            value = self.config_data[key]
            tk.Label(form_frame, text=f"{key}:").grid(row=row, column=0, sticky=tk.NW, padx=5, pady=5)
            
            if key == "triggers":
                 # Special handling for triggers list
                 count = len(value) if isinstance(value, list) else 0
                 btn_text = f"Manage Triggers ({count})"
                 tk.Button(form_frame, text=btn_text, command=self.open_trigger_editor).grid(row=row, column=1, sticky=tk.W, padx=5, pady=5)
                 
            elif isinstance(value, bool):
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

        bottom_frame = tk.Frame(self.editor)
        bottom_frame.pack(fill=tk.X, padx=10, pady=10)
        tk.Button(bottom_frame, text="Save", command=self.save_config_changes,
                  fg="white", bg="blue").pack(side=tk.RIGHT, padx=5)
        tk.Button(bottom_frame, text="Close", command=self.editor.destroy).pack(side=tk.RIGHT, padx=5)


    def open_trigger_editor(self):
        triggers = self.config_data.get("triggers", [])
        TriggerEditor(self.editor, triggers, self.update_triggers_data)

    def update_triggers_data(self, new_triggers_list):
        self.config_data["triggers"] = new_triggers_list
        # Save immediately as requested
        save_config(self.config_data)
        # Notify user briefly or just log
        print(f"Triggers updated and saved: {len(new_triggers_list)} rules.")


    def save_config_changes(self):
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

        # Unbind mousewheel handlers to prevent errors on close
        for widget in self.editor.winfo_children():
            if isinstance(widget, tk.Frame):
                for child in widget.winfo_children():
                    if isinstance(child, tk.Canvas):
                        child.unbind_all("<MouseWheel>")

        save_config(self.config_data)
        messagebox.showinfo("Info", "Configuration saved successfully.")
        
        if self.on_save:
            self.on_save(self.config_data)
        
        self.editor.destroy()
