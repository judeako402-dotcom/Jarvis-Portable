import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from config import REMINDERS_FILE, DATA_DIR

_log = logging.getLogger("reminders")


class ReminderScheduler:
    def __init__(self, speak_callback=None):
        self._file = REMINDERS_FILE
        self._reminders = []
        self._lock = threading.Lock()
        self._running = True
        self._speak = speak_callback or print
        os.makedirs(DATA_DIR, exist_ok=True)
        self._load()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _load(self):
        try:
            if os.path.exists(self._file):
                with open(self._file, "r") as f:
                    self._reminders = json.load(f)
        except Exception:
            self._reminders = []

    def _save(self):
        try:
            with open(self._file, "w") as f:
                json.dump(self._reminders, f, indent=2)
        except (IOError, OSError, PermissionError) as e:
            _log.error(f"Failed to save reminders: {e}")

    def add(self, text, delay_secs=0, when=None):
        if when:
            due = when
        else:
            due = (datetime.now() + timedelta(seconds=delay_secs)).isoformat()
        reminder = {"text": text, "due": due, "active": True}
        with self._lock:
            self._reminders.append(reminder)
            self._save()
        return reminder

    def add_timer(self, text, seconds):
        return self.add(text, delay_secs=seconds)

    def list_active(self):
        with self._lock:
            return [r for r in self._reminders if r.get("active")]

    def remove(self, index):
        with self._lock:
            if 0 <= index < len(self._reminders):
                self._reminders[index]["active"] = False
                self._save()
                return True
        return False

    def clear_expired(self):
        with self._lock:
            now = datetime.now()
            self._reminders = [
                r for r in self._reminders
                if r.get("active") and datetime.fromisoformat(r["due"]) > now
            ]
            self._save()

    def _loop(self):
        while self._running:
            now = datetime.now()
            with self._lock:
                for r in self._reminders:
                    if not r.get("active"):
                        continue
                    try:
                        due = datetime.fromisoformat(r["due"])
                        if due <= now:
                            r["active"] = False
                            t = threading.Thread(target=self._speak, args=(f"Reminder: {r['text']}",), daemon=True)
                            t.start()
                    except Exception:
                        continue
                self._save()
            time.sleep(5)

    def stop(self):
        self._running = False
