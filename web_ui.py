import json
import threading
from queue import Queue
from config import WEB_UI_PORT, WEB_UI_HOST, WEB_UI_TOKEN

_flask_ok = False
_sock_ok = False
try:
    from flask import Flask, render_template_string, request, jsonify
    _flask_ok = True
except ImportError:
    Flask = None
    render_template_string = None
try:
    from flask_sock import Sock
    _sock_ok = True
except ImportError:
    Sock = None

if not _flask_ok:
    print("[WEB] Flask not installed. Run: pip install flask flask-sock")
if _flask_ok and not _sock_ok:
    print("[WEB] flask-sock not installed. Run: pip install flask-sock")

HTML = """<!DOCTYPE html>
<html><head><title>JARVIS</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { background:#0a0a1a; color:#00e5ff; font-family:Consolas,monospace; display:flex; flex-direction:column; height:100vh; }
#log { flex:1; overflow-y:auto; padding:20px; font-size:14px; line-height:1.6; }
.msg { margin:4px 0; padding:6px 10px; border-radius:4px; }
.msg.user { color:#ffab00; background:#1a1a2e; }
.msg.jarvis { color:#00e5ff; background:#0d1a2e; }
.msg.system { color:#78909c; }
.msg.error { color:#ff1744; background:#2e0d0d; }
.msg.thinking { color:#ab47bc; }
#input-row { display:flex; padding:12px; gap:8px; background:#0d0d20; border-top:1px solid #00e5ff33; }
#input { flex:1; background:#0a0a1a; color:#00e5ff; border:1px solid #00e5ff44; padding:12px; font:14px Consolas,monospace; border-radius:4px; outline:none; }
#input:focus { border-color:#00e5ff; }
#send { background:#00e5ff; color:#0a0a1a; border:none; padding:12px 24px; font:bold 14px Consolas; border-radius:4px; cursor:pointer; }
#send:hover { background:#00b8d4; }
#status { text-align:center; padding:6px; font-size:12px; color:#1a237e; letter-spacing:2px; }
</style></head><body>
<div id="status">STANDBY</div>
<div id="log"></div>
<div id="input-row">
<input id="input" placeholder="Type a command..." autofocus>
<button id="send" onclick="send()">SEND</button>
</div>
<script>
let ws = null;
let token = localStorage.getItem('jarvis_token') || prompt('Jarvis access token:');
if(token) localStorage.setItem('jarvis_token', token);

function connect() {
    const url = token ? 'ws://'+location.host+'/ws?token='+encodeURIComponent(token) : 'ws://'+location.host+'/ws';
    ws = new WebSocket(url);
    ws.onmessage = e => {
        const data = JSON.parse(e.data);
        if(data.cmd === 'add_text') addLine(data.text, data.tag);
        if(data.cmd === 'status') document.getElementById('status').textContent = data.value;
        if(data.cmd === 'error') { addLine(data.value, 'error'); document.getElementById('status').textContent = 'UNAUTHORIZED'; }
    };
    ws.onopen = () => { addLine('Connected to Jarvis web UI.','system'); document.getElementById('status').textContent = 'STANDBY'; };
    ws.onclose = () => { addLine('Disconnected. Reconnecting...','error'); document.getElementById('status').textContent = 'DISCONNECTED'; setTimeout(connect, 2000); };
    ws.onerror = () => ws.close();
}
connect();

function addLine(text, tag) {
    const log = document.getElementById('log');
    const d = document.createElement('div');
    d.className = 'msg '+tag;
    d.textContent = text;
    log.appendChild(d);
    log.scrollTop = log.scrollHeight;
}
function send() {
    const inp = document.getElementById('input');
    const text = inp.value.trim();
    if(!text) return;
    addLine('You: '+text, 'user');
    ws.send(text);
    inp.value = '';
}
document.getElementById('input').addEventListener('keydown', e => { if(e.key==='Enter') send(); });
</script></body></html>"""


class WebUI:
    def __init__(self, on_command=None):
        self._on_command = on_command
        self._app = None
        self._sock = None
        self._clients = set()
        self._lock = threading.Lock()

    def start(self):
        if Flask is None:
            print("[WEB] Flask not installed. Run: pip install flask flask-sock")
            return
        self._app = Flask(__name__)
        self._sock = Sock(self._app)

        @self._app.route("/")
        def index():
            return render_template_string(HTML)

        @self._app.route("/auth")
        def auth():
            t = request.args.get("token", "")
            if WEB_UI_TOKEN and t != WEB_UI_TOKEN:
                return jsonify({"ok": False, "error": "Invalid token"}), 403
            return jsonify({"ok": True})

        @self._sock.route("/ws")
        def ws(wsock, **kwargs):
            from flask import request as flask_req
            token = flask_req.args.get("token", "") or ""
            if WEB_UI_TOKEN and token != WEB_UI_TOKEN:
                try:
                    wsock.send(json.dumps({"cmd": "error", "value": "Invalid token"}))
                except Exception:
                    pass
                return
            with self._lock:
                self._clients.add(wsock)
            try:
                for msg in wsock:
                    if self._on_command:
                        self._on_command(msg)
            except Exception:
                pass
            finally:
                with self._lock:
                    self._clients.discard(wsock)

        t = threading.Thread(
            target=lambda: self._app.run(host=WEB_UI_HOST, port=WEB_UI_PORT, debug=False, use_reloader=False),
            daemon=True,
        )
        t.start()
        print(f"[WEB] UI at http://{WEB_UI_HOST}:{WEB_UI_PORT}")

    def send(self, cmd, **kwargs):
        with self._lock:
            payload = json.dumps({"cmd": cmd, **kwargs})
            dead = set()
            for c in self._clients:
                try:
                    c.send(payload)
                except Exception:
                    dead.add(c)
            self._clients -= dead

    def add_text(self, text, tag="jarvis"):
        self.send("add_text", text=text, tag=tag)

    def set_status(self, status):
        self.send("status", value=status.upper())
