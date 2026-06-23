import os
import math
import queue
import tkinter as tk


THEME = {
    "bg": "#0a0a1a",
    "fg": "#00e5ff",
    "accent": "#00e5ff",
    "text_bg": "#0d0d20",
    "text_fg": "#b0bec5",
    "speaking": "#00e5ff",
    "listening": "#ffab00",
    "idle": "#1a237e",
    "font": ("Consolas", 11),
    "status_font": ("Consolas", 18, "bold"),
}

AUTOCOMPLETE_COMMANDS = [
    "/time", "/date", "/screenshot", "/readscreen", "/ocr", "/describe",
    "/joke", "/cpu", "/ram", "/battery",
    "/volume up", "/volume down", "/mute",
    "/open ", "/close ", "/search ", "/wiki ", "/play ",
    "/ask ", "/code ",
    "/tab ", "/search tab ",
    "/clip save", "/clip list", "/clip paste ",
    "/note ", "/notes ", "/remind ", "/reminders",
    "/list", "/read ", "/write ", "/delete ", "/copy ", "/move ", "/find ",
    "/weather ",
    "/hass status",
    "/github status", "/github push", "/github pull", "/github repos", "/github create ",
    "/brain status", "/brain project ", "/brain updates", "/brain summary",
    "/help", "/exit",
    "/mic list", "/mic select ",
]


class JarvisVisualizer:
    def __init__(self, on_text_command=None):
        self.on_text_command = on_text_command
        self.root = tk.Tk()
        self.root.title("JARVIS")
        self.root.configure(bg=THEME["bg"])
        self.root.geometry("520x750")

        self.cmd_queue = queue.Queue()
        self.status = "idle"
        self.angle = 0
        self.pulse = 0
        self.wave_offset = 0
        self.conversation = []
        self.intent_text = ""
        self._tray_icon = None

        self._build_ui()
        self._center_window()
        self._animate()
        self.root.after(100, self._process_queue)
        self._setup_tray()
        self.root.protocol("WM_DELETE_WINDOW", self._minimize_to_tray)

    def _center_window(self):
        self.root.update_idletasks()
        w, h = 520, 750
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

    def _setup_tray(self):
        pass  # Disabled - pystray interferes with Tkinter message pump

    def _minimize_to_tray(self):
        self.root.withdraw()
        self.root.after(100, self._check_restore)

    def _check_restore(self):
        try:
            if self.root.state() == "withdrawn":
                self.root.after(500, self._check_restore)
        except tk.TclError:
            pass

    def _restore_from_tray(self):
        self.root.deiconify()
        self.root.lift()

    def _exit_app(self):
        self.root.quit()
        os._exit(0)

    def _build_ui(self):
        input_area = tk.Frame(self.root, bg=THEME["bg"])
        input_area.pack(side="bottom", fill="x", padx=15, pady=(4, 10))

        input_label = tk.Label(input_area, text="TYPE YOUR COMMAND:",
                                font=("Consolas", 9, "bold"), bg=THEME["bg"], fg=THEME["accent"])
        input_label.pack(anchor="w", pady=(0, 3))

        row = tk.Frame(input_area, bg="#1a1a3a", bd=2, relief="solid")
        row.pack(fill="x")

        autocomplete_frame = tk.Frame(row, bg="#0d0d20")
        autocomplete_frame.pack(side="left", fill="x", expand=True, padx=(8, 4), pady=4)

        self.input_var = tk.StringVar()
        self.input_var.trace("w", self._on_input_change)
        self.input_entry = tk.Entry(
            autocomplete_frame, textvariable=self.input_var, font=("Consolas", 13),
            bg="#0d0d20", fg=THEME["accent"], insertbackground=THEME["accent"],
            bd=0, highlightthickness=0,
        )
        self.input_entry.pack(fill="x", ipady=8)
        self.input_entry.bind("<Return>", self._on_submit)
        self.input_entry.bind("<Tab>", self._on_tab_complete)
        self.input_entry.bind("<Up>", self._navigate_suggestions)
        self.input_entry.bind("<Down>", self._navigate_suggestions)

        self.suggestions_listbox = tk.Listbox(
            row, font=("Consolas", 10), bg="#1a1a3a", fg=THEME["accent"],
            bd=0, highlightthickness=0, height=4, exportselection=False,
        )
        self.suggestions_listbox.bind("<ButtonRelease-1>", self._on_suggestion_click)
        self._suggestions = []
        self._selected_suggestion = -1

        self.send_btn = tk.Button(
            row, text="SEND", font=("Consolas", 11, "bold"),
            bg=THEME["accent"], fg=THEME["bg"], activebackground="#00b8d4",
            activeforeground=THEME["bg"], bd=0, padx=20, pady=8,
            command=self._on_submit,
        )
        self.send_btn.pack(side="right", padx=(4, 8), pady=4)

        self.canvas = tk.Canvas(self.root, width=520, height=200, bg=THEME["bg"], highlightthickness=0)
        self.canvas.pack(side="top")

        self.intent_label = tk.Label(self.root, text="", font=("Consolas", 10),
                                      bg=THEME["bg"], fg=THEME["text_fg"])
        self.intent_label.pack(side="top", pady=(0, 1))

        self.status_label = tk.Label(self.root, text="STANDBY", font=THEME["status_font"],
                                      bg=THEME["bg"], fg=THEME["idle"])
        self.status_label.pack(side="top", pady=(0, 4))

        sep = tk.Frame(self.root, height=2, bg=THEME["accent"])
        sep.pack(side="top", fill="x", padx=15, pady=(0, 4))

        self.text_frame = tk.Frame(self.root, bg=THEME["text_bg"], bd=1, relief="sunken")
        self.text_frame.pack(side="top", fill="both", expand=True, padx=15, pady=(0, 4))

        self.text_box = tk.Text(self.text_frame, font=THEME["font"],
                                 bg=THEME["text_bg"], fg=THEME["text_fg"],
                                 bd=0, padx=10, pady=8, wrap="word", state="disabled")
        self.text_box.tag_config("jarvis", foreground="#00e5ff")
        self.text_box.tag_config("user", foreground="#ffab00")
        self.text_box.tag_config("system", foreground="#78909c")
        self.text_box.tag_config("error", foreground="#ff1744")
        self.text_box.tag_config("thinking", foreground="#ab47bc")

        scrollbar = tk.Scrollbar(self.text_frame, command=self.text_box.yview)
        scrollbar.pack(side="right", fill="y")
        self.text_box.config(yscrollcommand=scrollbar.set)
        self.text_box.pack(side="left", fill="both", expand=True)

        self._draw_idle()

    def _on_input_change(self, *args):
        text = self.input_var.get()
        if not text.startswith("/"):
            self._hide_suggestions()
            return
        self._suggestions = [c for c in AUTOCOMPLETE_COMMANDS if c.startswith(text) and c != text]
        self._show_suggestions()

    def _show_suggestions(self):
        self.suggestions_listbox.pack_forget()
        if not self._suggestions:
            return
        self.suggestions_listbox.delete(0, "end")
        for cmd in self._suggestions:
            self.suggestions_listbox.insert("end", cmd)
        self.suggestions_listbox.pack(fill="x", side="bottom")
        self._selected_suggestion = -1

    def _hide_suggestions(self):
        self.suggestions_listbox.pack_forget()
        self._suggestions = []
        self._selected_suggestion = -1

    def _on_tab_complete(self, event):
        if not self._suggestions:
            return "break"
        self._apply_suggestion(self._suggestions[0])
        return "break"

    def _navigate_suggestions(self, event):
        if not self._suggestions:
            return
        if event.keysym == "Down":
            self._selected_suggestion = min(self._selected_suggestion + 1, len(self._suggestions) - 1)
        elif event.keysym == "Up":
            self._selected_suggestion = max(self._selected_suggestion - 1, 0)
        self.suggestions_listbox.selection_clear(0, "end")
        self.suggestions_listbox.selection_set(self._selected_suggestion)
        self.suggestions_listbox.activate(self._selected_suggestion)

    def _on_suggestion_click(self, event):
        sel = self.suggestions_listbox.curselection()
        if sel:
            self._apply_suggestion(self._suggestions[sel[0]])

    def _apply_suggestion(self, cmd):
        self.input_var.set(cmd)
        self.input_entry.icursor("end")
        self._hide_suggestions()

    def _on_submit(self, event=None):
        text = self.input_var.get().strip()
        if not text:
            return
        self.input_entry.delete(0, "end")
        self._hide_suggestions()
        if self.on_text_command:
            self.on_text_command(text)

    def _particle_orb(self, cx, cy, count, base_r, color, spread, wave_mul=1):
        self.canvas.delete("all")
        for i in range(count):
            a = math.radians(self.angle + i * (360 / count))
            wave = math.sin(self.wave_offset + i * 0.5) * wave_mul
            dist = base_r + spread * (0.5 + 0.5 * wave)
            x = cx + dist * math.cos(a)
            y = cy + dist * math.sin(a)
            brightness = 0.5 + 0.5 * (0.5 + 0.5 * wave)
            size = 1.5 + abs(wave) * 2.5
            c = self._blend(color, brightness)
            self.canvas.create_oval(x - size, y - size, x + size, y + size, fill=c, outline="")
            if i % 4 == 0:
                trail = self._blend(color, brightness * 0.3)
                tx = cx + (dist + 8) * math.cos(a - 0.15)
                ty = cy + (dist + 8) * math.sin(a - 0.15)
                self.canvas.create_oval(tx - size * 0.6, ty - size * 0.6, tx + size * 0.6, ty + size * 0.6, fill=trail, outline="")
        inner = 12 + 4 * math.sin(self.pulse * 2)
        glow = self._blend(color, 0.3)
        self.canvas.create_oval(cx - inner - 10, cy - inner - 10, cx + inner + 10, cy + inner + 10, fill=glow, outline="")
        self.canvas.create_oval(cx - inner, cy - inner, cx + inner, cy + inner, fill=color, outline="")
        return cx, cy

    def _draw_idle(self):
        self._particle_orb(260, 100, 24, 50, THEME["idle"], 12, 0.4)
        self.canvas.create_text(260, 100, text="J.A.R.V.I.S.", font=("Consolas", 8, "bold"),
                                fill=THEME["accent"], anchor="center")

    def _draw_listening(self):
        self._particle_orb(260, 100, 36, 55, THEME["listening"], 20, 0.8)
        self.canvas.create_text(260, 100, text="MIC", font=("Consolas", 9, "bold"),
                                fill=THEME["bg"], anchor="center")

    def _draw_speaking(self):
        self.wave_offset += 0.08
        cx, cy = self._particle_orb(260, 100, 40, 55, THEME["speaking"], 28, 1.2)
        for i in range(8):
            a = math.radians(self.angle * 1.5 + i * 45)
            wave = math.sin(self.wave_offset + i)
            bx = cx + 65 * math.cos(a)
            by = cy + 65 * math.sin(a)
            ex = cx + (65 + 15 * abs(wave)) * math.cos(a)
            ey = cy + (65 + 15 * abs(wave)) * math.sin(a)
            c = self._blend(THEME["speaking"], 0.3 + 0.7 * abs(wave))
            self.canvas.create_line(bx, by, ex, ey, fill=c, width=2, capstyle="round")
        self.canvas.create_text(260, 100, text="TALKING", font=("Consolas", 9, "bold"),
                                fill=THEME["bg"], anchor="center")

    def _blend(self, color, factor):
        r = int(int(color[1:3], 16) * min(factor, 1.5))
        g = int(int(color[3:5], 16) * min(factor, 1.5))
        b = int(int(color[5:7], 16) * min(factor, 1.5))
        return f"#{min(r,255):02x}{min(g,255):02x}{min(b,255):02x}"

    def _animate(self):
        self.angle = (self.angle + 3) % 360
        self.pulse += 0.08
        self.wave_offset += 0.1
        draw = {"idle": self._draw_idle, "listening": self._draw_listening, "speaking": self._draw_speaking}
        draw.get(self.status, self._draw_idle)()
        self.root.after(40, self._animate)

    def _process_queue(self):
        try:
            while True:
                msg = self.cmd_queue.get_nowait()
                self._handle_message(msg)
        except queue.Empty:
            pass
        self.root.after(100, self._process_queue)

    def _handle_message(self, msg):
        cmd = msg.get("cmd")
        if cmd == "status":
            self.status = msg.get("value", "idle")
            labels = {"idle": "STANDBY", "listening": "LISTENING", "speaking": "SPEAKING"}
            colors = {"idle": THEME["idle"], "listening": THEME["listening"], "speaking": THEME["speaking"]}
            self.status_label.config(text=labels.get(self.status, "STANDBY"),
                                     fg=colors.get(self.status, THEME["idle"]))
        elif cmd == "add_text":
            text = msg.get("text", "")
            tag = msg.get("tag", "jarvis")
            self.conversation.append(text)
            self.text_box.config(state="normal")
            self.text_box.insert("end", text + "\n", tag)
            self.text_box.see("end")
            self.text_box.config(state="disabled")
        elif cmd == "intent":
            self.intent_text = msg.get("text", "")
            self.intent_label.config(text=f"[{self.intent_text}]" if self.intent_text else "")

    def set_status(self, status):
        self.cmd_queue.put({"cmd": "status", "value": status})

    def add_text(self, text, tag="jarvis"):
        self.cmd_queue.put({"cmd": "add_text", "text": text, "tag": tag})

    def show_intent(self, text):
        self.cmd_queue.put({"cmd": "intent", "text": text})

    def run(self):
        self.root.mainloop()

    def stop(self):
        if self.root:
            self.root.quit()
