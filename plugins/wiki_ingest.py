"""
Jarvis Wiki Ingest Plugin — Karpathy LLM Wiki for voice assistants.

Voice commands:
  "Jarvis, ingest this article [URL]"     → Downloads + compiles into wiki
  "Jarvis, ingest this file [path]"       → Reads local file + compiles
  "Jarvis, ask the knowledge base [q]"    → Searches wiki pages
  "Jarvis, what's in the knowledge base"  → Lists wiki pages
  "Jarvis, knowledge base stats"          → Shows wiki statistics

Slash commands:
  /wiki ingest <url>     - Ingest a URL
  /wiki ingest <path>    - Ingest a local file
  /wiki query <question> - Search the wiki
  /wiki list             - List all wiki pages
  /wiki stats            - Show statistics
"""

import os
import re
import sys
from pathlib import Path

BRAIN_ROOT = Path(os.environ.get("BRAIN_ROOT", r"E:\The Brain"))
if str(BRAIN_ROOT) not in sys.path:
    sys.path.insert(0, str(BRAIN_ROOT))


def _get_brain():
    """Lazy-import and initialize the BrainBridge."""
    try:
        from brain.assistant_bridge import BrainBridge
        bridge = BrainBridge()
        bridge.initialize()
        return bridge
    except Exception as e:
        return None


def register(handler):
    """Called by Jarvis plugin loader."""

    @handler.command("wiki_ingest_url", patterns=["ingest this article {url}", "ingest article {url}", "ingest url {url}"])
    def wiki_ingest_url(url):
        """Ingest a URL into the knowledge base."""
        if not url:
            handler.speak("What URL should I ingest?")
            return
        bridge = _get_brain()
        if not bridge:
            handler.speak("The brain is not available.")
            return
        handler.speak(f"Downloading and compiling {url}...")
        try:
            result = bridge.ingest_source(url=url)
            if result.get("success"):
                pages = result.get("total_pages", 0)
                handler.speak(
                    f"Ingested! Created {pages} wiki pages from "
                    f"{result.get('word_count', 0)} words."
                )
            else:
                handler.speak(f"Ingestion failed: {result.get('error', 'unknown error')}")
        except Exception as e:
            handler.speak(f"Ingestion failed: {e}")

    @handler.command("wiki_ingest_file", patterns=["ingest this file {path}", "ingest file {path}"])
    def wiki_ingest_file(path):
        """Ingest a local file into the knowledge base."""
        if not path:
            handler.speak("What file should I ingest?")
            return
        bridge = _get_brain()
        if not bridge:
            handler.speak("The brain is not available.")
            return
        handler.speak(f"Reading and compiling {path}...")
        try:
            result = bridge.ingest_source(file_path=path)
            if result.get("success"):
                pages = result.get("total_pages", 0)
                handler.speak(
                    f"Ingested! Created {pages} wiki pages from "
                    f"{result.get('word_count', 0)} words."
                )
            else:
                handler.speak(f"Ingestion failed: {result.get('error', 'unknown error')}")
        except Exception as e:
            handler.speak(f"Ingestion failed: {e}")

    @handler.command("wiki_query", patterns=["ask the knowledge base {question}", "knowledge base query {question}", "ask wiki {question}"])
    def wiki_query(question):
        """Search the knowledge base."""
        if not question:
            handler.speak("What would you like to know?")
            return
        bridge = _get_brain()
        if not bridge:
            handler.speak("The brain is not available.")
            return
        try:
            result = bridge.query_wiki(question, n=3)
            matches = result.get("results", [])
            if not matches:
                handler.speak(f"I couldn't find anything about '{question}' in the knowledge base.")
                return
            # Summarize top results
            titles = [f"{m['title']} ({m['page_type']})" for m in matches[:3]]
            handler.speak(
                f"I found {len(matches)} relevant pages: "
                + ", ".join(titles)
            )
        except Exception as e:
            handler.speak(f"Knowledge base search failed: {e}")

    @handler.command("wiki_list", patterns=["what's in the knowledge base", "knowledge base pages", "list wiki pages"])
    def wiki_list(_=""):
        """List what's in the knowledge base."""
        bridge = _get_brain()
        if not bridge:
            handler.speak("The brain is not available.")
            return
        try:
            result = bridge.list_wiki_pages()
            total = result.get("total", 0)
            by_type = result.get("by_type", {})
            if total == 0:
                handler.speak("The knowledge base is empty. Ingest some articles to get started!")
                return
            parts = [f"{count} {ptype}" for ptype, count in by_type.items()]
            handler.speak(f"The knowledge base has {total} pages: {', '.join(parts)}.")
        except Exception as e:
            handler.speak(f"Could not list knowledge base: {e}")

    @handler.command("wiki_stats", patterns=["knowledge base stats", "wiki stats"])
    def wiki_stats(_=""):
        """Show knowledge base statistics."""
        bridge = _get_brain()
        if not bridge:
            handler.speak("The brain is not available.")
            return
        try:
            wiki_path = BRAIN_ROOT / "vault" / "wiki"
            raw_path = BRAIN_ROOT / "vault" / "raw"
            wiki_files = list(wiki_path.rglob("*.md")) if wiki_path.exists() else []
            raw_files = list(raw_path.glob("raw_*.md")) if raw_path.exists() else []
            handler.speak(
                f"Knowledge base: {len(wiki_files)} wiki pages, "
                f"{len(raw_files)} raw sources ingested."
            )
        except Exception as e:
            handler.speak(f"Could not get stats: {e}")

    @handler.command("wiki_compound", patterns=["search and save {question}", "ask and save {question}", "learn about {question}"])
    def wiki_compound(question):
        """Query wiki and file the answer back (Karpathy's compounding loop)."""
        if not question:
            handler.speak("What would you like me to learn about?")
            return
        bridge = _get_brain()
        if not bridge:
            handler.speak("The brain is not available.")
            return
        try:
            result = bridge.query_and_compound(question)
            answer = result.get("answer")
            if not answer:
                handler.speak(f"I couldn't find enough information about '{question}' to form an answer.")
                return
            filed = result.get("filed", False)
            confidence = result.get("confidence", 0)
            # Speak a summary
            preview = answer[:200].replace("\n", " ").strip()
            status = "and saved it to the knowledge base" if filed else "but didn't save it (low confidence)"
            handler.speak(f"Here's what I found {status}: {preview}...")
        except Exception as e:
            handler.speak(f"Knowledge compound failed: {e}")

    @handler.command("wiki_lint", patterns=["check knowledge health", "wiki health", "knowledge base health"])
    def wiki_lint(_=""):
        """Run health check on the knowledge base."""
        bridge = _get_brain()
        if not bridge:
            handler.speak("The brain is not available.")
            return
        try:
            result = bridge.lint_wiki()
            total = result.get("total_pages", 0)
            issues = result.get("issues", 0)
            has_errors = result.get("has_errors", False)
            summary = result.get("summary", {})

            if issues == 0:
                handler.speak(f"Knowledge base is healthy! {total} pages, no issues found.")
            else:
                parts = [f"{count} {itype}" for itype, count in summary.items()]
                status = "has errors" if has_errors else "has warnings"
                handler.speak(
                    f"Knowledge base {status}: {issues} issues across {total} pages. "
                    f"Issues: {', '.join(parts)}."
                )
        except Exception as e:
            handler.speak(f"Health check failed: {e}")

    print("[WIKI] Wiki plugin loaded. You can ingest, search, compound, and lint the knowledge base.")
