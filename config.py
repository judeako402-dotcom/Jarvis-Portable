import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# -- Load .env file (if present) --
_env_file = os.path.join(BASE_DIR, ".env")
if os.path.isfile(_env_file):
    with open(_env_file) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _val = _line.split("=", 1)
                _key = _key.strip()
                _val = _val.strip().strip("\"'")
                if _key and not os.environ.get(_key):
                    os.environ[_key] = _val
DATA_DIR = os.path.join(BASE_DIR, "data")
MODELS_DIR = os.path.join(BASE_DIR, "models")
PLUGINS_DIR = os.path.join(BASE_DIR, "plugins")
NOTES_DIR = os.path.join(DATA_DIR, "notes")

# -- Voice / STT --
VOSK_MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
VOSK_MODEL_DIR = os.path.join(MODELS_DIR, "vosk-model-small-en-us-0.15")
WAKE_WORD = os.environ.get("JARVIS_WAKE_WORD", "jarvis").lower()
LANGUAGE = "en-US"
RECOGNITION_TIMEOUT = 7
WAKE_WORD_TIMEOUT = 3
PORCUPINE_ACCESS_KEY = os.environ.get("PORCUPINE_ACCESS_KEY", "")
CONTINUOUS_CONVERSATION = os.environ.get("JARVIS_CONTINUOUS", "true").lower() == "true"
MIC_DEVICE_INDEX = int(os.environ.get("MIC_DEVICE_INDEX", "-1"))

# -- TTS --
TTS_VOICE = "en-US-GuyNeural"
TTS_RATE = "+0%"

# -- Barge-in --
BARGE_IN_ENABLED = os.environ.get("JARVIS_BARGE_IN", "true").lower() == "true"
BARGE_IN_AGGRESSIVENESS = int(os.environ.get("BARGE_IN_AGGRESSIVENESS", "2"))

# -- Vision --
VISION_ENABLED = os.environ.get("JARVIS_VISION", "true").lower() == "true"
VISION_MODEL = os.environ.get("JARVIS_VISION_MODEL", "google/gemma-4-31b-it:free")

# -- Memory --
MEMORY_ENABLED = os.environ.get("JARVIS_MEMORY", "true").lower() == "true"
MEMORY_FILE = os.path.join(DATA_DIR, "memory.json")
FACTS_FILE = os.path.join(DATA_DIR, "facts.json")
MAX_MEMORY_LINES = 50

# -- GitHub --
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_USERNAME = os.environ.get("GITHUB_USERNAME", "")

# -- LLM Backend --
LLM_BACKEND = os.environ.get("LLM_BACKEND", "ollama")
LLM_MODEL = os.environ.get("LLM_MODEL", "llama3.2")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-3-haiku-20240307")

# -- OpenRouter --
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "google/gemma-4-31b-it:free")
OPENROUTER_FALLBACK_MODEL = os.environ.get("OPENROUTER_FALLBACK_MODEL", "google/gemma-4-26b-a4b-it:free")
OPENROUTER_BASE = "https://openrouter.ai/api/v1"

# -- AI Router --
AI_ROUTER = os.environ.get("JARVIS_AI_ROUTER", "true").lower() == "true"

# -- Conversation --
CONVERSATION_MODE = os.environ.get("JARVIS_CONVERSATION_MODE", "false").lower() == "true"
MAX_CONTEXT_TURNS = 10

# -- Web UI --
WEB_UI_PORT = int(os.environ.get("JARVIS_WEB_PORT", "5000"))
WEB_UI_HOST = os.environ.get("JARVIS_WEB_HOST", "127.0.0.1")
WEB_UI_TOKEN = os.environ.get("JARVIS_WEB_TOKEN", "")

# -- Home Assistant --
HASS_URL = os.environ.get("HASS_URL", "")
HASS_TOKEN = os.environ.get("HASS_TOKEN", "")

# -- Workspace --
DEFAULT_WORKSPACE = BASE_DIR
MAX_READ_LINES = 50

# -- Reminders --
REMINDERS_FILE = os.path.join(DATA_DIR, "reminders.json")

# -- Self-Improvement --
SELF_IMPROVEMENT_ENABLED = os.environ.get("JARVIS_SELF_IMPROVEMENT", "true").lower() == "true"
IMPROVEMENT_LOG_FILE = os.path.join(DATA_DIR, "improvement_log.json")
PATCHES_DIR = os.path.join(BASE_DIR, "patches")
IMPROVEMENT_REVIEW_INTERVAL = int(os.environ.get("JARVIS_IMPROVEMENT_INTERVAL", "600"))
IMPROVEMENT_MIN_FREQUENCY = int(os.environ.get("JARVIS_IMPROVEMENT_MIN_FREQ", "2"))
IMPROVEMENT_MAX_PENDING = int(os.environ.get("JARVIS_IMPROVEMENT_MAX_PENDING", "5"))

def _find_chrome():
    import shutil
    chrome = shutil.which("chrome") or shutil.which("google-chrome") or shutil.which("chromium")
    if chrome:
        return chrome
    candidates = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return "chrome.exe"


APP_MAP = {
    "notepad": "notepad.exe",
    "notes": "notepad.exe",
    "sticky notes": "notepad.exe",
    "calculator": "calc.exe",
    "paint": "mspaint.exe",
    "cmd": "cmd.exe",
    "command prompt": "cmd.exe",
    "powershell": "powershell.exe",
    "explorer": "explorer.exe",
    "file explorer": "explorer.exe",
    "task manager": "taskmgr.exe",
    "control panel": "control.exe",
    "settings": "ms-settings:",
    "browser": ["start", "ms-edge:"],
    "edge": ["start", "ms-edge:"],
    "chrome": _find_chrome(),
    "spotify": ["start", "spotify:"],
    "vscode": "code",
    "code": "code",
    "word": ["start", "winword:"],
    "excel": ["start", "excel:"],
    "powerpoint": ["start", "powerpnt:"],
}
