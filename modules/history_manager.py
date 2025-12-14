import os
import time
import threading
import re
from datetime import datetime, timedelta

HISTORY_PRUNE_LOCK = threading.Lock()
ONE_HOUR_IN_SECONDS = 3600

def parse_timestamp_robust(line):
    """
    Parses timestamp matching format: [Name HH:MM:SS] Text
    Uses regex to be robust against name changes.
    Matches: [anything HH:MM:SS]
    """
    try:
        # Regex to find timestamp in brackets: "[<Anything> HH:MM:SS]"
        # Non-greedy match for name part, then space, then time
        match = re.search(r"\[.*? (\d{2}:\d{2}:\d{2})\]", line)
        if match:
            time_str = match.group(1)
            log_time_obj = datetime.strptime(time_str, "%H:%M:%S").time()
            
            now_dt = datetime.now()
            log_dt_assumed_today = datetime.combine(now_dt.date(), log_time_obj)
            
            # Helper logic for midnight rollover (simple heuristic)
            if log_dt_assumed_today > now_dt:
                return datetime.combine(now_dt.date() - timedelta(days=1), log_time_obj)
            else:
                return log_dt_assumed_today
    except Exception:
        pass
    return None

def prune_transcript_history(history_file_path, max_age_seconds=ONE_HOUR_IN_SECONDS):
    with HISTORY_PRUNE_LOCK:
        if not os.path.exists(history_file_path): return
        try:
            with open(history_file_path, "r", encoding="utf-8") as hf: lines = hf.readlines()
        except Exception as e: print(f"Error reading history file for pruning {history_file_path}: {e}"); return
        if not lines: return

        cutoff_time = datetime.now() - timedelta(seconds=max_age_seconds)
        valid_lines = []
        pruned_count = 0
        for line in lines:
            timestamp = parse_timestamp_robust(line)
            if timestamp:
                if timestamp >= cutoff_time:
                    valid_lines.append(line)
                else:
                    pruned_count += 1
            else:
                # Keep lines we can't parse or don't look like timestamps (safe default)
                valid_lines.append(line) 
        
        if pruned_count > 0 or len(valid_lines) < len(lines):
            try:
                with open(history_file_path, "w", encoding="utf-8") as hf: hf.writelines(valid_lines)
                if pruned_count > 0: print(f"Pruned {pruned_count} old entries from {history_file_path}.")
            except Exception as e: print(f"Error writing pruned history file {history_file_path}: {e}")

def append_to_transcript_history(transcript_text, history_file_path, prefix="Oshimia"):
    if not transcript_text or not transcript_text.strip(): return
    
    # Format: [Prefix HH:MM:SS] Text
    time_str = time.strftime("%H:%M:%S", time.localtime())
    log_entry = f"[{prefix} {time_str}] {transcript_text}"
    
    try:
        with open(history_file_path, "a", encoding="utf-8") as hf: hf.write(log_entry + "\n")
        prune_transcript_history(history_file_path, ONE_HOUR_IN_SECONDS)
    except Exception as e: print(f"Error appending to or pruning transcript history {history_file_path}: {e}")
