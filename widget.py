#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TokenPulse — desktop widget for Strata + ComfyUI.

Small frameless always-on-top card that collapses into a slim strip.
Talks over the network to agent.py (default http://127.0.0.1:8787).

Shows:
  * three circular gauges: GPU load, CPU load, GPU power
  * one sensor block, sorted by device: GPU -> VRAM (HBM) -> CPU -> RAM,
    each row carries load bar + temperature bar with real °C values
  * both token kinds: DECODE (output) and PREFILL (input) tokens/sec
  * persistent token counters today / all time, rounded to millions
  * real tok/s history chart (0 while the engine is idle)
  * per-request progress, recent requests, ComfyUI + Strata status

Linux + Windows, Python 3.8+, standard library only.

Run:  python3 widget.py [--server http://HOST:8787]
"""

import argparse
import json
import math
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

WINDOWS = os.name == "nt"
if WINDOWS:
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

FONT = "Segoe UI" if WINDOWS else "DejaVu Sans"
MONO = "Consolas" if WINDOWS else "DejaVu Sans Mono"

# ------------------------------------------------------------------ palette --
BG = "#060a12"
PANEL = "#0b1322"
PANEL2 = "#0f1a2d"
TRACK = "#18243a"
FAINT = "#111a2a"
STROKE = "#1e2c46"
TEXT = "#e9effc"
DIM = "#65748f"
CYAN = "#22d3ee"
CYAN_SOFT = "#8fd8ea"
CYAN_DARK = "#0d5361"
GREEN = "#34d399"
GREEN_SOFT = "#7ee5b8"
GREEN_DARK = "#0f4d3a"
PINK = "#f472b6"
PINK_SOFT = "#f7a8c8"
PINK_DARK = "#5c2140"
AMBER = "#fbbf24"
AMBER_DARK = "#5c4410"
VIOLET = "#a78bfa"
VIOLET_DARK = "#3c2d63"
RED = "#fb7185"
WHITE = "#ffffff"

CONFIG_PATH = Path.home() / ".tokenpulse" / "widget.json"
LEGACY_CONFIG = Path.home() / ".strata-monitor.json"
DEFAULTS = {
    "server": "http://127.0.0.1:8787",
    "interval": 1.0,
    "topmost": True,
    "collapsed": False,
    "daily_goal": 1_000_000,
    "x": None,
    "y": None,
}

W, H = 364, 812
COLLAPSED_H = 104
PAD = 12
BAR_W = 330

# circular gauges
RING = 96
TICKS = 36
SLIM_RING = 44

# sensor rows
NAME_W = 10
LOAD_W = 96
THERM_W = 64

# history chart
CHART_W = 330
CHART_H = 52
CHART_SLOTS = 48

EQ_SAMPLES = 48


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #

def load_config():
    cfg = dict(DEFAULTS)
    for path in (CONFIG_PATH, LEGACY_CONFIG):
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
            break
        except Exception:
            continue
    return cfg


def save_config(cfg):
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(CONFIG_PATH) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_PATH)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# network
# --------------------------------------------------------------------------- #

class Fetcher(threading.Thread):
    def __init__(self, url, interval=1.0):
        super().__init__(daemon=True)
        self.url = url.rstrip("/")
        self.interval = max(0.4, float(interval))
        self.data = None
        self.error = None
        self.latency = None
        self.ok_at = 0.0
        self._stop = threading.Event()
        self._lock = threading.Lock()

    def stop(self):
        self._stop.set()

    def set_url(self, url):
        with self._lock:
            self.url = url.rstrip("/")

    def run(self):
        while not self._stop.is_set():
            with self._lock:
                url = self.url
            t0 = time.perf_counter()
            try:
                with urlopen(url + "/api/stats", timeout=2.5) as r:
                    payload = json.loads(r.read().decode("utf-8", "replace"))
                self.data = payload
                self.error = None
                self.ok_at = time.time()
            except Exception as e:
                self.error = str(e)
            self.latency = (time.perf_counter() - t0) * 1000.0
            self._stop.wait(self.interval)


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #

def clamp(v, lo=0.0, hi=100.0):
    try:
        return max(lo, min(hi, float(v)))
    except Exception:
        return lo


def clamp01(v):
    try:
        return max(0.0, min(1.0, float(v)))
    except Exception:
        return 0.0


def short(v, n=32):
    s = str(v or "")
    return s if len(s) <= n else s[: n - 1] + "…"


def grouped(v):
    try:
        return "{:,}".format(int(v)).replace(",", " ")
    except Exception:
        return "—"


def big_num(v):
    """Counter display: from one million up, rounded to hundredths (16.30M)."""
    try:
        v = float(v)
    except Exception:
        return "—"
    if v >= 1_000_000_000:
        return "%.2fB" % (v / 1_000_000_000.0)
    if v >= 1_000_000:
        return "%.2fM" % (v / 1_000_000.0)
    return grouped(v)


def human_int(v):
    try:
        v = int(v)
    except Exception:
        return "—"
    if v >= 1_000_000_000:
        return "%.2fB" % (v / 1_000_000_000.0)
    if v >= 1_000_000:
        return "%.2fM" % (v / 1_000_000.0)
    if v >= 1000:
        return "%.1fK" % (v / 1000.0)
    return str(v)


def num(v, nd=1):
    try:
        v = float(v)
    except Exception:
        return "—"
    if nd == 0:
        return "%d" % round(v)
    return ("%%.%df" % nd) % v


def mix(c1, c2, t):
    try:
        t = max(0.0, min(1.0, t))
        a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
        b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
        return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))
    except Exception:
        return c1


def heat_gradient(t):
    """green -> amber -> red, used by the temperature bars."""
    t = clamp01(t)
    if t < 0.55:
        return mix(GREEN, AMBER, t / 0.55)
    return mix(AMBER, RED, (t - 0.55) / 0.45)


def ease_out(p):
    return 1.0 - (1.0 - p) ** 3


def polar(cx, cy, r, deg):
    a = math.radians(deg)
    return cx + r * math.sin(a), cy - r * math.cos(a)


# --------------------------------------------------------------------------- #
# circular gauge
# --------------------------------------------------------------------------- #

class Gauge:
    """Smooth segmented ring: built from short arc segments instead of a
    single Tk arc, so the circle has no visible stair-steps or seam."""

    def __init__(self, parent, caption, color, dark, size=RING, ticks=TICKS,
                 value_font=(MONO, 17, "bold"), sub_font=(FONT, 6, "bold"),
                 caption_font=None, show_caption=True, show_ticks=True):
        self.color = color
        self.dark = dark
        self.size = size
        self.mid = size / 2.0
        self.r_out = size * 0.407
        self.r_in = size * 0.306
        # halo rims live strictly outside the ring band, so the filled part
        # is exactly as thick as the empty track and never looks doubled
        self.r_halo_out = self.r_out + 2.0
        self.r_halo_in = self.r_in - 1.8
        self.r_tick_out = size * 0.465
        self.r_tick_in = size * 0.440
        self.n_ticks = ticks
        self.major = 3 if ticks >= 24 else 1
        self.show_ticks = show_ticks

        self.frame = tk.Frame(parent, bg=BG)
        self.canvas = tk.Canvas(self.frame, width=size, height=size, bg=BG,
                                highlightthickness=0)
        self.canvas.pack()
        if show_caption:
            self.label = tk.Label(self.frame, text=caption, bg=BG, fg=DIM,
                                  font=caption_font or (FONT, 6, "bold"))
            self.label.pack()

        c = self.canvas
        m = self.mid
        # 360° track band
        self.track = c.create_polygon(*self._band(self.r_out, self.r_in, 0, 360),
                                      fill=TRACK, outline="")
        # soft halo rims + main arc (hidden until there is a value)
        halo = mix(dark, BG, 0.25)
        self.halo_out = c.create_polygon(0, 0, fill=halo, outline="", state="hidden")
        self.halo_in = c.create_polygon(0, 0, fill=mix(dark, BG, 0.55),
                                        outline="", state="hidden")
        self.arc = c.create_polygon(0, 0, fill=color, outline="", state="hidden")
        self.edge = c.create_line(0, 0, 0, 0, width=1, fill=mix(color, WHITE, 0.45),
                                  state="hidden")

        # graduation ticks outside the ring
        self.ticks = []
        if show_ticks:
            for i in range(self.n_ticks):
                deg = i * 360.0 / self.n_ticks
                x1, y1 = polar(m, m, self.r_tick_in, deg)
                x2, y2 = polar(m, m, self.r_tick_out, deg)
                major = (i % self.major == 0)
                self.ticks.append(c.create_line(
                    x1, y1, x2, y2, width=2 if major else 1,
                    fill=mix(TRACK, BG, 0.2) if major else FAINT))

        self.txt = c.create_text(m, m - (size * 0.065), text="—", fill=TEXT,
                                 font=value_font)
        self.sub = c.create_text(m, m + (size * 0.12), text="", fill=DIM,
                                 font=sub_font or (FONT, 6, "bold"))

    # -- geometry -----------------------------------------------------------
    def _points(self, r, a0, a1):
        n = max(6, int(abs(a1 - a0) / 3.0))
        pts = []
        for i in range(n + 1):
            x, y = polar(self.mid, self.mid, r, a0 + (a1 - a0) * i / n)
            pts.extend([x, y])
        return pts

    def _band(self, r_out, r_in, a0, a1):
        return self._points(r_out, a0, a1) + self._points(r_in, a1, a0)

    # -- painting -----------------------------------------------------------
    def paint(self, frac, value_text, sub_text="", value_color=None):
        frac = clamp01(frac)
        c = self.canvas
        full = frac >= 0.997
        deg = 360.0 if full else 360.0 * frac
        if deg < 1.0:
            for it in (self.halo_out, self.halo_in, self.arc, self.edge):
                c.itemconfig(it, state="hidden")
        else:
            # halo rims: strictly outside the band, one pixel of air on both sides
            c.coords(self.halo_out,
                     *self._band(self.r_halo_out, self.r_out + 0.4, 0, deg))
            c.itemconfig(self.halo_out, state="normal")
            c.coords(self.halo_in,
                     *self._band(self.r_in - 0.4, self.r_halo_in, 0, deg))
            c.itemconfig(self.halo_in, state="normal")
            # the filled part of the ring, same thickness as the track
            c.coords(self.arc, *self._band(self.r_out, self.r_in, 0, deg))
            c.itemconfig(self.arc, state="normal")

            if full:
                c.itemconfig(self.edge, state="hidden")
            else:
                x1, y1 = polar(self.mid, self.mid, self.r_in, deg)
                x2, y2 = polar(self.mid, self.mid, self.r_out, deg)
                c.coords(self.edge, x1, y1, x2, y2)
                c.itemconfig(self.edge, state="normal")

        if self.ticks:
            lit = int(round(frac * self.n_ticks))
            for i, t in enumerate(self.ticks):
                active = i < lit
                c.itemconfig(t, fill=self.color if active else
                             (mix(TRACK, BG, 0.2) if i % self.major == 0 else FAINT))

        c.itemconfig(self.txt, text=value_text, fill=value_color or TEXT)
        if sub_text is not None:
            c.itemconfig(self.sub, text=sub_text)


# --------------------------------------------------------------------------- #
# widget
# --------------------------------------------------------------------------- #

class TokenPulse:
    def __init__(self, server=None):
        self.cfg = load_config()
        if server:
            self.cfg["server"] = server
        self.url = self.cfg["server"]

        self.root = tk.Tk()
        self.root.title("TokenPulse Monitor")
        self.root.configure(bg=BG)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", bool(self.cfg.get("topmost", True)))
        try:
            self.root.attributes("-alpha", 0.975)
        except Exception:
            pass

        self.collapsed = bool(self.cfg.get("collapsed", False))
        self.h = min(H, max(430, self.root.winfo_screenheight() - 40))
        self._drag = None
        self._tried_agent = False
        self._last_data_time = 0.0
        self._last_push = 0.0
        self._pulse = 0.0
        self._hot = 0.0

        self.disp = {"gpu": 0.0, "cpu": 0.0, "power": 0.0, "vram": 0.0,
                     "ram": 0.0, "goal": 0.0, "req": 0.0, "decode": 0.0}
        self.target = dict(self.disp)
        self.live_hist = []          # real decode tok/s, 0 while idle
        self.hist_seeded = False

        self.counters = {}
        for key in ("today_in", "today_out", "all_in", "all_out"):
            self.counters[key] = {"shown": 0.0, "from": 0.0, "t0": 0.0,
                                  "target": 0.0, "flash": 0.0, "text": None}
        self.last_counters = {}

        # sensor row state, painted from smoothed values
        self.svals = {"gpu": 0.0, "vram": 0.0, "cpu": 0.0, "ram": 0.0}
        self.stext = {"gpu": "—", "vram": "—", "cpu": "—", "ram": "—"}
        self.stemps = {"gpu": None, "vram": None, "cpu": None, "ram": None}
        self.slimits = {"gpu": 90.0, "vram": 95.0, "cpu": 95.0, "ram": 95.0}

        self.hero = {"decode": "—", "decode_sub": "", "prefill": "—",
                     "power": "—", "power_sub": "", "gpu_sub": "", "cpu_sub": ""}

        self.fetcher = Fetcher(self.url, self.cfg.get("interval", 1.0))
        self.fetcher.start()

        self._build_ui()
        self._place_window()
        self._apply_collapsed(self.collapsed, animate=False)
        self.root.bind("<Escape>", lambda e: self._apply_collapsed(True))
        self.root.bind("<Control-q>", lambda e: self.close())
        self.root.after(100, self._tick)

    # ------------------------------------------------------------------ UI --
    def _build_ui(self):
        self.border = tk.Frame(self.root, bg=STROKE)
        self.border.pack(fill="both", expand=True)
        self.inner = tk.Frame(self.border, bg=BG)
        self.inner.pack(fill="both", expand=True, padx=1, pady=1)

        # ---- title bar ----------------------------------------------------
        self.bar = tk.Frame(self.inner, bg=BG, height=34)
        self.bar.pack(fill="x", side="top")
        self.bar.pack_propagate(False)

        self.live = tk.Canvas(self.bar, width=16, height=16, bg=BG, highlightthickness=0)
        self.live.pack(side="left", padx=(10, 3))
        self.live_dot = self.live.create_oval(4, 4, 12, 12, fill=CYAN, outline="")

        self.t1 = tk.Label(self.bar, text="TOKEN", bg=BG, fg=TEXT, font=(FONT, 10, "bold"))
        self.t1.pack(side="left")
        self.t2 = tk.Label(self.bar, text="PULSE", bg=BG, fg=CYAN, font=(FONT, 10, "bold"))
        self.t2.pack(side="left", padx=(1, 8))
        self.subtitle = tk.Label(self.bar, text="STRATA · COMFYUI", bg=BG, fg=DIM,
                                 font=(FONT, 6, "bold"))
        self.subtitle.pack(side="left", pady=(2, 0))

        self.btn_close = tk.Label(self.bar, text="✕", bg=BG, fg=DIM, font=(FONT, 11),
                                  cursor="hand2", padx=6)
        self.btn_close.pack(side="right", padx=(0, 4))
        self.btn_collapse = tk.Label(self.bar, text="▾", bg=BG, fg=DIM, font=(FONT, 12),
                                     cursor="hand2", padx=6)
        self.btn_collapse.pack(side="right")
        self.btn_pin = tk.Label(self.bar, text="◉", bg=BG,
                                fg=CYAN if self.cfg.get("topmost") else DIM,
                                font=(FONT, 10), cursor="hand2", padx=5)
        self.btn_pin.pack(side="right")

        for w in (self.bar, self.t1, self.t2, self.subtitle, self.live):
            w.bind("<Button-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
            w.bind("<ButtonRelease-1>", self._drag_end)
            w.bind("<Double-Button-1>", lambda e: self.toggle_collapsed())
            w.bind("<Button-3>", self._popup_menu)

        self.btn_close.bind("<Button-1>", lambda e: self.close())
        self.btn_collapse.bind("<Button-1>", lambda e: self.toggle_collapsed())
        self.btn_pin.bind("<Button-1>", lambda e: self.toggle_topmost())
        for b, on in ((self.btn_close, RED), (self.btn_collapse, CYAN),
                      (self.btn_pin, CYAN)):
            b.bind("<Enter>", lambda e, w=b, c=on: w.config(fg=c))
            b.bind("<Leave>", lambda e, w=b: w.config(
                fg=DIM if w is not self.btn_pin else
                (CYAN if self.cfg.get("topmost") else DIM)))

        self.accent = tk.Canvas(self.inner, width=W, height=2, bg=BG,
                                highlightthickness=0)
        self.accent.pack(fill="x")

        # ---- collapsed strip: mini gauges + both token speeds -------------
        self.slim = tk.Frame(self.inner, bg=BG, height=COLLAPSED_H - 10)
        self.slim_live = tk.Canvas(self.slim, width=16, height=16, bg=BG,
                                   highlightthickness=0)
        self.slim_live.pack(side="left", padx=(8, 3))
        self.slim_dot = self.slim_live.create_oval(4, 4, 12, 12, fill=CYAN, outline="")

        self.slim_gpu = Gauge(self.slim, "ГПУ", CYAN, CYAN_DARK, size=SLIM_RING,
                              ticks=12, value_font=(MONO, 9, "bold"),
                              sub_font=None, caption_font=(FONT, 6, "bold"))
        self.slim_gpu.frame.pack(side="left", padx=(1, 0))
        self.slim_cpu = Gauge(self.slim, "ЦП", GREEN, GREEN_DARK, size=SLIM_RING,
                              ticks=12, value_font=(MONO, 9, "bold"),
                              sub_font=None, caption_font=(FONT, 6, "bold"))
        self.slim_cpu.frame.pack(side="left", padx=(0, 6))

        self.slim_decode = self._slim_metric("ДЕКОД ↑", CYAN)
        self.slim_prefill = self._slim_metric("PREFILL ↓", GREEN)

        self.slim_temps = tk.Label(self.slim, text="—", bg=BG, fg=DIM,
                                   font=(MONO, 6, "bold"), justify="left",
                                   anchor="w")
        self.slim_temps.pack(side="left", padx=(6, 0))

        self.slim_btn = tk.Label(self.slim, text="▴", bg=BG, fg=DIM, font=(FONT, 12),
                                 cursor="hand2", padx=10)
        self.slim_btn.pack(side="right")
        self.slim_btn.bind("<Button-1>", lambda e: self.toggle_collapsed())
        self.slim_btn.bind("<Enter>", lambda e: self.slim_btn.config(fg=CYAN))
        self.slim_btn.bind("<Leave>", lambda e: self.slim_btn.config(fg=DIM))
        for w in (self.slim, self.slim_temps, self.slim_decode[0],
                  self.slim_prefill[0], self.slim_gpu.canvas, self.slim_cpu.canvas):
            w.bind("<Double-Button-1>", lambda e: self.toggle_collapsed())
        for w in (self.slim, self.slim_temps, self.slim_decode[0],
                  self.slim_decode[1], self.slim_prefill[0], self.slim_prefill[1],
                  self.slim_gpu.frame, self.slim_cpu.frame):
            w.bind("<Button-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
            w.bind("<ButtonRelease-1>", self._drag_end)
            w.bind("<Button-3>", self._popup_menu)

        # ---- content ------------------------------------------------------
        self.content = tk.Frame(self.inner, bg=BG)
        self.content.pack(fill="both", expand=True)

        self._build_hero()
        self._build_progress()
        self._build_gauges()
        self._build_sensors()
        self._build_chart()
        self._build_tokens()
        self._build_goal()
        self._build_grid()
        self._build_recent()
        self._build_footer()

        self._menu = tk.Menu(self.root, tearoff=0, bg=PANEL2, fg=TEXT,
                             activebackground=CYAN_DARK, activeforeground=TEXT,
                             bd=0, font=(FONT, 9))
        self._menu.add_command(label="Настройки…", command=self.open_settings)
        self._menu.add_command(label="Свернуть / развернуть", command=self.toggle_collapsed)
        self._menu.add_checkbutton(
            label="Поверх всех окон",
            variable=tk.BooleanVar(value=bool(self.cfg.get("topmost", True))),
            command=self.toggle_topmost)
        self._menu.add_separator()
        self._menu.add_command(label="Выход", command=self.close)

    def _slim_metric(self, caption, color):
        f = tk.Frame(self.slim, bg=BG)
        f.pack(side="left", padx=(0, 8))
        tk.Label(f, text=caption, bg=BG, fg=DIM, font=(FONT, 5, "bold")).pack(anchor="w")
        val = tk.Label(f, text="—", bg=BG, fg=color, font=(MONO, 11, "bold"))
        val.pack(anchor="w")
        return f, val

    # -- hero: both token kinds -------------------------------------------
    def _build_hero(self):
        hero = tk.Frame(self.content, bg=BG)
        hero.pack(fill="x", padx=PAD, pady=(2, 0))
        hero.columnconfigure(0, weight=1)
        hero.columnconfigure(1, weight=1)

        left = tk.Frame(hero, bg=BG)
        left.grid(row=0, column=0, sticky="w")
        self.cap_decode = tk.Label(left, text="ДЕКОД · ВЫХОД", bg=BG, fg=DIM,
                                   font=(FONT, 6, "bold"))
        self.cap_decode.pack(anchor="w")
        row = tk.Frame(left, bg=BG)
        row.pack(anchor="w")
        self.lbl_decode = tk.Label(row, text="—", bg=BG, fg=CYAN,
                                   font=(MONO, 24, "bold"))
        self.lbl_decode.pack(side="left")
        tk.Label(row, text="ток/с", bg=BG, fg=DIM, font=(FONT, 8)).pack(
            side="left", padx=(5, 0), pady=(12, 0))

        right = tk.Frame(hero, bg=BG)
        right.grid(row=0, column=1, sticky="e")
        self.cap_prefill = tk.Label(right, text="PREFILL · ВХОД", bg=BG, fg=DIM,
                                    font=(FONT, 6, "bold"))
        self.cap_prefill.pack(anchor="e")
        row2 = tk.Frame(right, bg=BG)
        row2.pack(anchor="e")
        self.lbl_prefill = tk.Label(row2, text="—", bg=BG, fg=GREEN,
                                    font=(MONO, 24, "bold"))
        self.lbl_prefill.pack(side="right")
        tk.Label(row2, text="ток/с", bg=BG, fg=DIM, font=(FONT, 8)).pack(
            side="right", padx=(0, 5), pady=(12, 0))
        self.lbl_phase = tk.Label(right, text="IDLE", bg=PANEL2, fg=DIM,
                                  font=(FONT, 8, "bold"), padx=10, pady=4)
        self.lbl_phase.pack(side="right", anchor="e")

        self.lbl_model = tk.Label(self.content, text="нет модели", bg=BG, fg=DIM,
                                  font=(FONT, 7), anchor="w")
        self.lbl_model.pack(fill="x", padx=PAD, pady=(1, 0))

    def _build_progress(self):
        prog = tk.Frame(self.content, bg=BG)
        prog.pack(fill="x", padx=PAD, pady=(4, 0))
        self.lbl_prog = tk.Label(prog, text="ЗАПРОС —", bg=BG, fg=DIM,
                                 font=(FONT, 6, "bold"))
        self.lbl_prog.pack(side="left")
        self.lbl_prog_v = tk.Label(prog, text="", bg=BG, fg=DIM, font=(MONO, 6))
        self.lbl_prog_v.pack(side="right")
        self.progress = tk.Canvas(self.content, width=BAR_W, height=8, bg=BG,
                                  highlightthickness=0)
        self.progress.pack(padx=PAD, pady=(2, 0))
        self.progress.create_line(4, 4, BAR_W - 4, 4, width=4, fill=TRACK,
                                  capstyle=tk.ROUND)
        self.prog_fill = self.progress.create_line(4, 4, 5, 4, width=4, fill=CYAN,
                                                   capstyle=tk.ROUND)
        self.prog_glow = self.progress.create_oval(0, 0, 6, 6, fill=CYAN,
                                                   outline="", state="hidden")

    # -- three circular gauges --------------------------------------------
    def _build_gauges(self):
        head = tk.Frame(self.content, bg=BG)
        head.pack(fill="x", padx=PAD, pady=(5, 0))
        tk.Label(head, text="ЗАГРУЗКА · КРУГОВЫЕ ДАТЧИКИ", bg=BG, fg=DIM,
                 font=(FONT, 6, "bold")).pack(side="left")
        self.lbl_gauge_src = tk.Label(head, text="", bg=BG, fg=DIM, font=(FONT, 6))
        self.lbl_gauge_src.pack(side="right")

        row = tk.Frame(self.content, bg=BG)
        row.pack(fill="x", padx=PAD, pady=(2, 0))
        self.g_gpu = Gauge(row, "ВИДЕОКАРТА", CYAN, CYAN_DARK)
        self.g_cpu = Gauge(row, "ПРОЦЕССОР", GREEN, GREEN_DARK)
        self.g_power = Gauge(row, "МОЩНОСТЬ", VIOLET, VIOLET_DARK)
        self.g_gpu.frame.pack(side="left")
        self.g_cpu.frame.pack(side="left", padx=(1, 0))
        self.g_power.frame.pack(side="left", padx=(1, 0))

    # -- one sensor block, sorted by device -------------------------------
    def _build_sensors(self):
        head = tk.Frame(self.content, bg=BG)
        head.pack(fill="x", padx=PAD, pady=(4, 0))
        tk.Label(head, text="ДАТЧИКИ · ЗАГРУЗКА / ТЕМПЕРАТУРА", bg=BG, fg=DIM,
                 font=(FONT, 6, "bold")).pack(side="left")
        self.lbl_temp_src = tk.Label(head, text="", bg=BG, fg=DIM, font=(FONT, 6))
        self.lbl_temp_src.pack(side="right")

        self.sensors = {}
        for key, name, color in (("gpu", "ВИДЕОКАРТА", CYAN),
                                 ("vram", "ВИДЕОПАМЯТЬ", PINK),
                                 ("cpu", "ПРОЦЕССОР", GREEN),
                                 ("ram", "ОПЕРАТИВКА", AMBER)):
            self.sensors[key] = self._make_sensor_row(name, color)

    def _make_sensor_row(self, name, color):
        box = tk.Frame(self.content, bg=BG)
        box.pack(fill="x", padx=PAD, pady=(1, 0))
        tk.Label(box, text=name, bg=BG, fg=DIM, font=(FONT, 6, "bold"),
                 width=NAME_W, anchor="w").pack(side="left")

        c1 = tk.Canvas(box, width=LOAD_W, height=9, bg=BG, highlightthickness=0)
        c1.pack(side="left")
        c1.create_line(3, 4.5, LOAD_W - 3, 4.5, width=6, fill=TRACK)
        fill1 = c1.create_line(3, 4.5, 4, 4.5, width=6, fill=color)

        val1 = tk.Label(box, text="—", bg=BG, fg=TEXT, font=(MONO, 8, "bold"),
                        width=9, anchor="e")
        val1.pack(side="left", padx=(5, 0))

        c2 = tk.Canvas(box, width=THERM_W, height=9, bg=BG, highlightthickness=0)
        c2.pack(side="left", padx=(6, 0))
        segs = 12
        step = (THERM_W - 6) / segs
        for i in range(segs):
            x = 3 + i * step
            col = heat_gradient(i / float(segs - 1))
            c2.create_line(x, 4.5, x + step, 4.5, width=6, fill=mix(col, BG, 0.70))
        fill2 = c2.create_line(3, 4.5, 4, 4.5, width=6, fill=GREEN)
        tick = c2.create_line(3, 1, 3, 8, width=1, fill=WHITE)

        val2 = tk.Label(box, text="—", bg=BG, fg=DIM, font=(MONO, 8, "bold"),
                        width=6, anchor="e")
        val2.pack(side="left")
        return {"load_c": c1, "load_fill": fill1, "load_val": val1,
                "temp_c": c2, "temp_fill": fill2, "temp_tick": tick, "temp_val": val2,
                "color": color, "shown_t": None, "shown_l": None}

    # -- real throughput history ------------------------------------------
    def _build_chart(self):
        head = tk.Frame(self.content, bg=BG)
        head.pack(fill="x", padx=PAD, pady=(4, 0))
        tk.Label(head, text="ИСТОРИЯ СКОРОСТИ · РЕАЛЬНЫЕ ТОК/С · 48 С", bg=BG,
                 fg=DIM, font=(FONT, 6, "bold")).pack(side="left")
        self.lbl_reqs = tk.Label(head, text="", bg=BG, fg=DIM, font=(FONT, 6))
        self.lbl_reqs.pack(side="right")
        self.chart = tk.Canvas(self.content, width=CHART_W, height=CHART_H, bg=BG,
                               highlightthickness=0)
        self.chart.pack(padx=PAD, pady=(2, 0))

    # -- persistent token counters ----------------------------------------
    def _build_tokens(self):
        box = tk.Frame(self.content, bg=PANEL)
        box.pack(fill="x", padx=PAD, pady=(5, 0))
        inner = tk.Frame(box, bg=PANEL)
        inner.pack(fill="x", padx=10, pady=(6, 4))
        inner.columnconfigure(0, weight=1)
        inner.columnconfigure(1, weight=1)

        col1 = tk.Frame(inner, bg=PANEL)
        col1.grid(row=0, column=0, sticky="w")
        col1.columnconfigure(1, weight=1)
        tk.Label(col1, text="СЕГОДНЯ", bg=PANEL, fg=CYAN_SOFT,
                 font=(FONT, 6, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
        tk.Label(col1, text="ВХОД", bg=PANEL, fg=DIM,
                 font=(FONT, 6, "bold")).grid(row=1, column=0, sticky="w", pady=(3, 0))
        self.cnt_today_in = tk.Label(col1, text="0", bg=PANEL, fg=CYAN,
                                     font=(MONO, 15, "bold"))
        self.cnt_today_in.grid(row=1, column=1, sticky="e")
        tk.Label(col1, text="ВЫХОД", bg=PANEL, fg=DIM,
                 font=(FONT, 6, "bold")).grid(row=2, column=0, sticky="w")
        self.cnt_today_out = tk.Label(col1, text="0", bg=PANEL, fg=PINK,
                                      font=(MONO, 15, "bold"))
        self.cnt_today_out.grid(row=2, column=1, sticky="e")
        self.sub_today = tk.Label(col1, text="0 запросов · кэш 0", bg=PANEL, fg=DIM,
                                  font=(FONT, 6))
        self.sub_today.grid(row=3, column=0, columnspan=2, sticky="w", pady=(3, 0))

        tk.Frame(inner, bg=STROKE, width=1).grid(row=0, column=1, sticky="ns",
                                                 padx=(0, 10))

        col2 = tk.Frame(inner, bg=PANEL)
        col2.grid(row=0, column=2, sticky="e")
        col2.columnconfigure(1, weight=1)
        tk.Label(col2, text="ЗА ВСЁ ВРЕМЯ", bg=PANEL, fg=CYAN_SOFT,
                 font=(FONT, 6, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
        tk.Label(col2, text="ВХОД", bg=PANEL, fg=DIM,
                 font=(FONT, 6, "bold")).grid(row=1, column=0, sticky="w", pady=(3, 0))
        self.cnt_all_in = tk.Label(col2, text="0", bg=PANEL, fg=CYAN_SOFT,
                                   font=(MONO, 15, "bold"))
        self.cnt_all_in.grid(row=1, column=1, sticky="e")
        tk.Label(col2, text="ВЫХОД", bg=PANEL, fg=DIM,
                 font=(FONT, 6, "bold")).grid(row=2, column=0, sticky="w")
        self.cnt_all_out = tk.Label(col2, text="0", bg=PANEL, fg=PINK_SOFT,
                                    font=(MONO, 15, "bold"))
        self.cnt_all_out.grid(row=2, column=1, sticky="e")
        self.sub_all = tk.Label(col2, text="0 запросов · кэш 0", bg=PANEL, fg=DIM,
                                font=(FONT, 6))
        self.sub_all.grid(row=3, column=0, columnspan=2, sticky="w", pady=(3, 0))

        self.lbl_exact = tk.Label(box, text="точные значения: —", bg=PANEL, fg=DIM,
                                  font=(FONT, 6))
        self.lbl_exact.pack(fill="x", padx=10, pady=(0, 6))

    def _build_goal(self):
        head = tk.Frame(self.content, bg=BG)
        head.pack(fill="x", padx=PAD, pady=(4, 0))
        self.lbl_goal = tk.Label(head, text="ЦЕЛЬ ДНЯ · —", bg=BG, fg=DIM,
                                 font=(FONT, 6, "bold"))
        self.lbl_goal.pack(side="left")
        self.lbl_goal_pct = tk.Label(head, text="0%", bg=BG, fg=CYAN,
                                     font=(MONO, 6, "bold"))
        self.lbl_goal_pct.pack(side="right")
        self.goal_bar = tk.Canvas(self.content, width=BAR_W, height=8, bg=BG,
                                  highlightthickness=0)
        self.goal_bar.pack(padx=PAD, pady=(2, 0))
        self.goal_bar.create_line(4, 4, BAR_W - 4, 4, width=4, fill=TRACK,
                                  capstyle=tk.ROUND)
        self.goal_fill = self.goal_bar.create_line(4, 4, 5, 4, width=4, fill=VIOLET,
                                                   capstyle=tk.ROUND)

    def _build_grid(self):
        grid = tk.Frame(self.content, bg=BG)
        grid.pack(fill="x", padx=PAD, pady=(4, 0))
        for i in range(3):
            grid.columnconfigure(i, weight=1)
        self.m_ctx = self._metric(grid, 0, 0, "КОНТЕКСТ", "—", CYAN)
        self.m_kv = self._metric(grid, 0, 1, "ЯДРА · ПОТОКИ", "—", GREEN)
        self.m_queue = self._metric(grid, 0, 2, "ОЧЕРЕДЬ", "—", AMBER)
        self.m_req_today = self._metric(grid, 1, 0, "ЗАПРОСЫ · ДЕНЬ", "—", TEXT)
        self.m_req_all = self._metric(grid, 1, 1, "ЗАПРОСЫ · ВСЕГО", "—", VIOLET)
        self.m_cache = self._metric(grid, 1, 2, "КЭШ · ДЕНЬ", "—", PINK)

    def _build_recent(self):
        rbox = tk.Frame(self.content, bg=PANEL)
        rbox.pack(fill="x", padx=PAD, pady=(4, 0))
        tk.Label(rbox, text="ПОСЛЕДНИЕ ЗАПРОСЫ · ↓ВХОД ↑ВЫХОД · ДЕКОД/PREFILL",
                 bg=PANEL, fg=DIM, font=(FONT, 6, "bold")).pack(
            anchor="w", padx=8, pady=(5, 0))
        self.lbl_recent = tk.Label(rbox, text="—", bg=PANEL, fg=TEXT,
                                   font=(MONO, 7), justify="left", anchor="w")
        self.lbl_recent.pack(fill="x", padx=8, pady=(1, 5))

    def _build_footer(self):
        crow = tk.Frame(self.content, bg=BG)
        crow.pack(fill="x", padx=PAD, pady=(4, 0))
        self.chip_comfy = tk.Label(crow, text="ComfyUI · —", bg=PANEL2, fg=DIM,
                                   font=(FONT, 7, "bold"), padx=8, pady=3)
        self.chip_comfy.pack(side="left")
        self.lbl_comfy = tk.Label(crow, text="", bg=BG, fg=DIM, font=(FONT, 7))
        self.lbl_comfy.pack(side="right")

        foot = tk.Frame(self.content, bg=BG)
        foot.pack(fill="x", padx=PAD, pady=(5, 6))
        self.chip_strata = tk.Label(foot, text="Strata · —", bg=PANEL2, fg=DIM,
                                    font=(FONT, 7, "bold"), padx=8, pady=3)
        self.chip_strata.pack(side="left")
        self.status = tk.Label(foot, text="нет связи", bg=BG, fg=RED, font=(FONT, 7))
        self.status.pack(side="left", padx=(8, 0))
        self.lbl_lat = tk.Label(foot, text="— мс", bg=BG, fg=DIM, font=(FONT, 7))
        self.lbl_lat.pack(side="right")

    # -- small builders ----------------------------------------------------
    def _metric(self, parent, row, col, name, value, color):
        box = tk.Frame(parent, bg=BG)
        box.grid(row=row, column=col, sticky="w", padx=(0, 8), pady=(0, 3))
        tk.Label(box, text=name, bg=BG, fg=DIM, font=(FONT, 6, "bold")).pack(anchor="w")
        lbl = tk.Label(box, text=value, bg=BG, fg=color, font=(MONO, 10, "bold"))
        lbl.pack(anchor="w")
        return lbl

    # ------------------------------------------------------------- window --
    def _place_window(self):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = self.cfg.get("x")
        y = self.cfg.get("y")
        if x is None or y is None:
            x = sw - W - 24
            y = sh - self.h - 40
        x = max(0, min(int(x), sw - W))
        y = max(0, min(int(y), max(0, sh - self.h)))
        self.pos = [x, y]
        self._set_geometry()

    def _set_geometry(self, h=None):
        h = h if h is not None else (COLLAPSED_H if self.collapsed else self.h)
        self.root.geometry("%dx%d+%d+%d" % (W, int(h), self.pos[0], self.pos[1]))

    def _drag_start(self, e):
        self._drag = (e.x_root - self.pos[0], e.y_root - self.pos[1])

    def _drag_move(self, e):
        if not self._drag:
            return
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        h = COLLAPSED_H if self.collapsed else self.h
        x = max(0, min(e.x_root - self._drag[0], sw - W))
        y = max(0, min(e.y_root - self._drag[1], sh - h))
        self.pos = [x, y]
        self.root.geometry("%dx%d+%d+%d" % (W, h, x, y))

    def _drag_end(self, e):
        self._drag = None
        self.cfg["x"], self.cfg["y"] = self.pos
        save_config(self.cfg)

    def _popup_menu(self, e):
        try:
            self._menu.tk_popup(e.x_root, e.y_root)
        finally:
            self._menu.grab_release()

    def toggle_collapsed(self):
        self._apply_collapsed(not self.collapsed)

    def _apply_collapsed(self, value, animate=True):
        if value == self.collapsed and animate:
            return
        old_h = self.root.winfo_height()
        self.collapsed = value
        if value:
            self.content.pack_forget()
            self.slim.pack(fill="x", pady=(2, 6))
            self.btn_collapse.config(text="▴")
        else:
            self.slim.pack_forget()
            self.content.pack(fill="both", expand=True)
            self.btn_collapse.config(text="▾")
        new_h = COLLAPSED_H if value else self.h
        self.cfg["collapsed"] = value
        save_config(self.cfg)
        if not animate:
            self._set_geometry(new_h)
            return

        steps = [12, 10, 8, 6, 4, 3, 2, 1]

        def step(i):
            p = sum(steps[:i]) / float(sum(steps))
            h = old_h + (new_h - old_h) * ease_out(p)
            self._set_geometry(h)
            if i < len(steps):
                self.root.after(14, lambda: step(i + 1))
            else:
                self._set_geometry(new_h)

        step(1)

    def toggle_topmost(self):
        val = not bool(self.cfg.get("topmost", True))
        self.cfg["topmost"] = val
        self.root.attributes("-topmost", val)
        self.btn_pin.config(fg=CYAN if val else DIM)
        save_config(self.cfg)

    def close(self):
        self.cfg["x"], self.cfg["y"] = self.pos
        save_config(self.cfg)
        self.fetcher.stop()
        self.root.destroy()

    # ------------------------------------------------------------ settings --
    def open_settings(self):
        w = tk.Toplevel(self.root)
        w.title("TokenPulse — настройки")
        w.configure(bg=BG)
        w.geometry("400x230")
        w.attributes("-topmost", True)
        w.resizable(False, False)

        tk.Label(w, text="Адрес агента (сервер с видеокартой)", bg=BG, fg=TEXT,
                 font=(FONT, 9)).pack(anchor="w", padx=14, pady=(14, 4))
        entry = tk.Entry(w, bg=PANEL2, fg=TEXT, insertbackground=CYAN,
                         relief="flat", font=(MONO, 9))
        entry.insert(0, self.url)
        entry.pack(fill="x", padx=14, ipady=5)
        tk.Label(w, text="например: http://192.168.31.30:8787", bg=BG, fg=DIM,
                 font=(FONT, 7)).pack(anchor="w", padx=14, pady=(3, 8))

        tk.Label(w, text="Цель дня, токенов (вход + выход)", bg=BG, fg=TEXT,
                 font=(FONT, 9)).pack(anchor="w", padx=14, pady=(0, 4))
        goal = tk.Entry(w, bg=PANEL2, fg=TEXT, insertbackground=VIOLET,
                        relief="flat", font=(MONO, 9))
        goal.insert(0, str(int(self.cfg.get("daily_goal") or 1_000_000)))
        goal.pack(fill="x", padx=14, ipady=5)

        row = tk.Frame(w, bg=BG)
        row.pack(fill="x", padx=14, pady=12)
        ok = tk.Label(row, text="Сохранить", bg=CYAN_DARK, fg=TEXT,
                      font=(FONT, 9, "bold"), padx=12, pady=5, cursor="hand2")
        ok.pack(side="right")
        cancel = tk.Label(row, text="Отмена", bg=PANEL2, fg=DIM, font=(FONT, 9),
                          padx=12, pady=5, cursor="hand2")
        cancel.pack(side="right", padx=(0, 8))

        def save():
            url = entry.get().strip().rstrip("/")
            if not url.startswith(("http://", "https://")):
                url = "http://" + url
            try:
                g = max(1, int(float(goal.get().replace(" ", "").replace(",", ""))))
            except Exception:
                g = int(self.cfg.get("daily_goal") or 1_000_000)
            self.url = url
            self.cfg["server"] = url
            self.cfg["daily_goal"] = g
            save_config(self.cfg)
            self.fetcher.set_url(url)
            self._tried_agent = False
            w.destroy()

        ok.bind("<Button-1>", lambda e: save())
        cancel.bind("<Button-1>", lambda e: w.destroy())
        entry.bind("<Return>", lambda e: save())
        goal.bind("<Return>", lambda e: save())
        entry.focus_set()

    # --------------------------------------------------------------- agent --
    def _maybe_start_agent(self):
        if self._tried_agent:
            return
        self._tried_agent = True
        try:
            host = urlparse(self.url).hostname
        except Exception:
            return
        if host not in ("127.0.0.1", "localhost", "::1"):
            return
        agent = Path(__file__).with_name("agent.py")
        if not agent.exists():
            return
        try:
            kwargs = {}
            if WINDOWS:
                kwargs["creationflags"] = 0x08000000
            else:
                kwargs["start_new_session"] = True
            subprocess.Popen([sys.executable, str(agent)], cwd=str(agent.parent),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             **kwargs)
        except Exception:
            pass

    # ---------------------------------------------------------------- data --
    def _ingest(self, data):
        gpu = data.get("gpu") or {}
        cpu = data.get("cpu") or {}
        temps = data.get("temps") or {}
        st = data.get("strata") or {}
        cf = data.get("comfyui") or {}
        agent = data.get("agent") or {}
        tk_ = data.get("tokens") or {}
        today = tk_.get("today") or {}
        allt = tk_.get("all_time") or {}

        live_decode = float(st.get("tok_s") or 0)
        live_prefill = float(st.get("prefill_tok_s_mean") or 0)
        avg_decode = float(st.get("decode_tok_s_avg") or st.get("tok_s_mean") or 0)
        avg_prefill = float(st.get("prefill_tok_s_avg") or 0)
        last_prefill = float(st.get("prefill_tok_s_last") or 0)
        busy = live_decode > 0.5 or (st.get("phase") in ("prefill", "generate",
                                                        "generating", "decoding",
                                                        "thinking"))

        self.target["gpu"] = clamp(gpu.get("util") or 0)
        self.target["cpu"] = clamp(cpu.get("percent") or 0)
        self.target["decode"] = live_decode if live_decode > 0 else 0.0

        power = gpu.get("power_w")
        plim = gpu.get("power_limit_w") or 0
        if power is not None and plim:
            self.target["power"] = clamp(100.0 * float(power) / float(plim))
        else:
            self.target["power"] = 0.0

        mt = gpu.get("mem_total_gib") or 0
        mu = gpu.get("mem_used_gib") or 0
        self.target["vram"] = clamp(100.0 * mu / mt) if mt else 0.0
        rt = cpu.get("ram_total_gib") or 0
        ru = cpu.get("ram_used_gib") or 0
        self.target["ram"] = clamp(100.0 * ru / rt) if rt else 0.0

        # hero numbers: live speed when the engine works, run average otherwise
        decode = live_decode if live_decode > 0 else avg_decode
        prefill = live_prefill if live_prefill > 0 else (last_prefill if busy else avg_prefill)
        suffix = "ЖИВОЙ" if busy else "СРЕДНЕЕ"
        for lbl, cap in ((self.cap_decode, "ДЕКОД · ВЫХОД · " + suffix),
                         (self.cap_prefill, "PREFILL · ВХОД · " + suffix)):
            if lbl.cget("text") != cap:
                lbl.config(text=cap)
        self.lbl_decode.config(fg=CYAN if busy else CYAN_SOFT)
        self.lbl_prefill.config(fg=GREEN if busy else GREEN_SOFT)
        self.hero["decode"] = num(decode, 1)
        self.hero["prefill"] = grouped(round(prefill)) if prefill >= 1000 else num(prefill, 1)
        self.hero["power"] = num(power, 0) if power is not None else "—"
        self.hero["power_sub"] = ("из %d W" % round(plim)) if plim else ""
        self.hero["gpu_sub"] = ""
        self.hero["cpu_sub"] = ""

        phase = (st.get("phase") or st.get("state") or "idle") if st.get("up") else "offline"
        self.lbl_phase.config(
            text=phase.upper(),
            fg=GREEN if phase in ("generating", "thinking", "generate", "decoding")
            else (DIM if phase == "offline" else CYAN))
        self.lbl_model.config(text=short(st.get("model") or "нет модели", 34))

        # gauges
        self.hero["gpu_sub"] = ""

        # sensors: GPU -> VRAM -> CPU -> RAM
        t_gpu = temps.get("gpu")
        t_mem = temps.get("gpu_mem")
        t_cpu = temps.get("cpu")
        self.svals["gpu"] = clamp(gpu.get("util") or 0)
        self.stext["gpu"] = "%d%%" % round(self.svals["gpu"])
        self.stemps["gpu"] = t_gpu
        self.slimits["gpu"] = 90.0

        self.svals["vram"] = self.target["vram"]
        self.stext["vram"] = ("%.1f/%.0fG" % (mu, mt)) if mt else "—"
        self.stemps["vram"] = t_mem
        self.slimits["vram"] = 95.0

        self.svals["cpu"] = clamp(cpu.get("percent") or 0)
        self.stext["cpu"] = "%d%%" % round(self.svals["cpu"])
        self.stemps["cpu"] = t_cpu
        self.slimits["cpu"] = float(temps.get("cpu_limit") or 95.0)

        self.svals["ram"] = self.target["ram"]
        self.stext["ram"] = ("%.1f/%.0fG" % (ru, rt)) if rt else "—"
        self.stemps["ram"] = None

        src = []
        if temps.get("cpu_source"):
            src.append(str(temps.get("cpu_source")))
        if gpu.get("name"):
            src.append("nvidia-smi")
        self.lbl_temp_src.config(text=" · ".join(src) if src else "нет датчиков")
        self.lbl_gauge_src.config(text=short(gpu.get("name") or "GPU", 30))

        hot = []
        for v, lo, hi in ((t_cpu, 30, self.slimits["cpu"]),
                          (t_gpu, 25, 90), (t_mem, 25, 95)):
            if v is not None:
                hot.append(clamp01((float(v) - lo) / (hi - lo)))
        self._hot = max(hot) if hot else 0.0

        self.m_ctx.config(text=("%dK" % round((st.get("context") or 0) / 1024))
                          if st.get("context") else "—")
        self.m_kv.config(text="%s / %s" % (cpu.get("cores") or "?", cpu.get("threads") or "?"))
        self.m_queue.config(text=str(st.get("queued")) if st.get("queued") is not None
                            else "—")
        self.m_req_today.config(text=grouped(today.get("requests")))
        self.m_req_all.config(text=grouped(allt.get("requests")))
        self.m_cache.config(text=human_int(today.get("reused")))

        # per-request progress
        gen = st.get("generated")
        mx = st.get("max_tokens")
        if gen is not None and mx:
            self.target["req"] = clamp(100.0 * float(gen) / float(mx))
            self.lbl_prog.config(text="ЗАПРОС · ↑%s / %s · ↓%s" % (
                grouped(gen), grouped(mx), grouped(st.get("prompt_tokens"))))
            self.lbl_prog_v.config(text="%d%%" % self.target["req"])
        else:
            self.target["req"] = 0.0
            self.lbl_prog.config(text="ЗАПРОС · %s" % phase.upper())
            self.lbl_prog_v.config(text="")

        # persistent counters, rounded to millions
        self._set_counter("today_in", int(today.get("prompt") or 0))
        self._set_counter("today_out", int(today.get("output") or 0))
        self._set_counter("all_in", int(allt.get("prompt") or 0))
        self._set_counter("all_out", int(allt.get("output") or 0))
        self.sub_today.config(text="%s запросов · кэш %s" % (
            grouped(today.get("requests")), human_int(today.get("reused"))))
        self.sub_all.config(text="%s запросов · кэш %s" % (
            grouped(allt.get("requests")), human_int(allt.get("reused"))))
        exact = "точные значения · сегодня %s · всего %s токенов" % (
            grouped(today.get("total")), grouped(allt.get("total")))
        if self.lbl_exact.cget("text") != exact:
            self.lbl_exact.config(text=exact)

        goal = int(self.cfg.get("daily_goal") or 1_000_000)
        pct = 100.0 * float(today.get("total") or 0) / goal if goal else 0.0
        self.target["goal"] = clamp(pct)
        self.lbl_goal.config(text="ЦЕЛЬ ДНЯ · %s (↓%s ↑%s)" % (
            big_num(goal), big_num(today.get("prompt")), big_num(today.get("output"))))
        if pct > 999:
            self.lbl_goal_pct.config(text="×%.1f" % (pct / 100.0),
                                     fg=GREEN if pct >= 100 else CYAN)
        else:
            self.lbl_goal_pct.config(text="%.0f%%" % pct,
                                     fg=GREEN if pct >= 100 else CYAN)

        # recent requests: both token kinds, both speeds
        lines = []
        for r in (st.get("recent") or [])[:3]:
            t = time.strftime("%H:%M", time.localtime(r.get("t") or 0))
            lines.append("%s ↓%7s ↑%6s  %5s / %-5s" % (
                t, human_int(r.get("prompt")), human_int(r.get("out")),
                num(r.get("tok_s"), 1), num(r.get("prefill_tok_s"), 0)))
        text = "\n".join(lines) if lines else "—"
        if self.lbl_recent.cget("text") != text:
            self.lbl_recent.config(text=text)
        self.lbl_reqs.config(text="запросов в окне: %s" % human_int(st.get("total_requests"))
                             if st.get("up") else "")

        if st.get("up"):
            self.chip_strata.config(text="Strata · %s" % (st.get("version") or "on"),
                                    fg=GREEN if st.get("state") == "generating" else CYAN)
        else:
            self.chip_strata.config(text="Strata · off", fg=DIM)

        if cf.get("up"):
            running = cf.get("running") or 0
            pending = cf.get("pending") or 0
            self.chip_comfy.config(
                text="ComfyUI · %d▶ %d…" % (running, pending) if (running or pending)
                else "ComfyUI · ready", fg=PINK)
            vf_gib = cf.get("vram_free_gib")
            self.lbl_comfy.config(text=("свободно %.1f GB" % vf_gib)
                                  if vf_gib is not None else "")
        else:
            self.chip_comfy.config(text="ComfyUI · off", fg=DIM)
            self.lbl_comfy.config(text=short(cpu.get("name") or "", 34))

        up = agent.get("uptime_s") or cpu.get("uptime_s") or 0
        host = agent.get("hostname") or "server"
        txt = "%s · онлайн" % host
        if self.status.cget("text") != txt:
            self.status.config(text=txt, fg=GREEN)
        lat = "аптайм %s" % self._fmt_uptime(up)
        if self.lbl_lat.cget("text") != lat:
            self.lbl_lat.config(text=lat)

        # real throughput samples (0 while the engine is idle)
        if not self.hist_seeded:
            hist = (st.get("history") or {}).get("tok_s") or []
            if hist:
                self.live_hist = [max(0.0, float(x)) for x in hist[-CHART_SLOTS:]]
                self.hist_seeded = True
        now = float(data.get("time") or time.time())
        if now - self._last_push >= 0.9:
            self._last_push = now
            self.live_hist.append(max(0.0, live_decode))
            self.live_hist = self.live_hist[-CHART_SLOTS:]
            self._draw_chart()

        self._last_data_time = time.time()

    def _set_counter(self, key, value):
        c = self.counters[key]
        prev = self.last_counters.get(key, value)
        if value != c["target"]:
            c["from"] = c["shown"]
            c["t0"] = time.time()
            c["target"] = float(value)
            if value > prev:
                c["flash"] = time.time()
        self.last_counters[key] = value

    @staticmethod
    def _fmt_uptime(sec):
        try:
            sec = int(sec or 0)
        except Exception:
            return "—"
        d, rem = divmod(sec, 86400)
        h, rem = divmod(rem, 3600)
        m = rem // 60
        if d:
            return "%dд %dч" % (d, h)
        if h:
            return "%dч %dм" % (h, m)
        return "%dм" % m

    # -------------------------------------------------------------- drawing --
    def _draw_chart(self):
        c = self.chart
        c.delete("all")
        w, h = CHART_W, CHART_H
        base = h - 10
        c.create_line(2, base, w - 2, base, fill=TRACK, width=1)
        for k in (1, 2, 3):
            x = 2 + (w - 4) * k / 4.0
            c.create_line(x, 6, x, base, fill=FAINT, width=1)
        c.create_text(4, h - 4, anchor="w", text="−48 с", fill=DIM, font=(FONT, 6))
        c.create_text(w / 2, h - 4, anchor="center", text="−24 с", fill=DIM,
                      font=(FONT, 6))
        c.create_text(w - 4, h - 4, anchor="e", text="сейчас", fill=DIM, font=(FONT, 6))

        data = self.live_hist[-CHART_SLOTS:]
        if not data:
            return
        peak = max(data)
        if peak <= 0.5:
            c.create_text(w / 2, h / 2 - 6, text="ДВИЖОК ПРОСТОИВАЕТ · 0 ТОК/С",
                          fill=DIM, font=(FONT, 6, "bold"))
            return

        slot = (w - 4) / float(CHART_SLOTS)
        tops = []
        for i, v in enumerate(data):
            x0 = 2 + i * slot
            bw = max(1.0, slot - 1.6)
            hh = (v / peak) * (base - 8)
            col = mix(CYAN, VIOLET, clamp01(v / peak))
            if hh < 1.0:
                c.create_line(x0, base - 1, x0 + bw, base - 1, width=1, fill=FAINT)
                tops.append((x0 + bw / 2, base - 1))
                continue
            c.create_rectangle(x0, base - hh, x0 + bw, base,
                               fill=mix(col, BG, 0.62), outline="")
            c.create_line(x0, base - hh, x0 + bw, base - hh, width=2, fill=col)
            tops.append((x0 + bw / 2, base - hh))

        pts = []
        for x, y in tops:
            pts.extend([x, y])
        if len(pts) >= 4:
            c.create_line(*pts, fill=mix(CYAN, BG, 0.35), width=1, smooth=True)
        c.create_text(4, 5, anchor="w", text="пик %s ток/с" % num(peak, 1),
                      fill=CYAN_SOFT, font=(MONO, 6, "bold"))

    def _draw_accent(self):
        c = self.accent
        c.delete("all")
        n = 46
        seg = W / n
        shift = (self._pulse * 0.35) % 1.0
        hot = self._hot
        for i in range(n):
            t = (i / n + shift) % 1.0
            if t < 0.4:
                col = mix(CYAN, VIOLET, t / 0.4)
            elif t < 0.7:
                col = mix(VIOLET, PINK, (t - 0.4) / 0.3)
            else:
                col = mix(PINK, CYAN, (t - 0.7) / 0.3)
            if hot > 0.6:
                col = mix(col, RED, (hot - 0.6) / 0.4 * 0.7)
            c.create_line(i * seg, 1, (i + 1) * seg, 1, fill=col)

    def _paint_sensors(self):
        for key in ("gpu", "vram", "cpu", "ram"):
            r = self.sensors[key]
            pct = clamp(self.svals[key])
            w = LOAD_W
            x2 = 3 + (w - 6) * (pct / 100.0)
            if x2 <= 4:
                x2 = 4.0
            hot_col = mix(r["color"], RED, 0.75) if pct > 92 else r["color"]
            r["load_c"].coords(r["load_fill"], 3, 4.5, x2, 4.5)
            r["load_c"].itemconfig(r["load_fill"], fill=hot_col)
            if r["shown_l"] != self.stext[key]:
                r["shown_l"] = self.stext[key]
                r["load_val"].config(text=self.stext[key], fg=TEXT)

            temp = self.stemps[key]
            if temp is None:
                r["temp_c"].coords(r["temp_fill"], 3, 4.5, 4, 4.5)
                r["temp_c"].itemconfig(r["temp_tick"], fill=FAINT)
                if r["shown_t"] != "—":
                    r["shown_t"] = "—"
                    r["temp_val"].config(text="—", fg=DIM)
                continue
            lo, hi = 25.0, self.slimits[key]
            frac = clamp01((float(temp) - lo) / max(1.0, hi - lo))
            col = heat_gradient(frac)
            x = 3 + (THERM_W - 6) * frac
            r["temp_c"].coords(r["temp_fill"], 3, 4.5, max(4.0, x), 4.5)
            r["temp_c"].itemconfig(r["temp_fill"], fill=col)
            r["temp_c"].coords(r["temp_tick"], x - 1, 1, x + 1, 8)
            r["temp_c"].itemconfig(r["temp_tick"], fill=WHITE)
            txt = "%d°C" % round(temp)
            if r["shown_t"] != txt:
                r["shown_t"] = txt
                r["temp_val"].config(text=txt, fg=col)
            else:
                r["temp_val"].config(fg=col)

    def _animate_counters(self):
        now = time.time()
        pairs = (("today_in", self.cnt_today_in, CYAN),
                 ("today_out", self.cnt_today_out, PINK),
                 ("all_in", self.cnt_all_in, CYAN_SOFT),
                 ("all_out", self.cnt_all_out, PINK_SOFT))
        for key, lbl, base in pairs:
            c = self.counters[key]
            if c["t0"] and c["shown"] != c["target"]:
                p = min(1.0, (now - c["t0"]) / 0.7)
                c["shown"] = c["from"] + (c["target"] - c["from"]) * ease_out(p)
                if p >= 1.0:
                    c["shown"] = c["target"]
            txt = big_num(c["shown"])
            if c["text"] != txt:
                c["text"] = txt
                lbl.config(text=txt)
            if c["flash"] and now - c["flash"] < 0.9:
                k = 1.0 - (now - c["flash"]) / 0.9
                lbl.config(fg=mix(base, WHITE, k))
            else:
                lbl.config(fg=base)

    # ---------------------------------------------------------------- tick --
    def _tick(self):
        now = time.time()
        data = self.fetcher.data
        if data and data.get("time", 0) > self._last_data_time - 0.001:
            self._ingest(data)

        online = (now - self._last_data_time) < 5.0
        if not online:
            if self.status.cget("text") != "нет связи":
                self.status.config(text="нет связи", fg=RED)
            if self.fetcher.error and now - self.fetcher.ok_at > 2.5:
                self._maybe_start_agent()

        for k in self.disp:
            self.disp[k] += (self.target[k] - self.disp[k]) * 0.16

        self._pulse += 0.045
        glow = 0.5 + 0.5 * math.sin(self._pulse)
        dot = mix(CYAN, "#0d2634", glow) if online else RED
        self.live.itemconfig(self.live_dot, fill=dot)
        self.slim_live.itemconfig(self.slim_dot, fill=dot)

        base = mix(STROKE, CYAN_DARK, 0.25 + 0.35 * glow)
        if self._hot > 0.55:
            base = mix(base, "#6b1c26", (self._hot - 0.55) / 0.45 * 0.8)
        self.border.config(bg=base)

        # circular gauges
        self.g_gpu.paint(self.disp["gpu"] / 100.0, "%d%%" % round(self.disp["gpu"]),
                         "загрузка", self._ring_color(self.disp["gpu"], CYAN))
        self.g_cpu.paint(self.disp["cpu"] / 100.0, "%d%%" % round(self.disp["cpu"]),
                         "загрузка", self._ring_color(self.disp["cpu"], GREEN))
        pw = self.hero["power"]
        self.g_power.paint(self.disp["power"] / 100.0, pw,
                           self.hero["power_sub"] or "мощность",
                           self._ring_color(self.disp["power"], VIOLET))

        self._paint_sensors()
        self._paint_bar_simple(self.progress, self.prog_fill, self.disp["req"], 4, BAR_W)
        self._paint_progress_glow(self.disp["req"])
        self._paint_bar_simple(self.goal_bar, self.goal_fill, self.disp["goal"], 4, BAR_W)

        d = self.hero["decode"]
        if getattr(self, "_shown_decode", None) != d:
            self._shown_decode = d
            self.lbl_decode.config(text=d)
        p = self.hero["prefill"]
        if getattr(self, "_shown_prefill", None) != p:
            self._shown_prefill = p
            self.lbl_prefill.config(text=p)

        self._draw_accent()
        self._animate_counters()

        if self.collapsed:
            d = self.fetcher.data or {}
            t = d.get("temps") or {}
            tk_ = (d.get("tokens") or {}).get("today") or {}
            self.slim_gpu.paint(self.disp["gpu"] / 100.0, "%d%%" % round(self.disp["gpu"]),
                                None, self._ring_color(self.disp["gpu"], CYAN))
            self.slim_cpu.paint(self.disp["cpu"] / 100.0, "%d%%" % round(self.disp["cpu"]),
                                None, self._ring_color(self.disp["cpu"], GREEN))
            self.slim_decode[1].config(text=self.hero["decode"])
            self.slim_prefill[1].config(text=self.hero["prefill"])
            temps1 = []
            if t.get("gpu") is not None:
                temps1.append("ВК %.0f°" % float(t["gpu"]))
            if t.get("gpu_mem") is not None:
                temps1.append("ВП %.0f°" % float(t["gpu_mem"]))
            temps2 = []
            if t.get("cpu") is not None:
                temps2.append("ЦП %.0f°" % float(t["cpu"]))
            temps2.append(big_num(tk_.get("total")))
            txt = "\n".join(x for x in (" · ".join(temps1), " · ".join(temps2)) if x)
            if self.slim_temps.cget("text") != txt:
                self.slim_temps.config(text=txt)

        self.root.after(40, self._tick)

    @staticmethod
    def _ring_color(pct, color):
        if pct > 92:
            return mix(color, RED, 0.6)
        if pct > 75:
            return mix(color, AMBER, 0.35)
        return color

    def _paint_bar_simple(self, canvas, item, pct, inset, width):
        pct = max(0.0, min(100.0, pct))
        h = canvas.winfo_height() or 8
        y = h / 2.0
        x2 = inset + (width - 2 * inset) * (pct / 100.0)
        if x2 <= inset + 1:
            x2 = inset + 1.0
        canvas.coords(item, inset, y, x2, y)

    def _paint_progress_glow(self, pct):
        pct = max(0.0, min(100.0, pct))
        y = 4
        x2 = 4 + (BAR_W - 8) * (pct / 100.0)
        if pct > 0.5:
            self.progress.coords(self.prog_glow, x2 - 3, y - 3, x2 + 3, y + 3)
            self.progress.itemconfig(self.prog_glow, state="normal")
        else:
            self.progress.itemconfig(self.prog_glow, state="hidden")

    def run(self):
        self.root.mainloop()


def main():
    ap = argparse.ArgumentParser(description="TokenPulse — Strata / ComfyUI widget")
    ap.add_argument("--server", help="agent URL, e.g. http://192.168.31.30:8787")
    args = ap.parse_args()
    TokenPulse(args.server).run()


if __name__ == "__main__":
    main()
