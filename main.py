"""Jarvis - Personal Voice-Controlled AI Assistant
Usage:
  python main.py              # GUI + voice mode
  python main.py --headless   # Web UI + voice (no Tkinter)
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    headless = "--headless" in sys.argv
    enable_web = "--web" in sys.argv
    from jarvis_core import Jarvis
    assistant = Jarvis(headless=headless, enable_web=enable_web)
    try:
        assistant.run()
    except KeyboardInterrupt:
        assistant.stop()
        print("\nJarvis stopped.")


if __name__ == "__main__":
    main()
