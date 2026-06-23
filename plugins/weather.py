import requests


def register(handler):
    @handler.command("weather", patterns=[
        "what's the weather", "weather in {city}",
        "tell me the weather", "how's the weather",
    ])
    def weather(city=""):
        city = city.strip() or "auto"
        try:
            if city == "auto":
                ip = requests.get("https://ipinfo.io/json", timeout=5).json()
                city = ip.get("city", "New York")
            url = f"https://wttr.in/{city}?format=%C+%t+%h+%w"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                handler.speak(f"Weather in {city}: {resp.text.strip()}")
            else:
                handler.speak(f"Couldn't get weather for {city}.")
        except Exception:
            handler.speak("Couldn't reach weather service.")
