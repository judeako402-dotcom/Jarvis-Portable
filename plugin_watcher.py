import os
import sys
import time
import threading
import importlib
from pathlib import Path
from config import PLUGINS_DIR


class PluginWatcher:
    def __init__(self, handler, interval=3):
        self._handler = handler
        self._dir = Path(PLUGINS_DIR)
        self._interval = interval
        self._mtimes = {}
        self._loaded = set()
        self._known_files = set()
        self._running = True
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()

    def _watch(self):
        while self._running:
            if self._dir.exists():
                current = set()
                for fpath in self._dir.glob("*.py"):
                    if fpath.name.startswith("_"):
                        continue
                    current.add(fpath.name)
                    mtime = fpath.stat().st_mtime
                    prev = self._mtimes.get(fpath.name)
                    if prev is None:
                        self._mtimes[fpath.name] = mtime
                    elif mtime > prev:
                        self._mtimes[fpath.name] = mtime
                        self._reload(fpath)
                removed = self._known_files - current
                for name in removed:
                    self._unload(name)
                self._known_files = current
            time.sleep(self._interval)

    def _reload(self, fpath):
        name = fpath.stem
        print(f"[WATCHER] Reloading plugin: {name}")
        try:
            if name in sys.modules:
                del sys.modules[name]
            spec = importlib.util.spec_from_file_location(name, fpath)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if hasattr(mod, "register"):
                mod.register(self._handler)
                print(f"[WATCHER] Reloaded {name}")
        except Exception as e:
            print(f"[WATCHER] Failed to reload {name}: {e}")

    def _unload(self, name):
        stem = name.replace(".py", "")
        print(f"[WATCHER] Plugin file removed: {stem}")
        if stem in sys.modules:
            del sys.modules[stem]
        keys = list(self._handler._custom_commands.keys())
        for k in keys:
            if k.startswith(stem):
                del self._handler._custom_commands[k]

    def stop(self):
        self._running = False
