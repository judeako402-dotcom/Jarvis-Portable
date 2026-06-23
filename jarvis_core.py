import logging
import os
import sys
import threading
import time
import traceback

from voice_engine import VoiceEngine
from brain import IntentParser, Memory
from commands import CommandHandler
from visualizer import JarvisVisualizer
from plugins import load_plugins
from self_improvement import SelfImprovement
from config import WAKE_WORD, CONTINUOUS_CONVERSATION, AI_ROUTER, MEMORY_ENABLED, BARGE_IN_ENABLED

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jarvis.log")
logging.basicConfig(
    filename=LOG_FILE, level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
_log = logging.getLogger("jarvis")


class Jarvis:
    def __init__(self, headless=False, enable_web=False):
        self.active = True
        self._headless = headless
        self._voice_available = True
        self._web_ui = None

        try:
            self.voice = VoiceEngine()
        except Exception as e:
            _log.error(f"Voice engine failed: {e}\n{traceback.format_exc()}")
            self.voice = None
            self._voice_available = False

        self.memory = Memory()
        self.brain = IntentParser()

        if headless:
            self.viz = None
        else:
            self.viz = JarvisVisualizer(on_text_command=self._on_text_command)

        self.handler = CommandHandler(self.voice, memory=self.memory, visualizer=self.viz,
                                       speak_callback=self._add_text)
        self.plugins_loaded = load_plugins(self.handler)

        self.handler.self_improvement = SelfImprovement(
            handler=self.handler,
            memory=self.memory,
            brain=self.brain,
        )

        if not headless:
            try:
                from plugin_watcher import PluginWatcher
                self._plugin_watcher = PluginWatcher(self.handler)
            except Exception:
                self._plugin_watcher = None
        else:
            self._plugin_watcher = None

        self._text_queue = []
        self._text_lock = threading.Lock()

        if enable_web:
            try:
                from web_ui import WebUI
                self._web_ui = WebUI(on_command=self._on_text_command)
                self._web_ui.start()
            except Exception as e:
                _log.error(f"Web UI failed: {e}")

        _log.info(f"Jarvis initialized (headless={headless})")

    def _add_text(self, text, tag="system"):
        if self.viz:
            self.viz.add_text(text, tag)
        if self._web_ui:
            self._web_ui.add_text(text, tag)

    def _on_text_command(self, command):
        with self._text_lock:
            self._text_queue.append(command)

    def _pop_text(self):
        with self._text_lock:
            if self._text_queue:
                return self._text_queue.pop(0)
        return None

    def _process_command(self, command):
        self._add_text(f"You: {command}", "user")
        self.memory.add("user", command)
        if self.viz:
            self.viz.set_status("speaking")
        if self._web_ui:
            self._web_ui.set_status("speaking")

        slash_intent, slash_entity = self.brain.parse_slash(command)
        if slash_intent:
            if self.viz:
                self.viz.show_intent(f"Intent: {slash_intent}")
            result = self.handler.handle(slash_intent, slash_entity, "")
        elif AI_ROUTER:
            self.handler._route_input(command)
            result = None
        else:
            intent, entity, extra = self.brain.parse(command)
            if self.viz:
                self.viz.show_intent(f"Intent: {intent}")
            result = self.handler.handle(intent, entity, extra)

        if MEMORY_ENABLED:
            last = self.memory.get_recent(2)
            if len(last) == 2 and last[0]["role"] == "user" and last[-1]["role"] == "jarvis":
                self.memory.learn_from_response(last[0]["text"], last[-1]["text"])

        if result == "exit":
            self.active = False

    def _voice_loop(self):
        if not self._voice_available:
            self._add_text("Voice not available. Type commands in the box below.", "error")
            self._add_text("Ready. Type a command below.", "jarvis")
            return

        time.sleep(1)
        if self.plugins_loaded:
            self._add_text(f"Plugins loaded: {', '.join(self.plugins_loaded)}", "system")
        self._add_text("Ready. Say 'Jarvis' or type a command below.", "jarvis")
        try:
            self.handler.speak("Hello sir. Jarvis is online and ready.", enable_barge_in=False)
        except Exception as e:
            _log.error(f"Startup greeting failed: {e}")

        while self.active:
            if self.viz:
                self.viz.set_status("idle")
                self.viz.show_intent("")
            if self._web_ui:
                self._web_ui.set_status("idle")

            text_cmd = self._pop_text()
            if text_cmd:
                self._process_command(text_cmd)
                continue

            time.sleep(0.05)

            try:
                if self.voice.listen_for_wake_word(WAKE_WORD):
                    if self.viz:
                        self.viz.set_status("listening")
                    if self._web_ui:
                        self._web_ui.set_status("listening")
                    self._add_text("[Wake word detected]", "user")

                    completed = self.handler.speak("Yes sir?")
                    if not completed and BARGE_IN_ENABLED:
                        if self.viz:
                            self.viz.set_status("listening")
                        if self._web_ui:
                            self._web_ui.set_status("listening")
                        self._add_text("[Barge-in: listening]", "system")
                        command = self.voice.listen()
                        if command:
                            self._process_command(command)
                        continue

                    if self._web_ui:
                        self._web_ui.set_status("listening")
                    if self.viz:
                        self.viz.set_status("listening")

                    if CONTINUOUS_CONVERSATION:
                        commands = self.voice.listen_continuous()
                        for cmd in commands:
                            if cmd:
                                self._process_command(cmd)
                    else:
                        command = self.voice.listen()
                        if command:
                            self._process_command(command)
                        else:
                            self.handler.speak("I didn't catch that, sir.", enable_barge_in=False)
            except Exception as e:
                _log.error(f"Voice loop error: {e}\n{traceback.format_exc()}")
                time.sleep(1)

    def run(self):
        if self._voice_available:
            voice_thread = threading.Thread(target=self._voice_loop, daemon=True)
            voice_thread.start()
        if self.viz:
            try:
                self.viz.run()
            finally:
                self.stop()
        else:
            try:
                while self.active:
                    time.sleep(1)
            except KeyboardInterrupt:
                self.stop()
                print("\nJarvis stopped.")

    def stop(self):
        self.active = False
        self.memory.flush()
        if self.voice:
            try:
                self.voice.cleanup()
            except Exception:
                pass
        if self.viz:
            self.viz.stop()
        _log.info("Jarvis stopped")
