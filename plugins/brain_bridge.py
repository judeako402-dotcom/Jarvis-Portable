"""
Jarvis Brain Bridge Plugin (Lightweight)
Connects Jarvis to the Agentic Cognitive OS Brain vault.
No Ollama required — reads vault files and scans project directories directly.

Slash commands:
  /brain status    - Overview of all projects
  /brain project [name] - Detail on one project
  /brain updates   - What changed recently
  /brain summary   - Daily summary

Natural language:
  "What am I working on?" / "Project status"
  "How's project [name]?"
  "What changed today?" / "Any updates?"
"""

import os
import re
import sys
import time
from pathlib import Path
from datetime import datetime, timezone
import yaml

BRAIN_ROOT = Path(os.environ.get("BRAIN_ROOT", ""))
VAULT = BRAIN_ROOT / "vault" if BRAIN_ROOT else Path()

# Project map — override via env var BRAIN_PROJECT_MAP (JSON string) or fall back to scanning
PROJECT_MAP_ENV = os.environ.get("BRAIN_PROJECT_MAP", "")
if PROJECT_MAP_ENV:
    import json
    PROJECT_MAP = json.loads(PROJECT_MAP_ENV)
else:
    PROJECT_MAP = []

SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv", "dist", "build", ".next"}


def _parse_vault_file(path):
    """Parse a vault markdown file and return (frontmatter_dict, body_text)."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None, ""
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content
    try:
        fm = yaml.safe_load(parts[1]) or {}
    except Exception:
        fm = {}
    body = parts[2].strip()
    return fm, body


def _get_project_dirs():
    """Return dict mapping project ID to its real directory path."""
    return {p["id"]: Path(p["dir"]) for p in PROJECT_MAP}


def _scan_project_files(proj_dir):
    """Scan a project directory: count files, get last modified, detect languages."""
    if not proj_dir.exists():
        return None

    ext_counts = {}
    last_modified = 0
    total_files = 0
    try:
        for f in proj_dir.rglob("*"):
            if any(skip in f.parts for skip in SKIP_DIRS):
                continue
            if f.is_file():
                total_files += 1
                ext = f.suffix.lower()
                if ext:
                    ext_counts[ext] = ext_counts.get(ext, 0) + 1
                mtime = f.stat().st_mtime
                if mtime > last_modified:
                    last_modified = mtime
    except Exception:
        pass

    top_langs = sorted(ext_counts.items(), key=lambda x: -x[1])[:5]
    lang_map = {
        ".py": "Python", ".js": "JS", ".ts": "TS", ".rs": "Rust",
        ".go": "Go", ".java": "Java", ".md": "Docs", ".json": "JSON",
        ".html": "HTML", ".css": "CSS", ".bat": "Batch", ".ps1": "PS",
        ".jsx": "React", ".tsx": "React", ".yaml": "YAML", ".yml": "YAML",
    }
    langs = [lang_map.get(ext, ext) for ext, _ in top_langs]

    return {
        "total_files": total_files,
        "languages": langs,
        "last_modified": last_modified,
        "last_modified_str": datetime.fromtimestamp(last_modified).strftime("%Y-%m-%d %H:%M") if last_modified else "unknown",
    }


def _load_all_projects():
    """Load all projects from vault + scan real directories for live data."""
    projects = {}

    # First, load from vault files
    if VAULT.exists():
        for proj_file in (VAULT / "projects").rglob("*.md"):
            fm, body = _parse_vault_file(proj_file)
            if not fm or not fm.get("id"):
                continue
            pid = fm["id"]
            projects[pid] = {
                "id": pid,
                "title": fm.get("title", pid),
                "status": fm.get("status", "unknown"),
                "priority": fm.get("priority", "medium"),
                "description": fm.get("description", "").strip()[:200],
                "tags": fm.get("tags", []),
                "objectives": fm.get("objectives", []),
                "milestones": fm.get("milestones", []),
                "updated_at": str(fm.get("updated_at", "")),
                "vault_path": str(proj_file),
            }

    # Now scan real directories for live data
    proj_dirs = _get_project_dirs()
    for pid, pdir in proj_dirs.items():
        scan = _scan_project_files(pdir)
        if scan:
            if pid not in projects:
                # Project not in vault yet — create entry from scan
                proj_info = next((p for p in PROJECT_MAP if p["id"] == pid), {})
                projects[pid] = {
                    "id": pid,
                    "title": pdir.name,
                    "status": proj_info.get("status", "unknown"),
                    "priority": proj_info.get("priority", "medium"),
                    "description": f"Project at {pdir}",
                    "tags": [],
                    "objectives": [],
                    "milestones": [],
                    "updated_at": "",
                    "vault_path": "",
                }
            projects[pid]["live_files"] = scan["total_files"]
            projects[pid]["live_languages"] = scan["languages"]
            projects[pid]["live_last_modified"] = scan["last_modified"]
            projects[pid]["live_last_modified_str"] = scan["last_modified_str"]
            projects[pid]["real_path"] = str(pdir)

    return projects


def _detect_updates(projects):
    """Detect which projects have been modified recently (within last 24 hours)."""
    now = time.time()
    updates = []
    for pid, p in projects.items():
        last_mod = p.get("live_last_modified", 0)
        if last_mod and (now - last_mod) < 86400:
            hours_ago = int((now - last_mod) / 3600)
            minutes_ago = int((now - last_mod) / 60) % 60
            if hours_ago > 0:
                time_str = f"{hours_ago}h {minutes_ago}m ago"
            else:
                time_str = f"{minutes_ago} minutes ago"
            updates.append((pid, p, time_str))
    return updates


def _format_project_summary(p):
    """Format a project into a spoken summary."""
    title = p.get("title", p.get("id", "Unknown"))
    status = p.get("status", "unknown")
    priority = p.get("priority", "medium")
    langs = ", ".join(p.get("live_languages", [])[:3])
    files = p.get("live_files", "?")
    objectives = p.get("objectives", [])
    done = sum(1 for o in objectives if o.get("status") == "completed")
    total = len(objectives)

    parts = [f"{title} ({status}, {priority} priority)"]
    if langs:
        parts.append(f"uses {langs}")
    parts.append(f"{files} files")
    if total > 0:
        parts.append(f"{done} of {total} objectives done")
    return ", ".join(parts)


def _ensure_project_map():
    """Populate PROJECT_MAP by scanning BASE_DIR subdirectories if empty."""
    global PROJECT_MAP
    if PROJECT_MAP:
        return
    try:
        from config import BASE_DIR
        base = Path(BASE_DIR).parent
        for i, d in enumerate(sorted(base.iterdir())):
            if d.is_dir() and not d.name.startswith(".") and d.name not in ("node_modules", "__pycache__"):
                PROJECT_MAP.append({
                    "dir": str(d), "id": f"proj_{i:03d}",
                    "status": "active", "priority": "medium",
                })
    except Exception:
        pass


def register(handler):
    """Called by Jarvis plugin loader."""
    _ensure_project_map()
    if not PROJECT_MAP and not BRAIN_ROOT:
        print("[PLUGIN] Brain bridge: No BRAIN_ROOT or projects configured. Set BRAIN_ROOT env var.")

    @handler.command("brain_status", patterns=["brain status", "project status", "what am i working on"])
    def brain_status(_=""):
        projects = _load_all_projects()
        active = [p for p in projects.values() if p.get("status") == "active"]
        paused = [p for p in projects.values() if p.get("status") == "paused"]
        completed = [p for p in projects.values() if p.get("status") == "completed"]

        handler.speak(
            f"You have {len(active)} active projects, {len(paused)} paused, and {len(completed)} completed."
        )

        for p in active:
            handler.speak(_format_project_summary(p))

        if paused:
            paused_names = [p.get("title", p.get("id")) for p in paused]
            handler.speak(f"Paused projects: {', '.join(paused_names)}")

    @handler.command("brain_project", patterns=["how is project {name}", "project {name}", "brain project {name}"])
    def brain_project(name):
        if not name:
            handler.speak("Which project would you like to know about?")
            return

        projects = _load_all_projects()
        name_lower = name.lower()

        # Match by title, ID, or partial name
        match = None
        for p in projects.values():
            title = p.get("title", "").lower()
            pid = p.get("id", "").lower()
            if name_lower in title or name_lower in pid or title in name_lower:
                match = p
                break

        if not match:
            handler.speak(f"I couldn't find a project matching '{name}'. Say 'brain status' to see all projects.")
            return

        handler.speak(_format_project_summary(match))

        # Mention recent activity
        last_mod = match.get("live_last_modified_str", "")
        if last_mod and last_mod != "unknown":
            handler.speak(f"Last modified: {last_mod}")

    @handler.command("brain_updates", patterns=["brain updates", "what changed", "any updates", "recent changes"])
    def brain_updates(_=""):
        projects = _load_all_projects()
        updates = _detect_updates(projects)

        if not updates:
            handler.speak("No projects have been modified in the last 24 hours.")
            return

        handler.speak(f"I found {len(updates)} recently updated projects.")
        for pid, p, time_str in updates[:5]:
            title = p.get("title", pid)
            handler.speak(f"{title}, updated {time_str}.")

    @handler.command("brain_summary", patterns=["brain summary", "daily summary", "how was my day"])
    def brain_summary(_=""):
        projects = _load_all_projects()
        updates = _detect_updates(projects)
        active = [p for p in projects.values() if p.get("status") == "active"]

        parts = [f"You have {len(active)} active projects."]
        if updates:
            parts.append(f"{len(updates)} were updated recently.")
            for pid, p, time_str in updates[:3]:
                title = p.get("title", pid)
                langs = ", ".join(p.get("live_languages", [])[:2])
                if langs:
                    parts.append(f"{title} ({langs}), updated {time_str}.")
                else:
                    parts.append(f"{title}, updated {time_str}.")
        else:
            parts.append("No recent updates today.")

        handler.speak(" ".join(parts))

    # ── Brain Health & Analytics ─────────────────────────────

    @handler.command("brain_health", patterns=["brain health", "vault health", "how is the vault"])
    def brain_health(_=""):
        try:
            sys.path.insert(0, str(BRAIN_ROOT))
            from brain.health import compute_health_score
            h = compute_health_score()
            score = sum(v for k, v in h.items() if isinstance(v, float)) / 6 * 100
            handler.speak(
                f"Vault health: grade {h['health_grade']}, score {score:.0f} out of 100. "
                f"{h['total_files']} files, {h['orphan_count']} orphans, {h['stale_count']} stale."
            )
        except Exception as e:
            handler.speak(f"Could not check vault health: {e}")

    @handler.command("brain_graph", patterns=["brain graph", "knowledge graph", "graph stats"])
    def brain_graph(_=""):
        try:
            sys.path.insert(0, str(BRAIN_ROOT))
            from brain.graph import KnowledgeGraph
            graph = KnowledgeGraph()
            handler.speak(
                f"Knowledge graph: {len(graph.nodes)} nodes, {len(graph.edges)} edges. "
                f"Top hubs: {', '.join(n for n, _ in graph.get_hubs(3))}."
            )
        except Exception as e:
            handler.speak(f"Could not check graph: {e}")

    @handler.command("brain_beliefs", patterns=["brain beliefs", "what do i believe", "beliefs"])
    def brain_beliefs(_=""):
        try:
            sys.path.insert(0, str(BRAIN_ROOT))
            from brain.beliefs import BeliefStore
            store = BeliefStore()
            active = store.list_active()
            if not active:
                handler.speak("No beliefs recorded yet.")
                return
            parts = [f"You have {len(active)} active beliefs."]
            for b in active[:3]:
                parts.append(f"{b.title} (confidence: {b.confidence:.0%}).")
            handler.speak(" ".join(parts))
        except Exception as e:
            handler.speak(f"Could not check beliefs: {e}")

    @handler.command("brain_episodes", patterns=["brain episodes", "past decisions", "what have i decided"])
    def brain_episodes(_=""):
        try:
            sys.path.insert(0, str(BRAIN_ROOT))
            from brain.episodes import EpisodeStore
            store = EpisodeStore()
            episodes = store.list_all()
            if not episodes:
                handler.speak("No episodes recorded yet.")
                return
            handler.speak(f"You have {len(episodes)} recorded decisions.")
            for ep in episodes[:3]:
                handler.speak(f"{ep.title}: {ep.decision[:80]}.")
        except Exception as e:
            handler.speak(f"Could not check episodes: {e}")

    print("[PLUGIN] Brain bridge loaded (v2 - with health, graph, beliefs, episodes)")
