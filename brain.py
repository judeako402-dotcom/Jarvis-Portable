import json
import os
import re
from datetime import datetime

import spacy

from config import MEMORY_FILE, FACTS_FILE, MAX_MEMORY_LINES


class Facts:
    def __init__(self, save_batch=5):
        self.file = FACTS_FILE
        self.data = {"facts": []}
        self._dirty = False
        self._unsaved = 0
        self._batch = save_batch
        self._load()

    def _load(self):
        try:
            if os.path.exists(self.file):
                with open(self.file, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
        except (json.JSONDecodeError, OSError):
            self.data = {"facts": []}

    def _save(self, force=False):
        if not self._dirty:
            return
        if not force and self._unsaved < self._batch:
            return
        os.makedirs(os.path.dirname(self.file), exist_ok=True)
        with open(self.file, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
        self._dirty = False
        self._unsaved = 0

    def flush(self):
        self._save(force=True)

    def add(self, text, category="general", source="conversation"):
        existing = [f for f in self.data["facts"] if f["text"].lower() == text.lower()]
        if existing:
            existing[0]["updated"] = datetime.now().isoformat()
            existing[0]["count"] = existing[0].get("count", 1) + 1
        else:
            self.data["facts"].append({
                "text": text, "category": category, "source": source,
                "created": datetime.now().isoformat(), "count": 1,
            })
        self._dirty = True
        self._unsaved += 1
        self._save()

    def search(self, query, max_results=5):
        if not self.data["facts"]:
            return []
        words = set(query.lower().split())
        scored = []
        for fact in self.data["facts"]:
            text = fact["text"].lower()
            score = sum(1 for w in words if w in text)
            if score > 0:
                scored.append((score + fact.get("count", 1) * 0.1, fact))
        scored.sort(key=lambda x: -x[0])
        return [f for _, f in scored[:max_results]]

    def get_relevant(self, context, max_results=3):
        words = set(context.lower().split())
        if len(words) < 2:
            return []
        scored = []
        for fact in self.data["facts"]:
            text = fact["text"].lower()
            score = sum(1 for w in words if w in text and len(w) > 3)
            if score > 0:
                scored.append((score / max(len(words), 1), fact))
        scored.sort(key=lambda x: -x[0])
        return [f for _, f in scored[:max_results]]

    def get_all(self, category=None):
        if category:
            return [f for f in self.data["facts"] if f["category"] == category]
        return self.data["facts"]


class Memory:
    def __init__(self, save_batch=10):
        self.file = MEMORY_FILE
        self.facts = Facts()
        self.data = {"conversations": [], "preferences": {}, "learned": {}}
        self._dirty = False
        self._unsaved = 0
        self._batch = save_batch
        self._load()

    def _load(self):
        try:
            if os.path.exists(self.file):
                with open(self.file, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
        except (json.JSONDecodeError, OSError):
            self.data = {"conversations": [], "preferences": {}, "learned": {}}

    def _save(self, force=False):
        if not self._dirty:
            return
        if not force and self._unsaved < self._batch:
            return
        os.makedirs(os.path.dirname(self.file), exist_ok=True)
        with open(self.file, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
        self._dirty = False
        self._unsaved = 0

    def flush(self):
        self._save(force=True)
        self.facts.flush()

    def add(self, role, text):
        entry = {"role": role, "text": text, "time": datetime.now().isoformat()}
        self.data["conversations"].append(entry)
        if len(self.data["conversations"]) > MAX_MEMORY_LINES:
            self.data["conversations"] = self.data["conversations"][-MAX_MEMORY_LINES:]
        self._dirty = True
        self._unsaved += 1
        self._save()

    def get_recent(self, n=5):
        return self.data["conversations"][-n:]

    def get_context_with_facts(self, prompt, max_turns=10):
        context = ""
        recent = self.get_recent(max_turns)
        if recent:
            lines = []
            for entry in recent:
                role = "User" if entry["role"] == "user" else "Assistant"
                lines.append(f"{role}: {entry['text']}")
            context = "Previous conversation:\n" + "\n".join(lines) + "\n\n"
        relevant = self.facts.get_relevant(prompt)
        if relevant:
            fact_lines = [f["text"] for f in relevant]
            context += "Known facts about the user:\n" + "\n".join(fact_lines) + "\n\n"
        return context + f"User: {prompt}\nAssistant:"

    def set_preference(self, key, value):
        self.data["preferences"][key] = value
        self._dirty = True
        self._save()

    def get_preference(self, key, default=None):
        return self.data["preferences"].get(key, default)

    def learn_from_response(self, user_text, assistant_text):
        statements = self._extract_facts(user_text, assistant_text)
        for s in statements:
            self.facts.add(s, category="learned")

    def _extract_facts(self, user_text, assistant_text):
        facts = []
        patterns = [
            r"(?:my name is|i(?:')?m called|call me)\s+(\w+)",
            r"i (?:live|work|study)\s+(?:at|in|on)\s+(.+?)(?:\.|,|$)",
            r"(?:i have|i(?:')?ve got)\s+(?:a|an)\s+(.+?)(?:\.|,|$)",
            r"i like\s+(.+?)(?:\.|,|$)",
            r"i love\s+(.+?)(?:\.|,|$)",
            r"my favorite\s+(.+?)(?:\.|,|$)",
            r"(?:i am|i'm)\s+(\d+)\s+(?:years old|yo)",
            r"my (?:email|phone|address|birthday)\s+(?:is\s+)?(.+?)(?:\.|,|$)",
        ]
        for p in patterns:
            match = re.search(p, user_text, re.IGNORECASE)
            if match:
                facts.append(match.group(0).strip())
        return facts


class IntentParser:
    SLASH_COMMANDS = {
        "/time": "time",
        "/date": "date",
        "/screenshot": "screenshot",
        "/joke": "joke",
        "/cpu": "cpu",
        "/ram": "ram",
        "/battery": "battery",
        "/volume up": "volume_up",
        "/volume down": "volume_down",
        "/mute": "mute",
        "/list": "list_files",
        "/ls": "list_files",
        "/help": "help",
        "/exit": "goodbye",
        "/quit": "goodbye",
        "/github status": "github_status",
        "/github push": "github_push",
        "/github pull": "github_pull",
        "/github commit": "github_commit",
        "/github repos": "github_list_repos",
        "/open": "open_app",
        "/close": "close_app",
        "/search": "search",
        "/wiki": "wikipedia",
        "/wikipedia": "wikipedia",
        "/play": "play_youtube",
        "/read": "read_file",
        "/write": "write_file",
        "/delete": "delete_file",
        "/rm": "delete_file",
        "/copy": "copy_file",
        "/move": "move_file",
        "/search files": "search_files",
        "/find": "search_files",
        "/weather": "weather",
        "/github create": "github_create_repo",
        "/github clone": "github_clone",
        "/brain status": "brain_status",
        "/brain project": "brain_project",
        "/brain updates": "brain_updates",
        "/brain summary": "brain_summary",
        "/ask": "ask",
        "/code": "code",
        "/readscreen": "read_screen",
        "/ocr": "read_screen",
        "/tab": "open_tab",
        "/search tab": "search_tab",
        "/describe": "describe_screen",
        "/camera": "camera",
        "/vision": "vision_ask",
        "/remember": "remember",
        "/recall": "recall",
        "/forget": "forget",
        "/clip save": "clip_save",
        "/clip list": "clip_list",
        "/clip paste": "clip_paste",
        "/note": "note",
        "/notes": "read_notes",
        "/remind": "remind",
        "/reminders": "list_reminders",
        "/hass": "hass_light",
        "/hass status": "hass_status",
        "/mic list": "mic_list",
        "/mic select": "mic_select",
        "/improve": "improve_review",
        "/patches": "patches_list",
        "/patch apply": "patch_apply",
        "/patch reject": "patch_reject",
    }

    PATTERNS = {
        "open_app": [
            r"(?:open|launch|start|run)\s+(.+)",
        ],
        "close_app": [
            r"(?:close|exit|quit|kill)\s+(.+)",
        ],
        "play_youtube": [
            r"(?:play|watch)\s+(.+)\s+on\s+youtube",
            r"(?:play|watch)\s+(.+)",
        ],
        "wikipedia": [
            r"(?:search\s+)?wikipedia\s+(?:for\s+)?(.+)",
        ],
        "time": [
            r"what(?:'s| is) the time",
            r"tell me the time",
            r"what time is it",
        ],
        "date": [
            r"what(?:'s| is) the date",
            r"what(?:'s| is) today",
        ],
        "screenshot": [
            r"take a screenshot",
            r"screenshot",
        ],
        "joke": [
            r"tell me a joke",
            r"say something funny",
        ],
        "cpu": [
            r"(?:what(?:'s| is) the )?cpu (?:usage|load|temperature)",
        ],
        "ram": [
            r"(?:what(?:'s| is) the )?(?:ram|memory) (?:usage|load)",
        ],
        "battery": [
            r"(?:what(?:'s| is) the )?battery (?:status|level|percentage)",
        ],
        "volume_up": [
            r"(?:turn |raise |increase )?(?:the )?volume(?: up)?",
        ],
        "volume_down": [
            r"(?:turn |lower |decrease )?(?:the )?volume down",
        ],
        "mute": [
            r"mute (?:the )?(?:volume|sound|audio)",
        ],
        "shutdown": [
            r"shutdown (?:the )?(?:computer|pc|system)",
        ],
        "restart": [
            r"restart (?:the )?(?:computer|pc|system)",
        ],
        "greeting": [
            r"^(?:hello|hi|hey|good\s+(?:morning|afternoon|evening))",
        ],
        "identity": [
            r"who are you",
            r"what are you",
            r"your name",
        ],
        "weather": [
            r"(?:what(?:'s| is) (?:the )?weather|how(?:'s| is) the weather)(?:\s+in\s+(.+))?",
        ],
        "goodbye": [
            r"(?:goodbye|bye|see you|shut down jarvis)",
        ],
        "thank": [
            r"thank(?:s| you)",
        ],
        "github_status": [
            r"github (?:git )?status",
            r"(?:show |check )?(?:git |github )status",
        ],
        "github_push": [
            r"github push(?:\s+(.+))?",
            r"push (?:to )?(?:github|git|origin)(?:\s+(.+))?",
            r"upload (?:to )?(?:github|git)(?:\s+(.+))?",
        ],
        "github_pull": [
            r"github pull",
            r"pull (?:from )?(?:github|git|origin)",
            r"update (?:my )?(?:code|repo|repository)",
        ],
        "github_clone": [
            r"github clone\s+(.+)",
            r"clone (?:repo|repository)?\s*(.+)",
        ],
        "github_create_repo": [
            r"(?:create|make|new) (?:a )?(?:github |git )?(?:repo|repository)\s+(.+)",
            r"github create\s+(.+)",
        ],
        "github_list_repos": [
            r"(?:list|show|my) (?:github |git )?(?:repos|repositories)",
            r"github repos",
        ],
        "github_commit": [
            r"github commit(?:\s+(.+))?",
            r"commit (?:to )?(?:github|git)(?:\s+(.+))?",
        ],
        "list_files": [
            r"(?:list|show|display|see) (?:the )?(?:files?|directory|folder)(?:\s+in\s+(.+))?",
            r"what(?:'s| is) (?:in|here) (?:the )?(?:current )?(?:directory|folder)",
            r"ls(?:\s+(.+))?",
        ],
        "read_file": [
            r"(?:read|open|show|cat)\s+(?:the\s+)?(?:file\s+)?(.+)",
        ],
        "write_file": [
            r"(?:create|write|make)\s+(?:a\s+)?(?:file\s+)?(.+?)(?:\s+with\s+content\s+(.+))?$",
        ],
        "delete_file": [
            r"(?:delete|remove|rm)\s+(?:the\s+)?(?:file\s+)?(.+)",
        ],
        "copy_file": [
            r"copy\s+(.+?)\s+(?:to|into)\s+(.+)",
        ],
        "move_file": [
            r"move\s+(.+?)\s+(?:to|into)\s+(.+)",
        ],
        "search_files": [
            r"(?:search|find|locate)\s+(?:the\s+)?(?:file|files|folder|directory)\s+(.+?)(?:\s+in\s+(.+))?$",
            r"(?:search|find|locate)\s+(?:for\s+)?(?:the\s+)?(?:file|files)\s+(.+?)(?:\s+in\s+(.+))?$",
        ],
        "search": [
            r"(?:search|google|look up|find)\s+(?:for\s+)?(.+)",
            r"tell me about\s+(.+)",
        ],
        "brain_status": [
            r"what(?:'s| is) (?:my )?(?:project|projects) status",
            r"(?:show|check|get) (?:my )?project status",
            r"what am i working on",
            r"project(?:s)? overview",
            r"project status",
        ],
        "brain_project": [
            r"how(?:'s| is| are) (?:my )?project\s+(.+)",
            r"(?:show|check|get) project\s+(.+)",
            r"tell me about project\s+(.+)",
        ],
        "brain_updates": [
            r"(?:what|any|show) (?:changed|updates|recent changes)",
            r"(?:any|got) (?:new )?(?:updates|changes)",
            r"what(?:'s| is) new",
        ],
        "brain_summary": [
            r"(?:give me a )?(?:daily )?summary",
            r"how was my day",
            r"(?:what|tell me) did i do today",
        ],
        "ask": [
            r"ask\s+(.+?)(?:\?)?$",
            r"what is\s+(.+)",
            r"how do (?:i|you)\s+(.+)",
            r"explain\s+(.+)",
            r"tell me about\s+(.+)",
            r"can you\s+(.+)",
        ],
        "code": [
            r"(?:write|create|generate|make)\s+(?:a\s+)?(?:python |javascript |bash |code |script |function |class )?(.+?)(?:\s+(?:that|to|for|in|using))?(.+)?$",
            r"code\s+(.+)",
        ],
        "read_screen": [
            r"(?:read|scan|ocr) (?:the )?(?:screen|display)",
            r"what(?:'s| is) on (?:the )?(?:screen|display)",
            r"read (?:text from )?(?:the )?screen",
        ],
        "open_tab": [
            r"(?:open|go to|navigate to)\s+(?:a\s+)?(?:tab |website |site |url |page )?(.+)",
            r"browse\s+(.+)",
        ],
        "search_tab": [
            r"(?:search|look up|find) (?:on|in) (?:the )?(?:browser|web|chrome|tab)\s+(.+)",
            r"browser (?:search|find)\s+(.+)",
        ],
        "describe_screen": [
            r"(?:describe|what do you see|analyze) (?:the )?(?:screen|display)",
            r"what(?:'s| is) (?:on|showing on) (?:the )?(?:screen|display)",
        ],
        "camera": [
            r"(?:take|show|use|open)\s+(?:a\s+)?(?:photo|picture|camera|photo|snap)",
            r"what do you see(?:\s+through\s+(?:the\s+)?(?:camera|webcam))?",
        ],
        "vision_ask": [
            r"(?:look|see|view|visual)\s+(?:at\s+)?(.+)",
            r"what(?:'s| is) (?:in|on)\s+(.+)\s+(?:picture|photo|image|screen)",
            r"analyze (?:this\s+)?(?:image|picture|photo|screen)",
        ],
        "remember": [
            r"(?:remember|save|store|keep in mind|note that)\s+(.+)",
            r"remember that\s+(.+)",
        ],
        "recall": [
            r"(?:what do you know about|recall|remember|what(?:'s| is)|do you remember|do you know)\s+(.+)",
            r"tell me what you know about\s+(.+)",
        ],
        "forget": [
            r"(?:forget|delete|remove|clear)\s+(?:the\s+)?(?:fact|memory|info|knowledge)\s+(?:about\s+)?(.+)",
            r"forget about\s+(.+)",
        ],
        "clip_save": [
            r"(?:save|store|keep) (?:the )?clipboard",
            r"(?:clipboard )?save",
        ],
        "clip_list": [
            r"(?:list|show) (?:my )?(?:clipboard |saved )?clips",
        ],
        "clip_paste": [
            r"paste (?:clip|clipboard)(?:\s+(\d+))?",
        ],
        "note": [
            r"(?:take a |write a |make a )?note\s+(.+)",
            r"note this down\s*(.+)",
            r"remember\s+(.+)",
        ],
        "read_notes": [
            r"(?:read|show|get) (?:my )?notes(?:\s+(?:for |from )?(.+))?",
        ],
        "remind": [
            r"remind me\s+(?:to\s+)?(.+?)(?:\s+in\s+(\d+\s*(?:minute|minutes|min|m|second|seconds|sec|s|hour|hours|hr|h)))?$",
            r"set (?:a |an )?(?:reminder|timer)\s+(?:for\s+)?(\d+\s*(?:minute|minutes|sec|second|seconds|m|s))\s+(.+)$",
            r"remind me in\s+(\d+\s*(?:minute|minutes|m|sec|seconds|s))\s+(?:to\s+)?(.+)$",
        ],
        "list_reminders": [
            r"(?:list|show) (?:my )?(?:reminders|timers)",
            r"what (?:reminders|timers) (?:do I have|are set)",
        ],
        "hass_light": [
            r"(?:turn|switch)\s+(on|off)\s+(?:the\s+)?(?:light\s+)?(.+)",
            r"(?:home assistant|hass)\s+(.+)",
        ],
        "hass_status": [
            r"(?:home assistant|hass)\s+(?:status|state)",
            r"how is (?:home assistant|the house)",
        ],
        "improve_review": [
            r"self[- ]improvement",
            r"(?:improve|enhance|upgrade)\s+(?:yourself|the system|jarvis)",
            r"review (?:and )?(?:fix|patch|improve)",
            r"run self[- ]improvement",
        ],
        "patches_list": [
            r"(?:show|list|what are) (?:pending )?(?:patches|improvements)",
            r"(?:any |are there )?pending (?:patches|improvements)",
        ],
        "patch_apply": [
            r"(?:apply|approve|use)\s+(?:patch\s+)?(\d+)",
            r"apply patch (\d+)",
        ],
        "patch_reject": [
            r"(?:reject|deny|skip|cancel)\s+(?:patch\s+)?(\d+)",
            r"reject patch (\d+)",
        ],
    }

    def __init__(self):
        self._nlp = None

    @property
    def nlp(self):
        if self._nlp is None:
            try:
                self._nlp = spacy.load("en_core_web_sm")
            except OSError:
                self._nlp = None
        return self._nlp

    def parse_slash(self, text):
        text = text.strip()
        if not text.startswith("/"):
            return None, None
        lower = text.lower()
        if lower == "/help":
            return "help", ""
        for cmd, intent in sorted(self.SLASH_COMMANDS.items(), key=lambda x: -len(x[0])):
            if lower.startswith(cmd):
                entity = text[len(cmd):].strip()
                return intent, entity
        parts = lower.split(None, 1)
        if parts:
            return "unknown", text
        return None, None

    def parse(self, text):
        text = text.strip().lower()
        for intent, patterns in self.PATTERNS.items():
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    groups = match.groups()
                    entity = groups[0].strip() if groups and groups[0] else ""
                    extra = groups[1].strip() if len(groups) > 1 and groups[1] else ""
                    return intent, entity, extra
        return "unknown", text, ""

    def extract_entities(self, text):
        if not self.nlp:
            return {}
        doc = self.nlp(text)
        return {ent.label_: ent.text for ent in doc.ents}
