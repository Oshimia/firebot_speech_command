import tkinter as tk
import tkinter.font as tkFont

class ConsoleRedirector:
    def __init__(self, text_widget):
        self.text_widget = text_widget

    def write(self, s):
        self.text_widget.insert(tk.END, s)
        self.text_widget.see(tk.END)

    def flush(self):
        pass

def update_text_wrap(event, text_widget):
    # Get the font used by the text widget.
    try:
        font = tkFont.Font(font=text_widget.cget("font"))
        # Estimate the average pixel width of a character (using "0" as a sample).
        avg_char_width = font.measure("0")
        # Compute the new number of characters that can fit in the widget's current width.
        new_width = max(20, int(text_widget.winfo_width() / avg_char_width))
        text_widget.config(width=new_width)
    except Exception:
        pass
