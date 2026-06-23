from datetime import datetime
import webbrowser
import subprocess
import os
import glob as globmod
import shutil
import re
import threading
import time
import json
from pathlib import Path

import psutil
import pyautogui
import pywhatkit
import wikipedia
import pyjokes
import requests

from urllib.parse import quote as url_encode
try:
    import pyperclip
    HAS_PYPERCLIP = True
except ImportError:
    HAS_PYPERCLIP = False

import importlib

from config import (
    APP_MAP, GITHUB_TOKEN, GITHUB_USERNAME, DEFAULT_WORKSPACE, MAX_READ_LINES,
    LLM_BACKEND, LLM_MODEL, GEMINI_API_KEY, OPENAI_API_KEY, OPENAI_MODEL,
    ANTHROPIC_API_KEY, ANTHROPIC_MODEL, CONVERSATION_MODE, MAX_CONTEXT_TURNS,
    NOTES_DIR, HASS_URL, HASS_TOKEN, BASE_DIR,
    OPENROUTER_API_KEY, OPENROUTER_MODEL, OPENROUTER_FALLBACK_MODEL, OPENROUTER_BASE, AI_ROUTER,
    VISION_ENABLED, VISION_MODEL, MEMORY_ENABLED, FACTS_FILE,
    SELF_IMPROVEMENT_ENABLED, IMPROVEMENT_MAX_PENDING,
)


class CommandHandler:
    def __init__(self, voice_engine, memory=None, visualizer=None, speak_callback=None):
        self.voice = voice_engine
        self.memory = memory
        self.viz = visualizer
        self._speak_callback = speak_callback
        self._custom_commands = {}
        self._workspace = DEFAULT_WORKSPACE
        self._response_queue = []
        self._response_lock = threading.Lock()
        self.self_improvement = None
        os.makedirs(NOTES_DIR, exist_ok=True)
        from reminders import ReminderScheduler
        self._reminder_scheduler = ReminderScheduler(speak_callback=self.speak)

    def push_response(self, text):
        with self._response_lock:
            self._response_queue.append(text.strip().lower())

    def get_response(self, timeout=5):
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._response_lock:
                if self._response_queue:
                    return self._response_queue.pop(0)
            time.sleep(0.1)
        return ""

    def speak(self, text, enable_barge_in=True):
        print(f"[JARVIS] {text}")
        completed = self.voice.speak(text, enable_barge_in=enable_barge_in)
        if self._speak_callback:
            self._speak_callback(text, "jarvis")
        if self.viz:
            self.viz.add_text(f"Jarvis: {text}", "jarvis")
        if self.memory:
            self.memory.add("jarvis", text)
        return completed

    def command(self, name, patterns=None):
        def decorator(func):
            self._custom_commands[name] = {"func": func, "patterns": patterns or []}
            return func
        return decorator

    def handle(self, intent, entity, extra=""):
        if intent == "help":
            self._intent_help()
            return
        if intent in self._custom_commands:
            return self._custom_commands[intent]["func"](entity)
        handler = getattr(self, f"_intent_{intent}", None)
        if handler:
            return handler(entity, extra)
        if intent == "unknown" and entity:
            enhanced = self._build_context(entity)
            answer = self._ask_llm(enhanced, system="You are Jarvis. Answer concisely and accurately.")
            if answer:
                self.speak(answer[:500])
            else:
                self._intent_search(entity)
            return
        self.speak("I'm not sure how to do that yet. You can ask me to open apps, search the web, manage files, or control your system.")

    def _run_git(self, args, cwd=None):
        try:
            result = subprocess.run(
                ["git"] + args, capture_output=True, text=True,
                cwd=cwd or self._workspace, timeout=30,
            )
            return result.stdout.strip(), result.stderr.strip(), result.returncode
        except Exception as e:
            return "", str(e), 1

    def _github_api(self, endpoint, method="GET", data=None):
        if not GITHUB_TOKEN:
            return None, "GitHub token not configured. Set GITHUB_TOKEN environment variable."
        headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
        url = f"https://api.github.com{endpoint}"
        try:
            if method == "GET":
                resp = requests.get(url, headers=headers, timeout=10)
            elif method == "POST":
                resp = requests.post(url, headers=headers, json=data, timeout=10)
            else:
                return None, "Unsupported method"
            return resp.json() if resp.text else {}, resp.status_code
        except Exception as e:
            return None, str(e)

    def _confirm(self, message):
        self.speak(message)
        response = self.get_response(timeout=8)
        return response in ["yes", "y", "confirm", "do it", "yeah", "sure", "ok", "okay"]

    def _intent_open_app(self, app_name, _=""):
        if not app_name:
            self.speak("What application should I open?")
            return
        for key, value in APP_MAP.items():
            if key in app_name:
                try:
                    if isinstance(value, list):
                        subprocess.Popen(value, shell=True)
                    elif value.startswith("ms-"):
                        subprocess.Popen(["start", value], shell=True)
                    else:
                        subprocess.Popen(value, shell=True)
                    self.speak(f"Done sir. {key} is now open.")
                except Exception as e:
                    self.speak(f"Sorry sir, I couldn't open {key}. {e}")
                return
        self.speak(f"I don't have {app_name} in my app list. I'll try opening it from the Start menu.")
        try:
            subprocess.Popen(["start", app_name], shell=True)
        except Exception:
            self.speak(f"Failed to open {app_name}.")

    def _intent_close_app(self, app_name, _=""):
        if not app_name:
            self.speak("What application should I close?")
            return
        for proc in psutil.process_iter(["name"]):
            try:
                if proc.info["name"] and app_name.lower() in proc.info["name"].lower():
                    proc.terminate()
                    self.speak(f"Done sir. {app_name} has been closed.")
                    return
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        self.speak(f"I couldn't find {app_name} running.")

    def _intent_search(self, query, _=""):
        if not query:
            self.speak("What would you like me to search for?")
            return
        self.speak(f"Searching for {query}.")
        summary = self._get_wikipedia_summary(query)
        if summary:
            self.speak(f"Here's what I found: {summary}")
        else:
            self._scrape_and_read(query)

    def _intent_wikipedia(self, query, _=""):
        if not query:
            self.speak("What would you like me to search on Wikipedia?")
            return
        summary = self._get_wikipedia_summary(query)
        if summary:
            self.speak(f"According to Wikipedia: {summary}")
        else:
            self.speak(f"I couldn't find {query} on Wikipedia.")

    def _get_wikipedia_summary(self, query):
        try:
            return wikipedia.summary(query, sentences=2)
        except wikipedia.exceptions.DisambiguationError as e:
            self.speak(f"Multiple results found. Options: {', '.join(e.options[:3])}")
            return None
        except wikipedia.exceptions.PageError:
            return None
        except Exception:
            return None

    def _duckduckgo_search(self, query):
        try:
            resp = requests.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
                timeout=8,
            )
            data = resp.json()
            abstract = data.get("AbstractText", "")
            if abstract:
                return abstract
            answer = data.get("Answer", "")
            if answer:
                return answer
            related = data.get("RelatedTopics", [])
            for topic in related[:3]:
                if "Text" in topic:
                    return topic["Text"]
            return None
        except Exception:
            return None

    def _scrape_and_read(self, query):
        summary = self._duckduckgo_search(query)
        if summary:
            self.speak(f"Here's what I found: {summary[:600]}")
        else:
            self.speak(f"I found some results. Opening the browser for you.")
            webbrowser.open(f"https://duckduckgo.com/?q={query}")

    def _intent_play_youtube(self, query, _=""):
        if not query:
            self.speak("What would you like me to play?")
            return
        self.speak(f"Playing {query} on YouTube now, sir.")
        pywhatkit.playonyt(query)

    def _intent_time(self, _1="", _2=""):
        now = datetime.now().strftime("%I:%M %p")
        self.speak(f"The time is {now}, sir.")

    def _intent_date(self, _1="", _2=""):
        today = datetime.now().strftime("%A, %B %d, %Y")
        self.speak(f"Today is {today}.")

    def _intent_screenshot(self, _1="", _2=""):
        os.makedirs(os.path.join(os.path.expanduser("~"), "Pictures", "Screenshots"), exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        path = os.path.join(os.path.expanduser("~"), "Pictures", "Screenshots", f"screenshot_{ts}.png")
        pyautogui.screenshot().save(path)
        self.speak(f"Done sir. Screenshot saved to {path}.")

    def _intent_joke(self, _1="", _2=""):
        self.speak(pyjokes.get_joke())

    def _intent_cpu(self, _1="", _2=""):
        usage = psutil.cpu_percent(interval=1)
        self.speak(f"CPU usage is at {usage} percent, sir.")

    def _intent_ram(self, _1="", _2=""):
        mem = psutil.virtual_memory()
        gb = mem.available // (1024**3)
        self.speak(f"Memory usage is {mem.percent} percent. {gb} gigabytes available out of {mem.total // (1024**3)}.")

    def _intent_battery(self, _1="", _2=""):
        battery = psutil.sensors_battery()
        if battery:
            plug = "plugged in" if battery.power_plugged else "on battery power"
            self.speak(f"Battery is at {battery.percent} percent, {plug}.")
        else:
            self.speak("No battery detected. This appears to be a desktop system.")

    def _intent_volume_up(self, _1="", _2=""):
        for _ in range(5):
            pyautogui.press("volumeup")
        self.speak("Done sir. Volume increased.")

    def _intent_volume_down(self, _1="", _2=""):
        for _ in range(5):
            pyautogui.press("volumedown")
        self.speak("Done sir. Volume decreased.")

    def _intent_mute(self, _1="", _2=""):
        pyautogui.press("volumemute")
        self.speak("Done sir. Volume muted.")

    def _intent_shutdown(self, _1="", _2=""):
        if self._confirm("This will shut down the computer. Are you sure?"):
            self.speak("Shutting down the system. Goodbye sir.")
            os.system("shutdown /s /t 5")
        else:
            self.speak("Shutdown cancelled. Your work is safe.")

    def _intent_restart(self, _1="", _2=""):
        if self._confirm("This will restart the computer. Are you sure?"):
            self.speak("Restarting now. I'll be back in a moment.")
            os.system("shutdown /r /t 5")
        else:
            self.speak("Restart cancelled.")

    def _intent_greeting(self, _1="", _2=""):
        hour = datetime.now().hour
        if hour < 12:
            self.speak("Good morning, sir. I hope you're well. How can I help you today?")
        elif hour < 17:
            self.speak("Good afternoon, sir. What can I do for you?")
        else:
            self.speak("Good evening, sir. Ready when you are.")

    def _intent_identity(self, _1="", _2=""):
        self.speak("I am Jarvis, your personal AI assistant. I can control your computer, manage your files, interact with GitHub, search the web, and much more. Think of me as your digital right hand, sir.")

    def _intent_weather(self, city="", _=""):
        try:
            if not city:
                ip = requests.get("https://ipinfo.io/json", timeout=5).json()
                city = ip.get("city", "New York")
            resp = requests.get(f"https://wttr.in/{city}?format=%C+%t+%h+%w", timeout=5)
            if resp.status_code == 200:
                self.speak(f"Weather in {city}: {resp.text.strip()}")
            else:
                self.speak("I couldn't get the weather right now.")
        except Exception:
            self.speak("I couldn't reach the weather service.")

    def _intent_goodbye(self, _1="", _2=""):
        self.speak("Goodbye sir. I'll be right here when you need me.")
        return "exit"

    def _intent_thank(self, _1="", _2=""):
        self.speak("You're welcome, sir. Always a pleasure to help.")

    # ── GitHub Commands ──────────────────────────────────────────────

    def _intent_github_status(self, _1="", _2=""):
        stdout, stderr, code = self._run_git(["status"])
        if code == 0:
            self.speak(f"Done sir. Git status: {stdout[:300]}")
        else:
            self.speak(f"Git error: {stderr or stdout}")

    def _intent_github_push(self, message="", _=""):
        if not GITHUB_TOKEN:
            self.speak("GitHub token not set. Set the GITHUB_TOKEN environment variable first.")
            return
        self.speak("Preparing to push to GitHub.")
        stdout, stderr, code = self._run_git(["add", "-A"])
        if code != 0:
            self.speak(f"Failed to stage files: {stderr}")
            return
        commit_msg = message or f"Update via Jarvis at {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        stdout, stderr, code = self._run_git(["commit", "-m", commit_msg])
        if code != 0 and "nothing to commit" not in (stdout + stderr).lower():
            self.speak(f"Commit failed: {stderr}")
            return
        stdout, stderr, code = self._run_git(["push"])
        if code == 0:
            self.speak("Done sir. Successfully pushed to GitHub.")
        else:
            self.speak(f"Push failed: {stderr}")

    def _intent_github_pull(self, _1="", _2=""):
        self.speak("Pulling latest changes from GitHub.")
        stdout, stderr, code = self._run_git(["pull"])
        if code == 0:
            self.speak(f"Done sir. Pull complete. {stdout[:200]}")
        else:
            self.speak(f"Pull failed: {stderr}")

    def _intent_github_clone(self, url, _=""):
        if not url:
            self.speak("What repository URL should I clone?")
            return
        self.speak(f"Cloning {url} now.")
        stdout, stderr, code = self._run_git(["clone", url])
        if code == 0:
            repo_name = url.rstrip("/").split("/")[-1].replace(".git", "")
            self._workspace = os.path.join(self._workspace, repo_name)
            self.speak(f"Done sir. Repository cloned. Working directory set to {repo_name}.")
        else:
            self.speak(f"Clone failed: {stderr}")

    def _intent_github_create_repo(self, name, _=""):
        if not name:
            self.speak("What should I name the repository?")
            return
        if not GITHUB_TOKEN:
            self.speak("GitHub token not set. Set the GITHUB_TOKEN environment variable.")
            return
        self.speak(f"Creating repository {name} on GitHub.")
        data = {"name": name, "auto_init": True, "private": False}
        result, status = self._github_api("/user/repos", method="POST", data=data)
        if status == 201:
            self.speak(f"Done sir. Repository {name} created. URL: {result.get('html_url', '')}")
        elif status == 422:
            self.speak(f"Repository {name} already exists on your account.")
        else:
            self.speak(f"Failed to create repository: {result}")

    def _intent_github_list_repos(self, _1="", _2=""):
        if not GITHUB_TOKEN:
            self.speak("GitHub token not set.")
            return
        user = GITHUB_USERNAME or "user"
        result, status = self._github_api(f"/users/{user}/repos?sort=updated&per_page=10")
        if status == 200 and isinstance(result, list):
            if not result:
                self.speak("You don't have any repositories yet.")
                return
            names = [r["name"] for r in result[:10]]
            self.speak(f"Your recent repositories: {', '.join(names)}.")
        else:
            self.speak("Couldn't fetch your repositories.")

    def _intent_github_commit(self, message="", _=""):
        if not message:
            self.speak("What commit message should I use?")
            return
        self.speak("Committing changes now.")
        stdout, stderr, code = self._run_git(["add", "-A"])
        stdout, stderr, code = self._run_git(["commit", "-m", message])
        if code == 0:
            self.speak(f"Done sir. Committed: {message}")
        else:
            self.speak(f"Commit failed: {stderr}")

    # ── File System Commands ─────────────────────────────────────────

    def _intent_list_files(self, path="", _=""):
        target = path if path else self._workspace
        target = os.path.expanduser(target)
        if not os.path.isdir(target):
            self.speak(f"Directory not found: {target}")
            return
        items = os.listdir(target)
        if not items:
            self.speak(f"The directory {os.path.basename(target)} is empty, sir.")
            return
        dirs = sorted([d for d in items if os.path.isdir(os.path.join(target, d))])
        files = sorted([f for f in items if os.path.isfile(os.path.join(target, f))])
        parts = []
        if dirs:
            parts.append(f"{len(dirs)} folders")
        if files:
            parts.append(f"{len(files)} files")
        listing = ", ".join(parts) + "."
        if len(items) <= 15:
            listing += f" Contents: {', '.join(items[:15])}"
        self.speak(f"Done sir. In {os.path.basename(target) or 'current directory'}: {listing}")

    def _intent_read_file(self, filename, _=""):
        if not filename:
            self.speak("Which file should I read, sir?")
            return
        filepath = os.path.join(self._workspace, filename)
        if not os.path.isfile(filepath):
            self.speak(f"File not found: {filename}. Would you like me to search for it?")
            return
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()[:MAX_READ_LINES]
            content = "".join(lines)
            self.speak(f"Done sir. Reading {filename}.")
            self.speak(content[:800])
            if len(lines) >= MAX_READ_LINES:
                self.speak(f"That's the first {MAX_READ_LINES} lines. The file may be longer.")
        except Exception as e:
            self.speak(f"Error reading file: {e}")

    def _intent_write_file(self, filename, content="", _=""):
        if not filename:
            self.speak("What should I name the file, sir?")
            return
        filepath = os.path.join(self._workspace, filename)
        if os.path.exists(filepath):
            if not self._confirm(f"{filename} already exists. Should I overwrite it?"):
                self.speak("File write cancelled.")
                return
        if not content:
            self.speak("What content should I write to the file?")
            content = self.get_response(timeout=15)
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            self.speak(f"Done sir. File {filename} created with {len(content)} characters.")
        except Exception as e:
            self.speak(f"Error writing file: {e}")

    def _intent_delete_file(self, filename, _=""):
        if not filename:
            self.speak("Which file should I delete, sir?")
            return
        filepath = os.path.join(self._workspace, filename)
        if not os.path.exists(filepath):
            self.speak(f"File not found: {filename}")
            return
        if self._confirm(f"Are you sure you want to delete {filename}? This cannot be undone."):
            try:
                if os.path.isdir(filepath):
                    shutil.rmtree(filepath)
                else:
                    os.remove(filepath)
                self.speak(f"Done sir. {filename} has been deleted.")
            except Exception as e:
                self.speak(f"Error deleting: {e}")
        else:
            self.speak("Delete cancelled. File is safe.")

    def _intent_copy_file(self, source, dest, _=""):
        if not source or not dest:
            self.speak("Please specify both source and destination.")
            return
        src_path = os.path.join(self._workspace, source)
        dst_path = os.path.join(self._workspace, dest)
        if not os.path.exists(src_path):
            self.speak(f"Source not found: {source}")
            return
        try:
            if os.path.isdir(src_path):
                shutil.copytree(src_path, dst_path)
            else:
                shutil.copy2(src_path, dst_path)
            self.speak(f"Done sir. Copied {source} to {dest}.")
        except Exception as e:
            self.speak(f"Copy failed: {e}")

    def _intent_move_file(self, source, dest, _=""):
        if not source or not dest:
            self.speak("Please specify both source and destination.")
            return
        src_path = os.path.join(self._workspace, source)
        dst_path = os.path.join(self._workspace, dest)
        if not os.path.exists(src_path):
            self.speak(f"Source not found: {source}")
            return
        try:
            shutil.move(src_path, dst_path)
            self.speak(f"Done sir. Moved {source} to {dest}.")
        except Exception as e:
            self.speak(f"Move failed: {e}")

    def _intent_search_files(self, query, path="", _=""):
        if not query:
            self.speak("What file are you looking for, sir?")
            return
        search_dir = os.path.join(self._workspace, path) if path else self._workspace
        matches = globmod.glob(os.path.join(search_dir, "**", f"*{query}*"), recursive=True)
        if matches:
            names = [os.path.relpath(m, search_dir) for m in matches[:10]]
            self.speak(f"Done sir. Found {len(matches)} matches: {', '.join(names)}.")
        else:
            self.speak(f"No files matching '{query}' found in {search_dir}.")

    def _ask_ollama(self, prompt):
        try:
            resp = requests.post(
                "http://localhost:11434/api/generate",
                json={"model": "llama3.2", "prompt": prompt, "stream": False, "max_tokens": 200},
                timeout=30,
            )
            if resp.status_code == 200:
                return resp.json().get("response", "").strip()
        except requests.exceptions.ConnectionError:
            return None
        except Exception as e:
            print(f"[OLLAMA] Error: {e}")
        return None

    # ── Multi-LLM Backend ──────────────────────────────────────────

    def _ask_llm(self, prompt, system=None):
        backend = LLM_BACKEND.lower()
        if backend == "gemini" and GEMINI_API_KEY:
            return self._ask_gemini(prompt)
        if backend == "openai" and OPENAI_API_KEY:
            return self._ask_openai(prompt, system)
        if backend == "claude" and ANTHROPIC_API_KEY:
            return self._ask_claude(prompt, system)
        if backend == "openrouter" and OPENROUTER_API_KEY:
            return self._ask_openrouter(prompt, system or "You are Jarvis, a helpful AI assistant.")
        return self._ask_ollama(prompt)

    def _ask_openrouter(self, prompt, system="You are Jarvis, a helpful AI assistant."):
        models_to_try = [OPENROUTER_MODEL]
        if OPENROUTER_FALLBACK_MODEL:
            models_to_try.append(OPENROUTER_FALLBACK_MODEL)
        for model in models_to_try:
            try:
                resp = requests.post(
                    f"{OPENROUTER_BASE}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": prompt},
                        ],
                        "max_tokens": 300,
                    },
                    timeout=30,
                )
                if resp.status_code == 200:
                    return resp.json()["choices"][0]["message"]["content"].strip()
                if resp.status_code in (429, 503):
                    print(f"[OPENROUTER] {model} unavailable ({resp.status_code}), trying fallback...")
                    continue
                print(f"[OPENROUTER] HTTP {resp.status_code}: {resp.text[:200]}")
            except Exception as e:
                print(f"[OPENROUTER] Error with {model}: {e}")
                continue
        return None

    def _route_input(self, text):
        system = (
            "You are Jarvis, an AI assistant that decides how to handle user input.\n"
            "Respond with exactly one of these formats:\n"
            "COMMAND|intent_name|entity|extra - if the user is giving a command\n"
            "CHAT|response - if the user is just chatting or asking a question\n\n"
            "Available intent names (use EXACTLY these): open_app, close_app, search, wikipedia, github, "
            "note, read_screen, describe_screen, camera, vision_ask, remember, recall, forget, "
            "volume_up, volume_down, mute, "
            "unmute, brightness_up, brightness_down, lock_screen, screenshot, "
            "clip_save, clip_list, clip_paste, remind, reminders, weather, "
            "hass, brain, file_read, file_write, file_list, file_delete, "
            "git_status, git_add, git_commit, git_push, git_pull, git_log, "
            "youtube, search_google, search_images, news, joke, refresh, "
            "sleep, exit, help, unknown\n\n"
            "IMPORTANT: intent_name must be one of the available intents listed above, exactly as written.\n\n"
            "Examples:\n"
            'User: "open notepad"\n'
            "COMMAND|open_app|notepad|\n"
            'User: "close notepad"\n'
            "COMMAND|close_app|notepad|\n"
            'User: "what is the weather in london?"\n'
            "COMMAND|weather|london|\n"
            'User: "who won the world cup in 2018?"\n'
            "CHAT|France won the 2018 FIFA World Cup, defeating Croatia 4-2 in the final.\n"
            'User: "I feel tired today"\n'
            "CHAT|I'm sorry to hear that, sir. Would you like me to make you some coffee or play some relaxing music?\n"
            'User: "remind me to call mom at 5pm"\n'
            "COMMAND|remind|call mom|5pm\n"
            'User: "search for python tutorials"\n'
            "COMMAND|search|python tutorials|\n"
            'User: "hello"\n'
            "CHAT|Hello sir. How can I help you today?\n"
            'User: "open youtube"\n'
            "COMMAND|youtube||\n"
            'User: "play despacito on youtube"\n'
            "COMMAND|youtube|despacito|\n"
            'User: "turn off the lights"\n'
            "COMMAND|hass|turn_off|light.living_room_lights\n"
            'User: "explain quantum computing"\n'
            "CHAT|Quantum computing uses qubits that can exist in multiple states simultaneously, allowing certain calculations to be performed much faster than classical computers.\n"
            'User: "take a screenshot"\n'
            "COMMAND|screenshot||\n"
            'User: "tell me a joke"\n'
            "COMMAND|joke||\n\n"
            "For any command you don't recognize, respond with:\n"
            "CHAT|I can help with opening apps, web searches, reminders, notes, GitHub, file operations, Home Assistant, and more. What would you like to do, sir?"
        )
        answer = self._ask_llm(text, system=system)
        if answer and answer.startswith("COMMAND|"):
            parts = answer.split("|")
            intent = parts[1].strip() if len(parts) > 1 else "unknown"
            entity = parts[2].strip() if len(parts) > 2 else ""
            extra = parts[3].strip() if len(parts) > 3 else ""
            noise_words = {"weather", "search", "note", "remind", "open", "close",
                           "play", "find", "look up", "get", "show", "tell"}
            if entity.lower() in noise_words and extra:
                entity = extra
                extra = ""
            self.handle(intent, entity, extra)
        elif answer and answer.startswith("CHAT|"):
            response_text = answer[5:].strip()
            self.speak(response_text[:500])
        else:
            self.speak(answer[:500] if answer else "I'm not sure how to help with that, sir.")

    def _ask_gemini(self, prompt):
        try:
            resp = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}",
                json={"contents": [{"parts": [{"text": prompt}]}]},
                timeout=30,
            )
            if resp.status_code == 200:
                candidates = resp.json().get("candidates", [])
                if candidates:
                    return candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
        except Exception as e:
            print(f"[GEMINI] Error: {e}")
        return None

    def _ask_openai(self, prompt, system=None):
        try:
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
                json={"model": OPENAI_MODEL, "messages": messages, "max_tokens": 300},
                timeout=30,
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"[OPENAI] Error: {e}")
        return None

    def _ask_claude(self, prompt, system=None):
        try:
            headers = {
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            }
            body = {"model": ANTHROPIC_MODEL, "max_tokens": 300, "messages": [{"role": "user", "content": prompt}]}
            if system:
                body["system"] = system
            resp = requests.post("https://api.anthropic.com/v1/messages", headers=headers, json=body, timeout=30)
            if resp.status_code == 200:
                return resp.json()["content"][0]["text"].strip()
        except Exception as e:
            print(f"[CLAUDE] Error: {e}")
        return None

    # ── OCR / Screen Reading (from Likhithsai2580) ────────────────

    def _intent_read_screen(self, _1="", _2=""):
        self.speak("Scanning the screen, sir.")
        try:
            import pytesseract
            from PIL import Image
            screenshot = pyautogui.screenshot()
            text = pytesseract.image_to_string(screenshot)
            text = text.strip()
            if text:
                self.speak(f"I found text on your screen: {text[:600]}")
                if self.viz:
                    self.viz.add_text(f"[OCR] {text[:2000]}", "system")
            else:
                self.speak("I couldn't find any readable text on the screen.")
        except ImportError:
            self.speak("OCR requires pytesseract and Tesseract-OCR installed. Run: pip install pytesseract")
        except Exception as e:
            self.speak(f"Screen reading failed: {e}")

    # ── Chrome Control ───────────────────────────────────────────

    def _intent_open_tab(self, url="", _=""):
        if not url:
            url = "https://www.google.com"
        if not url.startswith("http"):
            url = f"https://{url}"
        try:
            webbrowser.open(url)
            self.speak(f"Opened {url}, sir.")
        except Exception as e:
            self.speak(f"Failed to open tab: {e}")

    def _intent_search_tab(self, query, _=""):
        if not query:
            self.speak("What should I search for?")
            return
        url = f"https://www.google.com/search?q={url_encode(query)}"
        webbrowser.open(url)
        self.speak(f"Searching for {query} in your browser.")

    # ── Conversation Mode Context (from Isair) ───────────────────

    def _build_context(self, new_prompt):
        if not CONVERSATION_MODE or not self.memory:
            return new_prompt
        return self.memory.get_context_with_facts(new_prompt, max_turns=MAX_CONTEXT_TURNS)

    def _intent_ask(self, query, _=""):
        if not query:
            self.speak("What would you like to ask?")
            return
        self.speak("Let me think about that, sir.")
        enhanced = self._build_context(query)
        answer = self._ask_llm(enhanced, system="You are Jarvis, a helpful AI assistant. Be concise and accurate.")
        if answer:
            self.speak(answer[:600])
        else:
            self.speak("I couldn't get an answer. Let me search instead.")
            self._intent_search(query)

    def _intent_code(self, query, _=""):
        if not query:
            self.speak("What code should I help with?")
            return
        self.speak("Let me work on that.")
        answer = self._ask_llm(
            f"Write code for: {query}. Return only the code with brief comments.",
            system="You are an expert programmer. Output clean, working code.",
        )
        if answer:
            self.speak(answer[:600])
        else:
            self.speak("I couldn't generate code right now.")

    # ── Clipboard Manager ─────────────────────────────────────────

    def _intent_clip_save(self, _1="", _2=""):
        if not HAS_PYPERCLIP:
            self.speak("Clipboard requires pyperclip. Run: pip install pyperclip")
            return
        try:
            text = pyperclip.paste()
            if not text.strip():
                self.speak("Your clipboard is empty.")
                return
            clip_file = os.path.join(DEFAULT_WORKSPACE, "data", "clipboard.json")
            os.makedirs(os.path.dirname(clip_file), exist_ok=True)
            clips = []
            if os.path.exists(clip_file):
                with open(clip_file, "r") as f:
                    clips = json.load(f)
            clips.append({"text": text[:500], "time": datetime.now().isoformat()})
            clips = clips[-50:]
            with open(clip_file, "w") as f:
                json.dump(clips, f, indent=2)
            self.speak("Done sir. Clipboard saved.")
        except Exception as e:
            self.speak(f"Clipboard save failed: {e}")

    def _intent_clip_list(self, _1="", _2=""):
        clip_file = os.path.join(DEFAULT_WORKSPACE, "data", "clipboard.json")
        if not os.path.exists(clip_file):
            self.speak("No saved clips.")
            return
        with open(clip_file, "r") as f:
            clips = json.load(f)
        if not clips:
            self.speak("No saved clips.")
            return
        parts = [f"{i+1}. {c['text'][:60]}" for i, c in enumerate(clips[-5:])]
        self.speak("Recent clips: " + " | ".join(parts))
        if self.viz:
            for p in parts:
                self.viz.add_text(f"  {p}", "system")

    def _intent_clip_paste(self, idx="", _=""):
        if not HAS_PYPERCLIP:
            self.speak("Clipboard requires pyperclip.")
            return
        clip_file = os.path.join(DEFAULT_WORKSPACE, "data", "clipboard.json")
        if not os.path.exists(clip_file):
            self.speak("No saved clips.")
            return
        with open(clip_file, "r") as f:
            clips = json.load(f)
        try:
            n = int(idx) - 1 if idx.strip() else -1
            text = clips[n]["text"] if clips else None
        except Exception:
            text = clips[-1]["text"] if clips else None
        if text:
            pyperclip.copy(text)
            self.speak(f"Pasted clip {idx or 'latest'} to clipboard.")
        else:
            self.speak("Clip not found.")

    # ── Quick Notes ──────────────────────────────────────────────

    def _intent_note(self, text, _=""):
        if not text:
            self.speak("What should I note down?")
            return
        os.makedirs(NOTES_DIR, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        note_file = os.path.join(NOTES_DIR, f"{today}.md")
        timestamp = datetime.now().strftime("%H:%M")
        with open(note_file, "a", encoding="utf-8") as f:
            f.write(f"- [{timestamp}] {text}\n")
        self.speak(f"Noted: {text[:100]}")

    def _intent_read_notes(self, date_str="", _=""):
        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")
        note_file = os.path.join(NOTES_DIR, f"{date_str}.md")
        if not os.path.exists(note_file):
            self.speak(f"No notes for {date_str}.")
            return
        try:
            with open(note_file, "r") as f:
                content = f.read()[:800]
            self.speak(f"Notes for {date_str}: {content[:500]}")
        except Exception as e:
            self.speak(f"Error reading notes: {e}")

    # ── Reminders ────────────────────────────────────────────────

    def _intent_remind(self, text, delay_str="", _=""):
        if not text:
            self.speak("What should I remind you about?")
            return
        seconds = 60
        if delay_str:
            match = re.search(r"(\d+)\s*(minute|minutes|min|m|second|seconds|sec|s|hour|hours|hr|h)", delay_str.lower())
            if match:
                num = int(match.group(1))
                unit = match.group(2)
                if unit in ("hour", "hours", "hr", "h"):
                    seconds = num * 3600
                elif unit in ("minute", "minutes", "min", "m"):
                    seconds = num * 60
                else:
                    seconds = num
        from reminders import ReminderScheduler
        self._reminder_scheduler.add_timer(text, seconds)
        if seconds >= 60:
            self.speak(f"Reminder set for {seconds//60} minutes: {text}")
        else:
            self.speak(f"Reminder set for {seconds} seconds: {text}")

    def _intent_list_reminders(self, _1="", _2=""):
        reminders = self._reminder_scheduler.list_active()
        if not reminders:
            self.speak("No active reminders.")
            return
        parts = []
        for i, r in enumerate(reminders):
            try:
                due = datetime.fromisoformat(r["due"])
                remaining = (due - datetime.now()).total_seconds()
                if remaining > 0:
                    parts.append(f"{i+1}. {r['text']} (in {int(remaining//60)}m)")
                else:
                    parts.append(f"{i+1}. {r['text']} (now)")
            except Exception:
                parts.append(f"{i+1}. {r['text']}")
        self.speak("Active reminders: " + " | ".join(parts[:5]))

    # ── Home Assistant ───────────────────────────────────────────

    def _intent_hass_light(self, action, _=""):
        if not HASS_URL or not HASS_TOKEN:
            self.speak("Home Assistant not configured. Set HASS_URL and HASS_TOKEN.")
            return
        try:
            domain = "light"
            entity_id = f"{domain}.{action.replace(' ','_')}"
            headers = {"Authorization": f"Bearer {HASS_TOKEN}", "Content-Type": "application/json"}
            if action.startswith("turn on"):
                entity = action.replace("turn on ", "").strip()
                entity_id = f"light.{entity.replace(' ','_')}"
                requests.post(f"{HASS_URL}/api/services/{domain}/turn_on", json={"entity_id": entity_id}, headers=headers, timeout=5)
            elif action.startswith("turn off"):
                entity = action.replace("turn off ", "").strip()
                entity_id = f"light.{entity.replace(' ','_')}"
                requests.post(f"{HASS_URL}/api/services/{domain}/turn_off", json={"entity_id": entity_id}, headers=headers, timeout=5)
            else:
                self.speak("Say: turn on/off [light name]")
                return
            self.speak(f"Done sir. {action}.")
        except Exception as e:
            self.speak(f"Home Assistant error: {e}")

    def _intent_hass_status(self, _1="", _2=""):
        if not HASS_URL or not HASS_TOKEN:
            self.speak("Home Assistant not configured.")
            return
        try:
            resp = requests.get(f"{HASS_URL}/api/states", headers={"Authorization": f"Bearer {HASS_TOKEN}"}, timeout=5)
            if resp.status_code == 200:
                states = resp.json()
                lights = [s for s in states if s["entity_id"].startswith("light.")]
                on_count = sum(1 for l in lights if l["state"] == "on")
                self.speak(f"Home Assistant: {on_count} lights on out of {len(lights)} total.")
            else:
                self.speak("Couldn't reach Home Assistant.")
        except Exception as e:
            self.speak(f"Error: {e}")

    # ── Vision: Describe Screen ──────────────────────────────────

    def _capture_screen_base64(self):
        import io
        import base64
        from PIL import Image
        screenshot = pyautogui.screenshot()
        buf = io.BytesIO()
        screenshot.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    def _vision_llm(self, image_b64, prompt):
        if not OPENROUTER_API_KEY:
            return None
        try:
            resp = requests.post(
                f"{OPENROUTER_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": VISION_MODEL,
                    "messages": [
                        {"role": "user", "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                        ]},
                    ],
                    "max_tokens": 400,
                },
                timeout=30,
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"].strip()
            print(f"[VISION] HTTP {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            print(f"[VISION] Error: {e}")
        return None

    def _intent_describe_screen(self, _1="", _2=""):
        self.speak("Analyzing your screen, sir.")
        try:
            b64 = self._capture_screen_base64()
            if VISION_ENABLED and b64:
                answer = self._vision_llm(b64, "Describe what you see on this screen in detail. What applications are open? What content is visible?")
                if answer:
                    self.speak(answer[:600])
                    return
            import pytesseract
            screenshot = pyautogui.screenshot()
            text = pytesseract.image_to_string(screenshot).strip()
            if text:
                self.speak(f"I found text on your screen: {text[:600]}")
            else:
                self.speak("I couldn't find any readable text on the screen.")
        except ImportError:
            self.speak("Screen analysis requires pytesseract or a vision-capable LLM.")
        except Exception as e:
            self.speak(f"Screen analysis failed: {e}")

    # ── Vision: Camera ───────────────────────────────────────────

    def _intent_camera(self, _1="", _2=""):
        if not VISION_ENABLED:
            self.speak("Vision is not enabled, sir.")
            return
        self.speak("Taking a photo, sir.")
        try:
            import cv2
            cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                self.speak("Could not open camera.")
                return
            ret, frame = cap.read()
            cap.release()
            if not ret:
                self.speak("Failed to capture from camera.")
                return
            import io
            import base64
            from PIL import Image
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(rgb)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode()
            answer = self._vision_llm(b64, "Describe what you see in this photo in detail. What objects, people, or environment can you identify?")
            if answer:
                self.speak(f"I see: {answer[:600]}")
            else:
                self.speak("Photo captured but I couldn't analyze it.")
        except ImportError:
            self.speak("Camera requires opencv-python. Run: pip install opencv-python")
        except Exception as e:
            self.speak(f"Camera failed: {e}")

    # ── Vision: Ask about screen ─────────────────────────────────

    def _intent_vision_ask(self, query="", _=""):
        if not VISION_ENABLED:
            self.speak("Vision is not enabled, sir.")
            return
        if not query:
            query = "What do you see on the screen?"
        self.speak("Looking at your screen, sir.")
        try:
            b64 = self._capture_screen_base64()
            answer = self._vision_llm(b64, query)
            if answer:
                self.speak(answer[:600])
            else:
                self.speak("I couldn't answer that about the screen.")
        except Exception as e:
            self.speak(f"Vision analysis failed: {e}")

    # ── Persistent Memory ────────────────────────────────────────

    def _intent_remember(self, text="", _=""):
        if not text:
            self.speak("What should I remember?")
            return
        if self.memory and MEMORY_ENABLED:
            self.memory.facts.add(text, category="user_said")
            self.memory.flush()
            self.speak(f"I'll remember that, sir: {text[:200]}")
        else:
            self.speak("Memory system is not available.")

    def _intent_recall(self, query="", _=""):
        if not query:
            self.speak("What should I recall?")
            return
        if self.memory and MEMORY_ENABLED:
            results = self.memory.facts.search(query)
            if results:
                parts = [f["text"] for f in results[:3]]
                self.speak("I remember: " + " | ".join(parts))
            else:
                self.speak("I don't have any information about that yet, sir.")
        else:
            self.speak("Memory system is not available.")

    def _intent_forget(self, topic="", _=""):
        if not topic:
            self.speak("What should I forget?")
            return
        if self.memory and MEMORY_ENABLED:
            before = len(self.memory.facts.data["facts"])
            self.memory.facts.data["facts"] = [
                f for f in self.memory.facts.data["facts"]
                if topic.lower() not in f["text"].lower()
            ]
            removed = before - len(self.memory.facts.data["facts"])
            self.memory.facts.flush()
            if removed:
                self.speak(f"Forgot {removed} fact(s) about {topic}.")
            else:
                self.speak(f"I don't have anything about {topic} to forget.")
        else:
            self.speak("Memory system is not available.")

    def _intent_mic_list(self, _1="", _2=""):
        try:
            import pyaudio
            pa = pyaudio.PyAudio()
            lines = []
            for i in range(pa.get_device_count()):
                info = pa.get_device_info_by_index(i)
                if info.get("maxInputChannels", 0) > 0:
                    lines.append(f"  [{i}] {info.get('name')}")
            pa.terminate()
            msg = "Available microphones:\n" + "\n".join(lines) if lines else "No microphones found."
            self.speak(f"Found {len(lines)} microphones. Check the console for details.")
            print(msg)
            if self.viz:
                for line in msg.split("\n"):
                    self.viz.add_text(line, "system")
        except Exception as e:
            self.speak(f"Could not list microphones: {e}")

    def _intent_mic_select(self, device_id="", _=""):
        try:
            idx = int(device_id.strip())
            import pyaudio
            pa = pyaudio.PyAudio()
            info = pa.get_device_info_by_index(idx)
            pa.terminate()
            if info.get("maxInputChannels", 0) == 0:
                self.speak(f"Device {idx} is not an input device.")
                return
            name = info.get("name", "Unknown")
            config_path = os.path.join(BASE_DIR, ".env")
            self.speak(f"Selected microphone {idx}: {name}. Updating config...")
            self._set_env_value(config_path, "MIC_DEVICE_INDEX", str(idx))
            os.environ["MIC_DEVICE_INDEX"] = str(idx)
            self.speak(f"Microphone set to {name}. Please restart Jarvis for changes to take effect.")
        except ValueError:
            self.speak("Please provide a device number. Use /mic list to see available devices.")
        except Exception as e:
            self.speak(f"Could not select microphone: {e}")

    def _set_env_value(self, env_path, key, value):
        if os.path.isfile(env_path):
            with open(env_path, "r") as f:
                lines = f.readlines()
            found = False
            for i, line in enumerate(lines):
                if line.strip().startswith(key + "="):
                    lines[i] = f"{key}={value}\n"
                    found = True
                    break
            if not found:
                lines.append(f"{key}={value}\n")
            with open(env_path, "w") as f:
                f.writelines(lines)
        else:
            with open(env_path, "w") as f:
                f.write(f"{key}={value}\n")

    # ── Self-Improvement ─────────────────────────────────────

    def _intent_improve_review(self, _1="", _2=""):
        if not SELF_IMPROVEMENT_ENABLED or not self.self_improvement:
            self.speak("Self-improvement is not enabled, sir.")
            return
        self.speak("Running self-improvement review now, sir.")
        found = self.self_improvement.review_now()
        if found:
            count = len(self.self_improvement.get_pending())
            self.speak(f"I found {count} improvement opportunity. Say /patches to review them.")
        else:
            self.speak("I reviewed the recent conversations and didn't find any patterns to improve.")

    def _intent_patches_list(self, _1="", _2=""):
        if not SELF_IMPROVEMENT_ENABLED or not self.self_improvement:
            self.speak("Self-improvement is not enabled, sir.")
            return
        pending = self.self_improvement.get_pending()
        if not pending:
            self.speak("No pending patches, sir.")
            return
        self.speak(f"You have {len(pending)} pending patch.")
        for i, p in enumerate(pending, 1):
            desc = p.get("description", p.get("intent_name", "unknown"))
            self.speak(f"Patch {i}: {desc}")

    def _intent_patch_apply(self, idx="", _=""):
        if not SELF_IMPROVEMENT_ENABLED or not self.self_improvement:
            self.speak("Self-improvement is not enabled, sir.")
            return
        try:
            n = int(idx.strip()) - 1
        except (ValueError, AttributeError):
            self.speak("Which patch number should I apply? Say /patches to see them.")
            return
        pending = self.self_improvement.get_pending()
        if n < 0 or n >= len(pending):
            self.speak(f"Patch {idx} not found.")
            return
        patch = pending[n]
        if self._confirm(f"Apply patch: {patch.get('description', 'unknown')}. Are you sure?"):
            ok = self.self_improvement.apply_patch(patch["patch_id"])
            if ok:
                self.speak(f"Patch applied. Changes written to {patch.get('target_file', 'disk')}. Reloading module.")
                try:
                    target = patch.get("target_file", "").replace(".py", "")
                    if target in ("brain", "commands"):
                        import brain as bm
                        importlib.reload(bm)
                        self.brain = bm.IntentParser()
                    self.speak("Module reloaded. The improvement is active now.")
                except Exception as e:
                    self.speak(f"Patch written but reload failed. Restart Jarvis to activate.")
            else:
                self.speak("Failed to apply the patch, sir.")
        else:
            self.speak("Patch cancelled.")

    def _intent_patch_reject(self, idx="", _=""):
        if not SELF_IMPROVEMENT_ENABLED or not self.self_improvement:
            self.speak("Self-improvement is not enabled, sir.")
            return
        try:
            n = int(idx.strip()) - 1
        except (ValueError, AttributeError):
            self.speak("Which patch number should I reject?")
            return
        pending = self.self_improvement.get_pending()
        if n < 0 or n >= len(pending):
            self.speak(f"Patch {idx} not found.")
            return
        patch = pending[n]
        if self._confirm(f"Reject patch: {patch.get('description', 'unknown')}. Are you sure?"):
            self.self_improvement.reject_patch(patch["patch_id"])
            self.speak("Patch rejected.")

    def _intent_help(self, _1="", _2=""):
        help_text = """
Available slash commands:
  /time          - Current time
  /date          - Current date
  /open [app]    - Open application
  /close [app]   - Close application
  /search [q]    - Search the web
  /wiki [q]      - Search Wikipedia
  /play [q]      - Play on YouTube
  /ask [q]       - Ask Jarvis anything (via AI backend)
  /code [q]      - Generate code
  /screenshot    - Take screenshot
  /readscreen    - OCR: read text from screen
  /describe      - Describe screen contents (AI vision)
  /vision [q]    - Ask a question about what's on screen
  /camera        - Take a photo and describe it
  /remember [t]  - Store a fact in persistent memory
  /recall [q]    - Recall stored facts
  /forget [t]    - Remove stored facts about a topic
  /tab [url]     - Open browser tab
  /clip save     - Save current clipboard
  /clip list     - List saved clips
  /clip paste [n]- Paste a saved clip
  /note [text]   - Quick note to today's file
  /notes [date]  - Read notes for a date
  /remind [text] [in Xm] - Set a reminder
  /reminders     - List active reminders
  /list          - List files
  /read [file]   - Read file
  /write [f] [c] - Write file
  /delete [file] - Delete file
  /search files [q] - Search for files
  /improve       - Run self-improvement review
  /patches       - List pending improvement patches
  /patch apply [n]- Apply a pending patch
  /patch reject [n]- Reject a pending patch
  /mic list      - List microphone devices
  /mic select [n]- Select microphone by number
  /joke          - Tell a joke
  /cpu           - CPU usage
  /ram           - Memory usage
  /battery       - Battery status
  /volume up     - Increase volume
  /volume down   - Decrease volume
  /mute          - Mute audio
  /weather [city]- Weather report
  /hass [cmd]    - Home Assistant control
  /hass status   - Home Assistant status
  /github status - Git status
  /github push   - Push to GitHub
  /github pull   - Pull from GitHub
  /github repos  - List repos
  /github create [name] - Create repo
  /brain status  - Project overview
  /brain project [name] - Project detail
  /brain updates - Recent changes
  /brain summary - Daily summary
  /help          - Show this list
  /exit          - Exit Jarvis

Set LLM_BACKEND=gemini|openai|claude|ollama in env for AI questions.
Set HASS_URL + HASS_TOKEN for Home Assistant control.
You can also speak naturally: "What time is it?", "Open notepad", etc.
"""
        self.speak("Here are all available commands.")
        if self.viz:
            for line in help_text.strip().split("\n"):
                self.viz.add_text(line, "system")
        print(help_text)
