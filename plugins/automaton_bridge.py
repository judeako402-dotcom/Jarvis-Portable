"""
Jarvis Automaton Bridge Plugin v2
Connects Jarvis to the Conway Automaton pipeline via Brain modules.
Voice: "What is the automaton doing?" / "Automaton status" / "How's the pipeline"
"""

import os
import sys
import subprocess
import json
import re
from pathlib import Path
from datetime import datetime, timezone

BASE = os.environ.get("JARVIS_BASE_DIR", "")
BRAIN_ROOT = Path(os.environ.get("BRAIN_ROOT", ""))
AUTOMATON_DIR = Path(os.environ.get("AUTOMATON_DIR", ""))
MONEY_DIR = Path(os.environ.get("MONEY_SCHEME_DIR", ""))
MONITOR_SCRIPT = AUTOMATON_DIR / "scripts" / "automaton_monitor.py" if AUTOMATON_DIR else Path()
VAULT_NOTE = Path(os.environ.get("BRAIN_VAULT_NOTE", ""))


def _run_pipeline_cmd(cmd: str, timeout=60) -> str:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, cwd=str(MONEY_DIR))
        return (r.stdout + r.stderr)[:1000]
    except subprocess.TimeoutExpired:
        return "Command timed out"
    except Exception as e:
        return f"Error: {e}"


def _read_vault_note():
    if not VAULT_NOTE.exists():
        return None
    try:
        content = VAULT_NOTE.read_text(encoding="utf-8", errors="replace")
        parts = content.split("---", 2)
        if len(parts) < 3:
            return None
        body = parts[2].strip()
        return body[:800]
    except Exception:
        return None


def _get_brain_automaton_status():
    try:
        sys.path.insert(0, str(BRAIN_ROOT))
        from brain.automaton import get_pipeline_status, get_revenue_estimate, get_task_summary
        status = get_pipeline_status()
        revenue = get_revenue_estimate()
        tasks = get_task_summary()
        return {"status": status, "revenue": revenue, "tasks": tasks}
    except Exception as e:
        return {"error": str(e)}


def register(handler):
    if not BRAIN_ROOT or not BRAIN_ROOT.exists():
        print(f"[PLUGIN] Automaton bridge disabled: BRAIN_ROOT not found ({BRAIN_ROOT})")
        return

    @handler.command("automaton_status", patterns=[
        "automaton status", "what is the automaton doing", "how is the automaton",
        "pipeline status", "how is the pipeline", "automaton", "money scheme status",
    ])
    def automaton_status(_=""):
        data = _get_brain_automaton_status()
        if "error" in data:
            handler.speak(f"Could not get automaton status: {data['error']}")
            return

        status = data["status"]
        tasks = data["tasks"]
        now = datetime.now(timezone.utc).strftime("%H:%M UTC")

        parts = [f"Automaton pipeline status as of {now}."]
        parts.append(f"Name: {status['automaton_name']}.")
        parts.append(f"Queue has {status['queue_depth']} items.")
        parts.append(f"System is {status['health']} ({status['health_score']}/100).")
        parts.append(f"Revenue: ${status['revenue']:.2f}. Uploads: {status['uploads']}.")
        parts.append(f"Tasks: {tasks['completed']} completed, {tasks['pending']} pending, {tasks['blocked']} blocked.")
        parts.append(f"Model: {status['inference_model']}.")

        handler.speak(" ".join(parts))

    @handler.command("automaton_queue", patterns=[
        "automaton queue", "queue status", "how many items in queue",
    ])
    def automaton_queue(_=""):
        data = _get_brain_automaton_status()
        if "error" in data:
            handler.speak(f"Could not check queue: {data['error']}")
            return
        status = data["status"]
        handler.speak(f"The queue has {status['queue_depth']} items. System health: {status['health']} ({status['health_score']}/100).")

    @handler.command("automaton_revenue", patterns=[
        "automaton revenue", "how much money", "pipeline earnings", "money scheme revenue",
        "potential earnings", "how much can i make", "revenue estimate",
    ])
    def automaton_revenue(_=""):
        data = _get_brain_automaton_status()
        if "error" in data:
            handler.speak(f"Could not check revenue: {data['error']}")
            return
        status = data["status"]
        revenue = data["revenue"]

        parts = [f"Current revenue: ${status['revenue']:.2f}."]
        parts.append(f"Digital products ready to sell: {revenue['digital_products']['count']} products.")
        parts.append(f"Digital product potential: {revenue['digital_products']['annual_estimate']} per year.")
        parts.append(f"YouTube potential once monetized: {revenue['youtube_kids']['annual_estimate']} per year.")
        parts.append(f"Combined pipeline potential: {revenue['combined_pipeline']['annual_estimate']} per year.")
        parts.append(f"Digital products status: {revenue['digital_products']['status']}.")
        parts.append(f"YouTube status: {revenue['youtube_kids']['status']}.")

        handler.speak(" ".join(parts))

    @handler.command("automaton_tasks", patterns=[
        "automaton tasks", "what tasks are there", "task status",
    ])
    def automaton_tasks(_=""):
        data = _get_brain_automaton_status()
        if "error" in data:
            handler.speak(f"Could not check tasks: {data['error']}")
            return
        tasks = data["tasks"]

        parts = [f"You have {tasks['total']} tasks total."]
        parts.append(f"{tasks['completed']} completed, {tasks['pending']} pending, {tasks['blocked']} blocked.")

        for task in tasks["tasks"]:
            status_icon = "done" if task["status"] == "completed" else "pending" if task["status"] == "pending" else "blocked"
            parts.append(f"{task['id']}: {task['title']} [{status_icon}].")

        handler.speak(" ".join(parts))

    @handler.command("automaton_health", patterns=[
        "automaton health", "is automaton ok", "system health",
    ])
    def automaton_health(_=""):
        data = _get_brain_automaton_status()
        if "error" in data:
            handler.speak(f"Could not check health: {data['error']}")
            return
        status = data["status"]
        handler.speak(
            f"Automaton health: {status['health']} ({status['health_score']}/100). "
            f"Wallet: {status['wallet_address'][:10]}... "
            f"Model: {status['inference_model']}."
        )

    print("[PLUGIN] Automaton bridge loaded v2 (with Brain integration)")
