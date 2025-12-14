import tkinter as tk
from tkinter import messagebox
import json

class TriggerEditor:
    def __init__(self, parent, triggers_list, on_update):
        self.window = tk.Toplevel(parent)
        self.window.title("Manage Triggers")
        self.window.geometry("700x500")
        self.window.grab_set()  # Modal window
        
        self.triggers = []
        # Deep copy to allow cancelling
        for t in triggers_list:
            self.triggers.append(t.copy())
            
        self.on_update = on_update
        self.selected_index = None

        # --- Layout ---
        # Main container with two panes
        paned = tk.PanedWindow(self.window, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Left: List Selection
        left_frame = tk.Frame(paned)
        paned.add(left_frame, minsize=200)

        tk.Label(left_frame, text="Triggers List").pack(anchor=tk.W)
        
        self.listbox = tk.Listbox(left_frame)
        self.listbox.pack(fill=tk.BOTH, expand=True, pady=5)
        self.listbox.bind("<<ListboxSelect>>", self.on_select)

        btn_frame = tk.Frame(left_frame)
        btn_frame.pack(fill=tk.X)
        tk.Button(btn_frame, text="Add New", command=self.add_trigger).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        tk.Button(btn_frame, text="Delete", command=self.delete_trigger).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        # Right: Editing Form
        right_frame = tk.Frame(paned)
        paned.add(right_frame, minsize=400)

        tk.Label(right_frame, text="Trigger Details", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, pady=(0, 10))

        # Phrases
        tk.Label(right_frame, text="Phrases (comma-separated):").pack(anchor=tk.W)
        self.phrases_text = tk.Text(right_frame, height=4, width=40)
        self.phrases_text.pack(fill=tk.X, pady=(0, 10))
        self.phrases_text.bind("<<Modified>>", self.on_field_change)

        # URL
        tk.Label(right_frame, text="Target URL:").pack(anchor=tk.W)
        self.url_var = tk.StringVar()
        self.url_var.trace_add("write", self.on_field_change)
        tk.Entry(right_frame, textvariable=self.url_var).pack(fill=tk.X, pady=(0, 10))

        # Cooldown
        tk.Label(right_frame, text="Cooldown (seconds):").pack(anchor=tk.W)
        self.cooldown_var = tk.StringVar(value="2.0")
        self.cooldown_var.trace_add("write", self.on_field_change)
        tk.Entry(right_frame, textvariable=self.cooldown_var).pack(fill=tk.X, pady=(0, 10))

        # Bottom: Actions
        bottom_frame = tk.Frame(self.window)
        bottom_frame.pack(fill=tk.X, padx=10, pady=10)
        
        tk.Button(bottom_frame, text="Save & Close", command=self.save_and_close, bg="#007acc", fg="white", width=15).pack(side=tk.RIGHT)
        tk.Button(bottom_frame, text="Cancel", command=self.window.destroy, width=10).pack(side=tk.RIGHT, padx=10)

        self.ignore_changes = False
        self.refresh_list()
        
        if self.triggers:
            self.listbox.selection_set(0)
            self.on_select(None)

    def refresh_list(self):
        selected_idx = self.listbox.curselection()
        
        self.listbox.delete(0, tk.END)
        for i, t in enumerate(self.triggers):
            phrases = t.get("phrases", [])
            preview = ", ".join(phrases) if phrases else "(No phrases)"
            if len(preview) > 30: preview = preview[:27] + "..."
            self.listbox.insert(tk.END, f"#{i+1}: {preview}")
            
        if selected_idx and selected_idx[0] < len(self.triggers):
             self.listbox.selection_set(selected_idx[0])

    def on_select(self, event):
        sel = self.listbox.curselection()
        if not sel:
            self.clear_form()
            self.disable_form()
            self.selected_index = None
            return

        idx = sel[0]
        self.selected_index = idx
        trigger = self.triggers[idx]
        
        self.ignore_changes = True
        self.enable_form()
        
        # Populate fields
        self.phrases_text.delete("1.0", tk.END)
        self.phrases_text.insert("1.0", ", ".join(trigger.get("phrases", [])))
        
        self.url_var.set(trigger.get("url", ""))
        self.cooldown_var.set(str(trigger.get("cooldown", 2.0)))
        
        self.phrases_text.edit_modified(False)
        self.ignore_changes = False

    def on_field_change(self, *args):
        if self.ignore_changes or self.selected_index is None:
            return
            
        # If modifying text widget, we need to reset the modified flag
        if self.phrases_text.edit_modified():
            self.phrases_text.edit_modified(False)

        # Update the model immediately
        idx = self.selected_index
        
        # Phrases
        raw_phrases = self.phrases_text.get("1.0", tk.END).strip()
        phrases_list = [p.strip() for p in raw_phrases.split(",") if p.strip()]
        self.triggers[idx]["phrases"] = phrases_list
        
        # URL
        self.triggers[idx]["url"] = self.url_var.get().strip()
        
        # Cooldown
        try:
            val = float(self.cooldown_var.get())
            self.triggers[idx]["cooldown"] = val
        except ValueError:
            pass # Ignore invalid float for now

        # Don't full refresh list on every keypress, but maybe update label?
        # A full refresh clears selection which is annoying.
        # Just update the Listbox text for this item
        preview = ", ".join(phrases_list) if phrases_list else "(No phrases)"
        if len(preview) > 30: preview = preview[:27] + "..."
        self.listbox.delete(idx)
        self.listbox.insert(idx, f"#{idx+1}: {preview}")
        self.listbox.selection_set(idx)

    def add_trigger(self):
        new_trigger = {
            "phrases": ["new phrase"],
            "url": "",
            "cooldown": 2.0
        }
        self.triggers.append(new_trigger)
        self.refresh_list()
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(tk.END)
        self.listbox.see(tk.END)
        self.on_select(None)

    def delete_trigger(self):
        sel = self.listbox.curselection()
        if not sel: return
        
        idx = sel[0]
        del self.triggers[idx]
        self.refresh_list()
        
        if self.triggers:
            new_idx = min(idx, len(self.triggers) - 1)
            self.listbox.selection_set(new_idx)
            self.on_select(None)
        else:
            self.on_select(None)

    def clear_form(self):
        self.ignore_changes = True
        self.phrases_text.delete("1.0", tk.END)
        self.url_var.set("")
        self.cooldown_var.set("")
        self.ignore_changes = False

    def disable_form(self):
        self.phrases_text.config(state=tk.DISABLED, bg="#f0f0f0")
        # Entry widgets don't have a simple style toggle like Text, just disable
        # To make it cleaner, we could iterate children of right_frame, but this is fine
        pass 

    def enable_form(self):
        self.phrases_text.config(state=tk.NORMAL, bg="white")

    def save_and_close(self):
        if self.on_update:
            self.on_update(self.triggers)
        self.window.destroy()
