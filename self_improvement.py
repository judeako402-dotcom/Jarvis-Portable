import json
import logging
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path

from config import (
    IMPROVEMENT_LOG_FILE, PATCHES_DIR, IMPROVEMENT_REVIEW_INTERVAL,
    IMPROVEMENT_MIN_FREQUENCY, IMPROVEMENT_MAX_PENDING,
    SELF_IMPROVEMENT_ENABLED,
)

_log = logging.getLogger("self_improve")


class SelfImprovement:
    def __init__(self, handler, memory, brain):
        self.handler = handler
        self.memory = memory
        self.brain = brain
        self.log = self._load_log()
        self._pending = []
        self._running = True
        os.makedirs(PATCHES_DIR, exist_ok=True)
        self._refresh_pending()
        if SELF_IMPROVEMENT_ENABLED:
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()

    def _load_log(self):
        try:
            if os.path.exists(IMPROVEMENT_LOG_FILE):
                with open(IMPROVEMENT_LOG_FILE, "r") as f:
                    return json.load(f)
        except Exception:
            pass
        return {"version": 1, "last_review": "", "patterns": [], "patches": []}

    def _save_log(self):
        try:
            os.makedirs(os.path.dirname(IMPROVEMENT_LOG_FILE), exist_ok=True)
            with open(IMPROVEMENT_LOG_FILE, "w") as f:
                json.dump(self.log, f, indent=2)
        except Exception as e:
            _log.error(f"Failed to save improvement log: {e}")

    def _refresh_pending(self):
        self._pending = [p for p in self.log["patches"] if p.get("status") == "pending_review"]

    def has_pending(self):
        return len(self._pending) > 0

    def get_pending(self):
        return list(self._pending)

    def _loop(self):
        time.sleep(30)
        while self._running:
            try:
                if SELF_IMPROVEMENT_ENABLED:
                    self._review_and_generate()
            except Exception as e:
                _log.error(f"Self-improvement review failed: {e}")
            time.sleep(IMPROVEMENT_REVIEW_INTERVAL)

    def review_now(self):
        self._review_and_generate()
        return self.has_pending()

    def _review_and_generate(self):
        conversations = self.memory.data.get("conversations", [])
        if not conversations:
            return
        last_review = self.log.get("last_review", "")
        cutoff = last_review
        new_entries = []
        for entry in conversations:
            ts = entry.get("time", "")
            if ts > cutoff:
                new_entries.append(entry)
        if not new_entries:
            return
        self.log["last_review"] = conversations[-1].get("time", "")
        patterns = self._identify_failures(new_entries)
        for pattern in patterns:
            if self._is_duplicate_pattern(pattern):
                continue
            self.log["patterns"].append(pattern)
            patch = self._generate_patch(pattern)
            if patch:
                self.log["patches"].append(patch)
        self._refresh_pending()
        self._save_log()

    def _identify_failures(self, entries):
        patterns = {}
        for entry in entries:
            if entry.get("role") != "user":
                continue
            text = entry["text"].strip().lower()
            if not text or text.startswith("/"):
                continue
            slash_intent, _ = self.brain.parse_slash(text)
            if slash_intent:
                continue
            intent, _, _ = self.brain.parse(text)
            if intent != "unknown":
                continue
            normalized = re.sub(r"[^\w\s]", "", text).strip()
            if len(normalized) < 3:
                continue
            if normalized not in patterns:
                patterns[normalized] = {
                    "trigger": text, "count": 0,
                    "first": entry.get("time", ""),
                    "last": entry.get("time", ""),
                }
            patterns[normalized]["count"] += 1
            patterns[normalized]["last"] = entry.get("time", "")
        result = []
        for norm, data in patterns.items():
            if data["count"] < IMPROVEMENT_MIN_FREQUENCY:
                continue
            result.append({
                "pattern_id": f"fp_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(result)}",
                "trigger_phrases": [data["trigger"]],
                "frequency": data["count"],
                "first_seen": data["first"],
                "last_seen": data["last"],
                "status": "new",
            })
        return result

    def _is_duplicate_pattern(self, pattern):
        trigger = pattern.get("trigger_phrases", [""])[0].lower()
        for existing in self.log["patterns"]:
            for phrase in existing.get("trigger_phrases", []):
                if phrase.lower() == trigger:
                    return True
        return False

    def _generate_patch(self, pattern):
        prompt = (
            f"The user frequently says things like: {pattern['trigger_phrases']}\n"
            f"This happens {pattern['frequency']} times and results in an 'unknown' intent.\n\n"
            f"Analyze these phrases and decide if they need:\n"
            f"1. New regex patterns in brain.py (for existing intent)\n"
            f"2. A new intent handler in commands.py + patterns in brain.py\n\n"
            f"Existing intent names: time, date, screenshot, joke, cpu, ram, battery, "
            f"volume_up, volume_down, mute, shutdown, restart, greeting, identity, "
            f"weather, goodbye, thank, open_app, close_app, search, wikipedia, "
            f"play_youtube, list_files, read_file, write_file, delete_file, "
            f"copy_file, move_file, search_files, github_status, github_push, "
            f"github_pull, github_clone, github_create_repo, github_list_repos, "
            f"github_commit, read_screen, describe_screen, camera, vision_ask, "
            f"remember, recall, forget, open_tab, search_tab, note, read_notes, "
            f"remind, list_reminders, hass_light, hass_status, clip_save, "
            f"clip_list, clip_paste, ask, code\n\n"
            f"Return ONLY valid JSON with no markdown:\n"
            f"{{\n"
            f'  "matches_existing_intent": true|false,\n'
            f'  "existing_intent_name": "intent_name" or null,\n'
            f'  "new_intent_name": "snake_case_name" or null,\n'
            f'  "new_patterns": ["regex pattern 1", "regex pattern 2"],\n'
            f'  "needs_handler_code": true|false,\n'
            f'  "handler_code": "def _intent_NAME(self, entity, extra):\\n    ..." or null,\n'
            f'  "description": "what this patch does"\n'
            f"}}"
        )
        raw = self.handler._ask_llm(
            prompt,
            system="You are an expert Python developer. Output only valid JSON.",
        )
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group())
                except json.JSONDecodeError:
                    return None
            else:
                return None
        patch = {
            "patch_id": f"p_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(self.log['patches'])}",
            "failure_pattern_id": pattern["pattern_id"],
            "target_file": "brain.py" if not parsed.get("needs_handler_code") else "commands.py",
            "patch_type": "add_regex_pattern" if not parsed.get("needs_handler_code") else "new_intent_handler",
            "intent_name": parsed.get("existing_intent_name") or parsed.get("new_intent_name", "unknown"),
            "new_patterns": parsed.get("new_patterns", []),
            "handler_code": parsed.get("handler_code"),
            "description": parsed.get("description", ""),
            "created": datetime.now().isoformat(),
            "status": "pending_review",
            "applied_at": None,
        }
        return patch

    def apply_patch(self, patch_id):
        for patch in self.log["patches"]:
            if patch["patch_id"] == patch_id and patch["status"] == "pending_review":
                success = self._write_patch(patch)
                if success:
                    patch["status"] = "applied"
                    patch["applied_at"] = datetime.now().isoformat()
                    self._refresh_pending()
                    self._save_log()
                    return True
                return False
        return False

    def reject_patch(self, patch_id):
        for patch in self.log["patches"]:
            if patch["patch_id"] == patch_id and patch["status"] == "pending_review":
                patch["status"] = "rejected"
                self._refresh_pending()
                self._save_log()
                return True
        return False

    def _write_patch(self, patch):
        try:
            target = patch["target_file"]
            full_path = os.path.join(os.path.dirname(IMPROVEMENT_LOG_FILE), "..", target)
            full_path = os.path.normpath(os.path.abspath(full_path))
            if not os.path.isfile(full_path):
                _log.error(f"Target file not found: {full_path}")
                return False
            if patch["patch_type"] == "add_regex_pattern":
                return self._add_regex_patterns(full_path, patch["intent_name"], patch["new_patterns"])
            elif patch["patch_type"] == "new_intent_handler":
                with open(full_path, "a") as f:
                    f.write("\n" + patch.get("handler_code", ""))
                with open(full_path, "a") as f:
                    f.write(f"\n\n    # --- Added by self-improvement: {patch['description']} ---\n")
                self._save_patch_file(patch)
                return True
            return False
        except Exception as e:
            _log.error(f"Failed to write patch {patch['patch_id']}: {e}")
            return False

    def _add_regex_patterns(self, filepath, intent_name, patterns):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            pattern_entry = f'        "{intent_name}": [\n'
            for p in patterns:
                pattern_entry += f'            r"{p}",\n'
            pattern_entry += "        ],\n"
            content = content.replace(
                f'        "{intent_name}": [',
                pattern_entry.strip()[:-1],
            )
            if f'"{intent_name}": [' not in content:
                insert_pos = content.rfind("    }")
                if insert_pos > 0:
                    content = content[:insert_pos] + pattern_entry + content[insert_pos:]
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            self._save_patch_file(patch := {
                "patch_id": f"inline_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                "intent_name": intent_name,
                "patterns": patterns,
            })
            return True
        except Exception as e:
            _log.error(f"Failed to add regex patterns: {e}")
            return False

    def _save_patch_file(self, patch):
        try:
            pid = patch.get("patch_id", datetime.now().strftime("%Y%m%d_%H%M%S"))
            path = Path(PATCHES_DIR) / f"{pid}.json"
            with open(path, "w") as f:
                json.dump(patch, f, indent=2)
        except Exception as e:
            _log.error(f"Failed to save patch file: {e}")
