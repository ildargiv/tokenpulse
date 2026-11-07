#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Strata / llama.cpp / LM Studio / Ollama / vLLM + ComfyUI monitor agent.

Runs on the GPU server, collects:
  * CPU load / RAM / swap
  * GPU load / VRAM / temperature / power  (nvidia-smi)
  * the inference engine: Strata /metrics, llama.cpp, vLLM, LM Studio, Ollama or any
    OpenAI-compatible server (found automatically on the usual local ports, see engines.py)
  * ComfyUI /system_stats + /queue

Exposes a JSON API (CORS *, no auth by default; set TP_TOKEN to require a token):
  GET /api/stats    -> snapshot
  GET /api/health   -> {"ok": true}
  GET /             -> dashboard (web/index.html)

Works on Linux and Windows, Python 3.8+, standard library only.
"""

import argparse
import glob
import hmac
import json
import math
import os
import platform
import shutil
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

import engines

VERSION = "1.2.0"
WINDOWS = os.name == "nt"
HERE = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(HERE, "web")

if WINDOWS:
    import ctypes
    from ctypes import wintypes


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def http_json(url, timeout=1.5):
    try:
        req = Request(url, headers={"User-Agent": "strata-monitor/%s" % VERSION})
        with urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None


def run_cmd(cmd, timeout=5):
    try:
        flags = 0
        if WINDOWS:
            flags = 0x08000000  # CREATE_NO_WINDOW
        p = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=timeout, creationflags=flags,
        )
        return p.stdout.decode("utf-8", "replace")
    except Exception:
        return ""


def as_float(v, default=None):
    try:
        s = str(v).strip().lower()
        if s in ("[n/a]", "n/a", "none", ""):
            return default
        return float(s)
    except Exception:
        return default


def gib(n_bytes):
    try:
        return round(float(n_bytes) / (1024.0 ** 3), 2)
    except Exception:
        return None


def _speed(tokens, ms):
    """tokens per second from a millisecond duration."""
    try:
        ms = float(ms)
        tokens = float(tokens)
        if ms <= 0 or tokens <= 0:
            return None
        return round(tokens / (ms / 1000.0), 1)
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# CPU temperature collector
#   Linux   : /sys/class/hwmon  (k10temp / coretemp / zenpower / cpu_thermal)
#   Windows : WMI MSAcpi_ThermalZoneTemperature, optional LibreHardwareMonitor
#             (set TP_LHM_URL=http://127.0.0.1:8085 to use it)
# --------------------------------------------------------------------------- #

CPU_HWMON_RANK = {
    "k10temp": 0, "zenpower": 0, "coretemp": 1, "cpu_thermal": 2,
    "cpu-thermal": 2, "soc_thermal": 2, "chiptemp": 2, "acpitz": 3,
    "amdgpu": 7, "i915": 7, "radeon": 7,
}
CPU_TEMP_LABELS = ("tctl", "tdie", "package", "tdie1", "core 0", "cpu", "tcore")
BAD_TEMP_LABELS = ("composite", "sensor 1", "sensor 2", "phy", "gpu", "edge",
                   "mem", "hbm", "video")


def _read_text(path):
    try:
        with open(path, "r") as f:
            return f.read().strip()
    except Exception:
        return None


def _read_int(path):
    try:
        return int(open(path, "r").read().strip())
    except Exception:
        return None


class CpuTempCollector:
    def __init__(self):
        self._devices = []
        self._scanned = 0.0
        self._zone = None
        self._cache = None
        self._win_next = 0.0
        self._win_cmd = None
        self.lhm_url = (os.environ.get("TP_LHM_URL") or "").strip()

    # -- sample -------------------------------------------------------------
    def sample(self):
        try:
            if WINDOWS:
                return self._sample_windows()
            return self._sample_linux()
        except Exception:
            return {"temp_c": None, "temp_source": None}

    # -- linux --------------------------------------------------------------
    def _rescan(self):
        now = time.time()
        if self._devices and now - self._scanned < 120:
            return
        self._scanned = now
        found = []
        try:
            names = sorted(os.listdir("/sys/class/hwmon"))
        except Exception:
            names = []
        for n in names:
            d = "/sys/class/hwmon/" + n
            chip = _read_text(d + "/name") or ""
            rank = CPU_HWMON_RANK.get(chip, 9)
            if rank >= 9:
                continue
            found.append((rank, chip, d))
        found.sort()
        self._devices = found

    def _sample_linux(self):
        self._rescan()
        out = {"temp_c": None, "temp_max_c": None, "temp_limit_c": None,
               "temp_cores": [], "temp_source": None, "temp_sensors": []}

        all_sensors = []
        for rank, chip, d in self._devices:
            vals = []
            for f in sorted(glob.glob(d + "/temp*_input")):
                raw = _read_int(f)
                if raw is None:
                    continue
                v = raw / 1000.0
                if v < -40 or v > 165:
                    continue
                stem = f[:-6]
                label = _read_text(stem + "_label") or os.path.basename(stem)
                lim = _read_int(stem + "_max")
                all_sensors.append({
                    "chip": chip, "label": label, "temp_c": round(v, 1),
                    "limit_c": round(lim / 1000.0, 1) if lim else None,
                })
                vals.append((label.lower(), v, lim))
            if not vals:
                continue
            primary = None
            for label, v, _lim in vals:
                if any(k in label for k in CPU_TEMP_LABELS) and \
                        not any(k in label for k in BAD_TEMP_LABELS):
                    primary = v
                    break
            core_vals = [v for _l, v, _x in vals]
            limits = [x for _l, _v, x in vals if x]
            out["temp_c"] = round(primary if primary is not None else max(core_vals), 1)
            out["temp_max_c"] = round(max(core_vals), 1)
            out["temp_cores"] = [round(v, 1) for v in core_vals]
            out["temp_limit_c"] = round(max(limits) / 1000.0, 1) if limits else None
            out["temp_source"] = chip
            break

        out["temp_sensors"] = all_sensors

        if out["temp_c"] is None:
            out.update(self._linux_zone())
        return out

    def _linux_zone(self):
        best = None
        for d in sorted(glob.glob("/sys/class/thermal/thermal_zone*")):
            ztype = (_read_text(d + "/type") or "").lower()
            raw = _read_int(d + "/temp")
            if raw is None:
                continue
            v = raw / 1000.0
            if v < -40 or v > 165:
                continue
            score = 0 if any(k in ztype for k in ("pkg", "cpu", "x86", "acpitz")) else 5
            if "iwl" in ztype or "gpu" in ztype:
                score = 9
            if best is None or score < best[0]:
                best = (score, ztype or "thermal zone", round(v, 1))
        if best and best[0] < 9:
            return {"temp_c": best[2], "temp_max_c": best[2], "temp_limit_c": None,
                    "temp_cores": [], "temp_source": "thermal zone · " + best[1],
                    "temp_sensors": []}
        return {}

    # -- windows ------------------------------------------------------------
    def _sample_windows(self):
        now = time.time()
        if self._cache is not None and now < self._win_next:
            return self._cache
        self._win_next = now + 5.0

        out = {"temp_c": None, "temp_max_c": None, "temp_limit_c": None,
               "temp_cores": [], "temp_source": None, "temp_sensors": []}

        # 1. LibreHardwareMonitor HTTP interface (best numbers on Windows)
        if self.lhm_url:
            out.update(self._from_lhm())
            if out["temp_c"] is not None:
                self._cache = out
                return out

        # 2. WMI ACPI thermal zone
        cmds = [
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance -Namespace root/cimv2 -ClassName "
             "MSAcpi_ThermalZoneTemperature | ForEach-Object { $_.CurrentReading }"],
            ["wmic", "/namespace:\\\\root\\\\cimv2", "path",
             "MSAcpi_ThermalZoneTemperature", "get", "CurrentReading"],
        ]
        if self._win_cmd is not None:
            cmds = [cmds[self._win_cmd]] + cmds[: self._win_cmd] + cmds[self._win_cmd + 1:]
        for i, cmd in enumerate(cmds):
            raw = run_cmd(cmd, timeout=6)
            temps = []
            for tok in raw.replace("\r", " ").split():
                v = as_float(tok)
                if v is None:
                    continue
                c = v / 10.0 - 273.15 if v > 1000 else v
                if 0 <= c <= 150:
                    temps.append(round(c, 1))
            if temps:
                self._win_cmd = i
                out["temp_c"] = max(temps)
                out["temp_max_c"] = max(temps)
                out["temp_cores"] = temps
                out["temp_source"] = ("WMI · ACPI thermal zone" if i == 0
                                      else "WMI · MSAcpi_ThermalZoneTemperature")
                break

        if out["temp_c"] is None:
            out["temp_hint"] = ("Датчик температуры CPU недоступен. Установите "
                                "LibreHardwareMonitor и задайте TP_LHM_URL.")
        self._cache = out
        return out

    def _from_lhm(self):
        try:
            j = http_json(self.lhm_url.rstrip("/") + "/data.json", 1.2)
        except Exception:
            return {}
        if not isinstance(j, dict):
            return {}
        vals = {}

        def walk(node, ancestry):
            if not isinstance(node, dict):
                return
            name = str(node.get("Text") or node.get("Name") or "")
            path = ancestry + [name]
            if str(node.get("SensorType") or "") == "Temperature":
                v = as_float(node.get("Value"))
                if v is not None and 0 <= v <= 160:
                    tag = " ".join(path).lower()
                    if "cpu" in tag or "package" in tag or "core" in tag:
                        vals.setdefault("cpu", []).append(round(v, 1))
                    if "gpu" in tag and ("memory" in tag or "vram" in tag):
                        vals.setdefault("gpu_mem", []).append(round(v, 1))
            for child in node.get("Children") or []:
                walk(child, path)

        walk(j, [])
        out = {}
        if vals.get("cpu"):
            out["temp_c"] = max(vals["cpu"])
            out["temp_max_c"] = max(vals["cpu"])
            out["temp_cores"] = vals["cpu"]
            out["temp_source"] = "LibreHardwareMonitor"
        if vals.get("gpu_mem"):
            out["temp_mem_c"] = max(vals["gpu_mem"])
        return out


# --------------------------------------------------------------------------- #
# system collector (CPU / RAM / swap / uptime)
# --------------------------------------------------------------------------- #

def _linux_cpu_times():
    with open("/proc/stat", "r") as f:
        parts = f.readline().split()
    nums = [int(x) for x in parts[1:]]
    idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
    return idle, sum(nums)


def _linux_meminfo():
    info = {}
    with open("/proc/meminfo", "r") as f:
        for line in f:
            k, v = line.split(":", 1)
            info[k.strip()] = int(v.split()[0]) * 1024
    return info


class SystemCollector:
    def __init__(self):
        self.psutil = None
        try:
            import psutil
            self.psutil = psutil
            try:
                psutil.cpu_percent(None)
            except Exception:
                pass
        except Exception:
            self.psutil = None

        self._prev = None          # linux counters
        self._prev_win = None      # windows counters
        self.cores = os.cpu_count() or 1
        self.cpu_name = self._cpu_name()
        self.threads = self._threads()
        self.physical_cores = self._physical_cores()
        self.cpu_temp = CpuTempCollector()

    # -- static -------------------------------------------------------------
    def _cpu_name(self):
        if WINDOWS:
            try:
                import winreg
                key = winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
                )
                val, _ = winreg.QueryValueEx(key, "ProcessorNameString")
                return str(val).strip()
            except Exception:
                return platform.processor() or "CPU"
        try:
            with open("/proc/cpuinfo", "r") as f:
                for line in f:
                    if line.lower().startswith("model name"):
                        return line.split(":", 1)[1].strip()
        except Exception:
            pass
        return platform.processor() or "CPU"

    def _threads(self):
        if self.psutil:
            try:
                return self.psutil.cpu_count(logical=True) or self.cores
            except Exception:
                pass
        return self.cores

    def _physical_cores(self):
        if WINDOWS:
            return self.cores
        seen = set()
        try:
            with open("/proc/cpuinfo", "r") as f:
                pid = cid = None
                for line in f:
                    if line.startswith("processor"):
                        pid = cid = None
                    elif line.startswith("physical id"):
                        pid = line.split(":", 1)[1].strip()
                    elif line.startswith("core id"):
                        cid = line.split(":", 1)[1].strip()
                        if pid is not None:
                            seen.add((pid, cid))
        except Exception:
            return self.cores
        return len(seen) or self.cores

    # -- sample -------------------------------------------------------------
    def sample(self):
        used = swap_used = total = swap_total = None
        pct = 0.0
        pi = 0.0
        swap_pct = None

        if self.psutil:
            try:
                pct = float(self.psutil.cpu_percent(None))
                vm = self.psutil.virtual_memory()
                sm = self.psutil.swap_memory()
                total, used = vm.total, vm.total - vm.available
                swap_total, swap_used = sm.total, sm.used
                pi = 100.0 * used / total if total else 0.0
                swap_pct = 100.0 * swap_used / swap_total if swap_total else 0.0
            except Exception:
                self.psutil = None

        if self.psutil is None and WINDOWS:
            pct, total, used, swap_total, swap_used = self._sample_windows()
            pi = 100.0 * used / total if total else 0.0
            swap_pct = 100.0 * swap_used / swap_total if swap_total else 0.0

        if self.psutil is None and not WINDOWS:
            pct = self._cpu_linux()
            try:
                mi = _linux_meminfo()
                total = mi.get("MemTotal")
                avail = mi.get("MemAvailable", mi.get("MemFree", 0))
                used = (total - avail) if total else None
                swap_total = mi.get("SwapTotal")
                swap_used = (swap_total - mi.get("SwapFree", 0)) if swap_total else None
                pi = 100.0 * used / total if total else 0.0
                swap_pct = 100.0 * swap_used / swap_total if swap_total else 0.0
            except Exception:
                pass

        ct = self.cpu_temp.sample() or {}
        return {
            "percent": round(pct, 1),
            "name": self.cpu_name,
            "cores": self.physical_cores,
            "threads": self.threads,
            "temp_c": ct.get("temp_c"),
            "temp_max_c": ct.get("temp_max_c"),
            "temp_limit_c": ct.get("temp_limit_c"),
            "temp_cores": ct.get("temp_cores") or [],
            "temp_source": ct.get("temp_source"),
            "temp_sensors": ct.get("temp_sensors") or [],
            "temp_hint": ct.get("temp_hint"),
            "ram_percent": round(pi, 1),
            "ram_used_gib": gib(used),
            "ram_total_gib": gib(total),
            "swap_percent": round(swap_pct, 1) if swap_pct is not None else None,
            "swap_used_gib": gib(swap_used),
            "swap_total_gib": gib(swap_total),
            "uptime_s": self._uptime(),
        }

    def _cpu_linux(self):
        try:
            idle, total = _linux_cpu_times()
        except Exception:
            return 0.0
        if self._prev is None:
            self._prev = (idle, total)
            return 0.0
        di = idle - self._prev[0]
        dt = total - self._prev[1]
        self._prev = (idle, total)
        return 100.0 * (dt - di) / dt if dt > 0 else 0.0

    def _sample_windows(self):
        kernel32 = ctypes.windll.kernel32

        class FILETIME(ctypes.Structure):
            _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", wintypes.DWORD),
                ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        idle, kern, user = FILETIME(), FILETIME(), FILETIME()
        kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user))

        def val(ft):
            return (ft.hi << 32) | ft.lo

        cur = (val(idle), val(kern), val(user))
        pct = 0.0
        if self._prev_win is not None:
            di = cur[0] - self._prev_win[0]
            dt = (cur[1] - self._prev_win[1]) + (cur[2] - self._prev_win[2])
            if dt > 0:
                pct = 100.0 * (dt - di) / dt
        self._prev_win = cur

        ms = MEMORYSTATUSEX()
        ms.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
        total = int(ms.ullTotalPhys)
        used = total - int(ms.ullAvailPhys)
        swap_total = int(ms.ullTotalPageFile)
        swap_used = swap_total - int(ms.ullAvailPageFile)
        return pct, total, used, swap_total, swap_used

    def _uptime(self):
        if WINDOWS:
            try:
                return int(ctypes.windll.kernel32.GetTickCount64() / 1000)
            except Exception:
                return None
        try:
            with open("/proc/uptime", "r") as f:
                return int(float(f.read().split()[0]))
        except Exception:
            return None


# --------------------------------------------------------------------------- #
# GPU collector (nvidia-smi)
# --------------------------------------------------------------------------- #

class GpuCollector:
    # richest query first; falls back automatically when a field is unsupported
    QUERIES = [
        "name,utilization.gpu,memory.used,memory.total,temperature.gpu,"
        "temperature.memory,power.draw,power.limit,fan.speed",
        "name,utilization.gpu,memory.used,memory.total,temperature.gpu,"
        "power.draw,power.limit,fan.speed",
        "name,utilization.gpu,memory.used,memory.total,temperature.gpu,"
        "power.draw,power.limit",
    ]

    def __init__(self):
        self.smi = shutil.which("nvidia-smi")
        if not self.smi and WINDOWS:
            for p in (
                r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
                r"C:\Windows\System32\nvidia-smi.exe",
            ):
                if os.path.exists(p):
                    self.smi = p
                    break
        self._failed = False
        self._qi = 0

    def _rows(self, fields):
        keys = fields.split(",")
        out = run_cmd([
            self.smi, "--query-gpu=" + fields,
            "--format=csv,noheader,nounits",
        ], timeout=4)
        rows = []
        for line in out.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) != len(keys):
                continue
            rows.append(dict(zip(keys, parts)))
        return rows

    def sample(self):
        if not self.smi or self._failed:
            return None

        gpus = []
        while self._qi < len(self.QUERIES):
            fields = self.QUERIES[self._qi]
            rows = self._rows(fields)
            if rows:
                gpus = rows
                break
            self._qi += 1
        if not gpus:
            self._failed = True
            return None

        parsed = []
        for r in gpus:
            parsed.append({
                "name": r.get("name"),
                "util": as_float(r.get("utilization.gpu"), 0.0),
                "mem_used_mib": as_float(r.get("memory.used"), 0.0),
                "mem_total_mib": as_float(r.get("memory.total"), 0.0),
                "temp": as_float(r.get("temperature.gpu")),
                "temp_mem": as_float(r.get("temperature.memory")),
                "power_w": as_float(r.get("power.draw")),
                "power_limit_w": as_float(r.get("power.limit")),
                "fan_percent": as_float(r.get("fan.speed")),
            })

        g = dict(parsed[0])
        g["count"] = len(parsed)
        g["gpus"] = parsed
        g["mem_used_gib"] = round(g["mem_used_mib"] / 1024.0, 2)
        g["mem_total_gib"] = round(g["mem_total_mib"] / 1024.0, 2)
        if g["temp_mem"] is None:
            # AMD / Tesla without a reported HBM sensor: keep the Strata probe value
            g.pop("temp_mem", None)
        return g


# --------------------------------------------------------------------------- #
# Strata collector
# --------------------------------------------------------------------------- #

def collect_strata(base):
    base = (base or "").rstrip("/")
    if not base:
        return {"up": False}
    data = http_json(base + "/metrics", 1.8)
    if not isinstance(data, dict):
        return {"up": False}

    eng = data.get("engine") or {}
    live = data.get("live") or {}
    totals = data.get("totals") or {}
    hist = data.get("history") or {}
    raw_reqs = data.get("requests") or []
    recent = []
    for r in raw_reqs[:24]:
        read = r.get("prompt_read")
        if read is None:
            reused = r.get("reused") or 0
            prm = r.get("prompt_tokens") or 0
            read = max(0, prm - reused)
        recent.append({
            "id": r.get("id"),
            "t": r.get("time"),
            "tok_s": r.get("decode_tok_s"),
            "prefill_tok_s": _speed(read, r.get("prompt_ms")),
            "out": r.get("output_tokens"),
            "prompt": r.get("prompt_tokens"),
            "prompt_read": read,
            "reused": r.get("reused"),
            "finish": r.get("finish"),
            "duration_s": r.get("duration_s"),
        })

    def tail(key, n=60):
        arr = hist.get(key) or []
        return [round(float(x), 2) if isinstance(x, (int, float)) else 0.0 for x in arr[-n:]]

    # both kinds of token throughput: prefill (входные токены) and decode (выходные)
    last = recent[0] if recent else None
    prefill_last = (last or {}).get("prefill_tok_s")
    decode_last = (last or {}).get("tok_s")
    fresh_prompt = max(0, int(totals.get("prompt_tokens") or 0)
                       - int(totals.get("reused") or 0))
    avg_prefill = _speed(fresh_prompt, totals.get("prompt_ms"))
    avg_decode = _speed(totals.get("output_tokens"), totals.get("decode_ms"))

    return {
        "up": True,
        "model": eng.get("model"),
        "context": eng.get("context") or eng.get("max_context"),
        "version": eng.get("version"),
        "kv": eng.get("kv"),
        "state": live.get("state") or "idle",
        "phase": live.get("phase"),
        "tok_s": round(float(live.get("tok_s") or 0), 2),
        "tok_s_mean": round(float(live.get("tok_s_mean") or 0), 2),
        "prefill_tok_s_mean": round(float(live.get("prefill_tok_s_mean") or 0), 2),
        "decode_tok_s_last": decode_last,
        "prefill_tok_s_last": prefill_last,
        "prefill_tok_s_avg": avg_prefill,
        "decode_tok_s_avg": avg_decode,
        "generated": live.get("generated"),
        "max_tokens": live.get("max_tokens"),
        "prompt_tokens": live.get("prompt_tokens"),
        "prompt_read": live.get("prompt_read"),
        "prompt_total": live.get("prompt_total"),
        "elapsed_s": live.get("elapsed_s"),
        "queued": live.get("queued"),
        "vram_free_mib": eng.get("vram_free_mib"),
        "total_requests": totals.get("requests"),
        "total_output_tokens": totals.get("output_tokens"),
        "total_prompt_tokens": totals.get("prompt_tokens"),
        "total_reused_tokens": totals.get("reused"),
        "engine_totals": {
            "requests": totals.get("requests") or 0,
            "prompt_tokens": totals.get("prompt_tokens") or 0,
            "output_tokens": totals.get("output_tokens") or 0,
            "reused": totals.get("reused") or 0,
            "since": totals.get("since"),
        },
        "recent": recent,
        "history": {
            "tok_s": tail("tok_s"),
            "gpu_util": tail("gpu_util"),
            "gpu_temp": tail("gpu_temp"),
            "cpu": tail("cpu"),
            "prefill_tok_s_mean": tail("prefill_tok_s_mean"),
        },
        "hardware": data.get("hardware") or {},
    }


# --------------------------------------------------------------------------- #
# ComfyUI collector
# --------------------------------------------------------------------------- #

def collect_comfy(base):
    base = (base or "").rstrip("/")
    if not base:
        return {"up": False}

    ss = http_json(base + "/system_stats", 1.5)
    q = http_json(base + "/queue", 1.5)
    up = isinstance(ss, dict) or isinstance(q, dict)

    out = {"up": up}
    if isinstance(ss, dict):
        system = ss.get("system") or {}
        devs = ss.get("devices") or []
        out["version"] = system.get("comfyui_version")
        out["torch"] = system.get("pytorch_version")
        out["ram_total_gib"] = gib(system.get("ram_total"))
        out["ram_free_gib"] = gib(system.get("ram_free"))
        if devs:
            d = devs[0]
            out["device"] = d.get("name")
            out["vram_total_gib"] = gib(d.get("vram_total"))
            out["vram_free_gib"] = gib(d.get("vram_free"))
    if isinstance(q, dict):
        out["running"] = len(q.get("queue_running") or [])
        out["pending"] = len(q.get("queue_pending") or [])
    return out


# --------------------------------------------------------------------------- #
# persistent token ledger
# --------------------------------------------------------------------------- #

class TokenLedger:
    """Counts output/prompt tokens per day and all-time.

    Strata /metrics only keeps recent requests and resets its totals when the
    engine restarts, so the agent keeps its own append-only ledger keyed by
    request id and persists it to ~/.tokenpulse/tokens.json.
    """

    MAX_SEEN = 5000

    def __init__(self, path=None):
        self.path = Path(path) if path else (Path.home() / ".tokenpulse" / "tokens.json")
        self.lock = threading.Lock()
        self.data = {
            "version": 1,
            "seeded": False,
            "all_time": {"prompt": 0, "output": 0, "requests": 0},
            "days": {},
        }
        self.seen = set()
        self._order = []
        self._load()

    # -- persistence --------------------------------------------------------
    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                seen = d.pop("seen", []) or []
                self.data.update(d)
                self.seen = {str(x) for x in seen}
                self._order = [str(x) for x in seen]
        except Exception:
            pass

    def _save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            out = dict(self.data)
            out["seen"] = self._order[-self.MAX_SEEN:]
            tmp = str(self.path) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False)
            os.replace(tmp, self.path)
        except Exception:
            pass

    # -- accounting ---------------------------------------------------------
    @staticmethod
    def _day(ts):
        try:
            return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d")
        except Exception:
            return datetime.now().strftime("%Y-%m-%d")

    def _add(self, day, prompt, output, reused=0, count_all=True):
        d = self.data["days"].setdefault(
            day, {"prompt": 0, "output": 0, "reused": 0, "requests": 0})
        d["prompt"] += int(prompt or 0)
        d["output"] += int(output or 0)
        d["reused"] = d.get("reused", 0) + int(reused or 0)
        d["requests"] += 1
        if not count_all:
            return
        a = self.data["all_time"]
        a["prompt"] += int(prompt or 0)
        a["output"] += int(output or 0)
        a["reused"] = a.get("reused", 0) + int(reused or 0)
        a["requests"] += 1

    def _remember(self, rid):
        if rid in self.seen:
            return False
        self.seen.add(rid)
        self._order.append(rid)
        if len(self._order) > self.MAX_SEEN * 2:
            drop = len(self._order) - self.MAX_SEEN
            for old in self._order[:drop]:
                self.seen.discard(old)
            self._order = self._order[drop:]
        return True

    def seed(self, totals, recent):
        """First run: take the engine's current totals as the baseline."""
        with self.lock:
            if self.data.get("seeded"):
                return
            totals = totals or {}
            reqs = int(totals.get("requests") or 0)
            prm = int(totals.get("prompt_tokens") or 0)
            out = int(totals.get("output_tokens") or 0)
            reuse = int(totals.get("reused") or 0)

            if not reqs and recent:
                # engine totals unavailable: rebuild from the request window
                for r in recent:
                    self._add(self._day(r.get("t")), r.get("prompt"),
                              r.get("out"), r.get("reused"))
                    self._remember(str(r.get("id") or ""))
                self.data["seeded"] = True
                self._save()
                return

            self.data["all_time"] = {
                "prompt": prm, "output": out, "reused": reuse, "requests": reqs}
            for r in recent:
                rid = str(r.get("id") or "")
                if rid:
                    self._remember(rid)
                # engine totals already include these requests: only fill the
                # per-day buckets so "today" is correct without double counting
                self._add(self._day(r.get("t")), r.get("prompt"),
                          r.get("out"), r.get("reused"), count_all=False)
            self.data["seeded"] = True
            self._save()

    def update(self, recent):
        changed = False
        with self.lock:
            for r in recent or []:
                rid = str(r.get("id") or "")
                if not rid or rid in self.seen:
                    continue
                self._add(self._day(r.get("t")), r.get("prompt"),
                          r.get("out"), r.get("reused"))
                self._remember(rid)
                changed = True
            if changed:
                self._prune()
                self._save()

    def add_counters(self, key, prompt, output):
        """Engines that only expose token counters (llama.cpp --metrics, vLLM): add the growth
        since the last sample. The first sample is the baseline, a drop means the engine restarted."""
        with self.lock:
            if not hasattr(self, "_counters"):
                self._counters = {}
            prev = self._counters.get(key)
            self._counters[key] = (int(prompt or 0), int(output or 0))
            if prev is None:
                return
            dp, do = self._counters[key][0] - prev[0], self._counters[key][1] - prev[1]
            if dp < 0 or do < 0 or (dp == 0 and do == 0):
                return
            day = datetime.now().strftime("%Y-%m-%d")
            d = self.data["days"].setdefault(day, {"prompt": 0, "output": 0, "reused": 0, "requests": 0})
            d["prompt"] += dp
            d["output"] += do
            a = self.data["all_time"]
            a["prompt"] += dp
            a["output"] += do
            self._prune()
            now = time.time()
            if now - getattr(self, "_saved_at", 0) > 5:
                self._saved_at = now
                self._save()

    def _prune(self):
        days = self.data.get("days") or {}
        if len(days) <= 420:
            return
        for day in sorted(days)[:-420]:
            days.pop(day, None)

    # -- output -------------------------------------------------------------
    def snapshot(self):
        today = datetime.now().strftime("%Y-%m-%d")
        with self.lock:
            d = self.data["days"].get(today) or {}
            a = self.data["all_time"]

            def block(src):
                prm = int(src.get("prompt") or 0)
                out = int(src.get("output") or 0)
                reuse = int(src.get("reused") or 0)
                return {
                    "prompt": prm,
                    "output": out,
                    "reused": reuse,
                    "requests": int(src.get("requests") or 0),
                    "total": prm + out,
                }

            return {
                "today": block(d),
                "all_time": block(a),
                "days": sorted((self.data.get("days") or {}).keys())[-14:],
                "days_tracked": len(self.data.get("days") or {}),
                "since_seeded": bool(self.data.get("seeded")),
            }

    def dump(self, limit=90):
        """Daily history, for the web dashboard and for exports."""
        with self.lock:
            days = self.data.get("days") or {}
            keys = sorted(days)[-limit:]
            return {
                "all_time": dict(self.data.get("all_time") or {}),
                "days": {k: dict(days[k]) for k in keys},
                "days_tracked": len(days),
            }


# --------------------------------------------------------------------------- #
# sampler
# --------------------------------------------------------------------------- #

class EngineEntry:
    """One configured engine address: finds out what it is, then samples it every second."""

    def __init__(self, url, kind="auto", explicit=False):
        self.url = url.rstrip("/")
        self.want = kind
        self.kind = None if kind == "auto" else kind
        self.explicit = explicit
        self.adapter = None
        self.next_probe = 0.0
        self.fails = 0

    def sample(self, gpu_util, other_busy):
        now = time.time()
        if self.kind is None:
            if now < self.next_probe:
                return {"up": False, "kind": None, "name": self.url, "url": self.url}
            self.kind = engines.detect(self.url)
            self.next_probe = now + 10
            self.adapter = None
            if self.kind is None:
                return {"up": False, "kind": None, "name": self.url, "url": self.url}
        if self.kind == "strata":
            res = collect_strata(self.url)
            if res.get("up"):
                res.update(kind="strata", name="Strata", url=self.url)
                res.setdefault("speed", "live")
            else:
                res = {"up": False, "kind": "strata", "name": "Strata", "url": self.url}
        else:
            if self.adapter is None:
                self.adapter = engines.make_adapter(self.kind, self.url)
            res = self.adapter.sample(gpu_util, other_busy)
        if res.get("up"):
            self.fails = 0
        else:
            self.fails += 1
            if self.fails >= 3 and self.want == "auto":
                self.kind, self.fails, self.next_probe = None, 0, now + 5
        return res


class EngineSet:
    def __init__(self, targets):
        self.entries = [EngineEntry(u, k, explicit) for k, u, explicit in targets]

    def sample(self, gpu_util, other_busy):
        results = [e.sample(gpu_util, other_busy) for e in self.entries]
        up = [r for r in results if r.get("up")]
        busy = [r for r in up if r.get("state") in ("generating", "reading")]
        primary = (busy or up or [results[0] if results else {"up": False}])[0]
        chips = [{"kind": r.get("kind"), "name": r.get("name"), "url": r.get("url"), "up": bool(r.get("up")),
                  "state": r.get("state"), "model": r.get("model")}
                 for e, r in zip(self.entries, results) if r.get("up") or e.explicit]
        return results, primary, chips


class Sampler(threading.Thread):
    def __init__(self, targets, comfy_url, interval=1.0):
        super().__init__(daemon=True)
        self.engines = EngineSet(targets)
        self.comfy_url = comfy_url
        self.interval = max(0.3, float(interval))
        self.sys = SystemCollector()
        self.gpu = GpuCollector()
        self.ledger = TokenLedger()
        self._state = {"time": 0}
        self._lock = threading.Lock()
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def snapshot(self):
        with self._lock:
            return dict(self._state)

    def run(self):
        while not self._stop.is_set():
            t0 = time.time()
            try:
                state = self._collect()
            except Exception as e:
                state = {"error": str(e)}
            state["time"] = time.time()
            state["agent"] = {
                "version": VERSION,
                "hostname": socket.gethostname(),
                "os": platform.system(),
                "uptime_s": state.get("cpu", {}).get("uptime_s"),
            }
            with self._lock:
                self._state = state
            delay = self.interval - (time.time() - t0)
            self._stop.wait(max(0.1, delay))

    def _collect(self):
        cpu = self.sys.sample()
        gpu = self.gpu.sample()
        comfy = collect_comfy(self.comfy_url)
        results, strata, chips = self.engines.sample(gpu.get("util") if gpu else None,
                                                     bool(comfy.get("running")))

        for r in results:
            if not r.get("up"):
                continue
            if r.get("kind") == "strata":
                self.ledger.seed(r.get("engine_totals") or {}, r.get("recent") or [])
                self.ledger.update(r.get("recent") or [])
            elif r.get("engine_totals"):
                et = r["engine_totals"]
                self.ledger.add_counters(r.get("url"), et.get("prompt_tokens"), et.get("output_tokens"))

        # fall back to Strata's own hardware probe when nvidia-smi is unavailable
        hw = strata.get("hardware") or {}
        if gpu is None and hw:
            gpu = {
                "name": (hw.get("gpu_name") or "GPU"),
                "count": hw.get("gpu_count") or 1,
                "util": hw.get("gpu_util"),
                "mem_used_gib": gib(hw.get("gpu_mem_used")),
                "mem_total_gib": gib(hw.get("gpu_mem_total")),
                "temp": hw.get("gpu_temp"),
                "power_w": hw.get("gpu_power"),
                "power_limit_w": hw.get("gpu_power_limit"),
            }
            if gpu["mem_used_gib"] is None and hw.get("gpu_mem_used"):
                gpu["mem_used_gib"] = round(hw["gpu_mem_used"] / 1073741824.0, 2)
        if gpu is None:
            gpu = {"count": 0, "name": "GPU"}

        if not cpu.get("ram_total_gib") and hw:
            cpu["ram_used_gib"] = gib(hw.get("ram_used"))
            cpu["ram_total_gib"] = gib(hw.get("ram_total"))
            if cpu.get("percent") in (None, 0):
                cpu["percent"] = hw.get("cpu")

        if gpu.get("temp") is None and hw.get("gpu_temp") is not None:
            gpu["temp"] = hw.get("gpu_temp")
        if gpu.get("temp_mem") is None and cpu.get("temp_sensors"):
            # AMD boards expose HBM/GPU memory temperature through hwmon
            for s in cpu["temp_sensors"]:
                if s.get("chip") in ("amdgpu", "i915") and \
                        str(s.get("label", "")).lower() in ("vdd", "mem", "memory", "hbm", "soc"):
                    gpu["temp_mem"] = s["temp_c"]
                    break

        temps = {
            "cpu": cpu.get("temp_c"),
            "cpu_max": cpu.get("temp_max_c"),
            "cpu_limit": cpu.get("temp_limit_c"),
            "cpu_source": cpu.get("temp_source"),
            "cpu_hint": cpu.get("temp_hint"),
            "cpu_cores": cpu.get("temp_cores") or [],
            "gpu": gpu.get("temp"),
            "gpu_mem": gpu.get("temp_mem"),
            "gpu_source": gpu.get("name"),
        }

        legacy = dict(strata)      # old clients (widget.py) read "strata" and expect numbers
        for k in ("tok_s", "tok_s_mean", "prefill_tok_s_mean"):
            if legacy.get("up"):
                legacy[k] = legacy.get(k) or 0

        return {
            "cpu": cpu,
            "gpu": gpu,
            "temps": temps,
            "engine": strata,
            "engines": chips,
            "strata": legacy,
            "comfyui": comfy,
            "tokens": self.ledger.snapshot(),
        }


class DemoSampler(Sampler):
    """Synthetic data in the same shape as the real one: --demo / TP_DEMO=1.
    Lets you look at the clients without a GPU, Strata or ComfyUI."""

    def __init__(self, interval=1.0):
        super().__init__([], "", interval)
        import random
        self.rnd = random.Random(7)
        self.t0 = time.time()
        self.hist = []
        self.recent = []
        self.today = {"prompt": 41250000, "output": 312116, "reused": 40610000, "requests": 343}
        self.all = {"prompt": 56660000, "output": 438901, "reused": 55690000, "requests": 466}
        self.req = None

    def _collect(self):
        r, now = self.rnd, time.time()
        if self.req is None and r.random() < 0.18:
            self.req = {"id": "demo-%d" % int(now), "phase": "reading", "read": 0,
                        "total": r.choice([1200, 4400, 34000, 138000]), "gen": 0,
                        "max": r.choice([256, 512, 1024]), "start": now}
        state, tok, pre = "idle", 0.0, 0.0
        q = self.req
        if q:
            if q["phase"] == "reading":
                pre = 600 + r.random() * 90
                q["read"] = min(q["total"], q["read"] + int(pre * self.interval))
                state = "reading"
                if q["read"] >= q["total"]:
                    q["phase"] = "generating"
            else:
                tok = 55 + 10 * math.sin(now / 3) + r.random() * 6
                q["gen"] = min(q["max"], q["gen"] + int(tok * self.interval))
                state = "generating"
                if q["gen"] >= q["max"]:
                    self.recent.insert(0, {"id": q["id"], "t": now, "tok_s": round(tok, 1),
                                           "prefill_tok_s": round(640 + r.random() * 40, 1),
                                           "out": q["gen"], "prompt": q["total"], "prompt_read": q["total"],
                                           "reused": 0, "finish": "stop", "duration_s": round(now - q["start"], 1)})
                    del self.recent[24:]
                    for b in (self.today, self.all):
                        b["prompt"] += q["total"]; b["output"] += q["gen"]; b["requests"] += 1
                    self.req = None
        self.hist.append(round(tok, 2)); del self.hist[:-60]
        busy = state != "idle"
        util = (92 + r.random() * 7) if busy else (3 + r.random() * 4)
        cpu = (38 + r.random() * 20) if state == "reading" else (12 + r.random() * 8 if busy else 2 + r.random() * 3)
        gtemp = 48 + (24 if busy else 0) + r.random() * 3
        last = self.recent[0] if self.recent else {}

        def block(b):
            return dict(b, total=b["prompt"] + b["output"])
        gpu = {"name": "NVIDIA GeForce RTX 3060", "util": round(util, 1), "mem_used_mib": 11160.0,
               "mem_total_mib": 12288.0, "mem_used_gib": 10.9, "mem_total_gib": 12.0, "temp": round(gtemp, 1),
               "power_w": round((150 + r.random() * 18) if busy else 18 + r.random() * 4, 1),
               "power_limit_w": 170.0, "fan_percent": 64.0 if busy else 30.0, "count": 1}
        cpu_d = {"percent": round(cpu, 1), "name": "AMD Ryzen 7 5700G", "cores": 8, "threads": 16,
                 "temp_c": round(44 + cpu / 4 + r.random() * 2, 1), "ram_percent": 61.0,
                 "ram_used_gib": 38.9, "ram_total_gib": 64.0, "uptime_s": int(now - self.t0) + 86400 * 3}
        strata = {"up": True, "model": "Qwen3.8-Flash-Next IQ3_XXS", "context": 262144, "version": "0.1.57",
                  "state": state, "tok_s": round(tok, 2), "tok_s_mean": round(tok, 2),
                  "prefill_tok_s_mean": round(pre, 2), "decode_tok_s_last": last.get("tok_s"),
                  "prefill_tok_s_last": last.get("prefill_tok_s"), "decode_tok_s_avg": 61.0,
                  "prefill_tok_s_avg": 619.0, "generated": q and q["gen"], "max_tokens": q and q["max"],
                  "prompt_tokens": q and q["total"], "prompt_read": q and q["read"],
                  "prompt_total": q and q["total"], "queued": 0, "recent": self.recent[:12],
                  "history": {"tok_s": list(self.hist)}}
        comfy = {"up": True, "version": "0.3.66", "device": "cuda:0 RTX 3060", "vram_total_gib": 12.0,
                 "vram_free_gib": 1.1, "running": 1 if r.random() < 0.3 else 0, "pending": r.choice([0, 0, 1, 2])}
        strata.update(kind="strata", name="Strata", speed="live")
        return {"cpu": cpu_d, "gpu": gpu,
                "temps": {"cpu": cpu_d["temp_c"], "gpu": gpu["temp"], "gpu_mem": None},
                "engine": strata, "strata": strata, "comfyui": comfy,
                "engines": [{"kind": "strata", "name": "Strata", "up": True, "state": state, "model": strata["model"]}],
                "tokens": {"today": block(self.today), "all_time": block(self.all)}}


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #

class Handler(BaseHTTPRequestHandler):
    server_version = "StrataMonitor/" + VERSION
    sampler = None
    token = ""

    def _headers(self, code=200, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    # -- optional API token ---------------------------------------------------
    # Empty token (the default) keeps the API open. When TP_TOKEN / --token is
    # set, the client may pass it as ?token=..., X-Token: ... or
    # Authorization: Bearer ...
    def _request_token(self):
        got = self.headers.get("X-Token") or ""
        if not got:
            auth = self.headers.get("Authorization") or ""
            if auth.lower().startswith("bearer "):
                got = auth[7:].strip()
        if not got:
            qs = parse_qs(urlsplit(self.path).query)
            got = (qs.get("token") or [""])[0]
        return got

    def _authorized(self):
        want = self.token or ""
        if not want:
            return True
        return hmac.compare_digest(self._request_token(), want)

    def _unauthorized(self):
        body = json.dumps({"ok": False, "error": "unauthorized"},
                          ensure_ascii=False).encode("utf-8")
        self._headers(401)
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._headers(204)

    def do_GET(self):
        path = self.path.split("?", 1)[0]

        if path in ("/api/stats", "/stats.json", "/api/tokens", "/tokens.json"):
            if not self._authorized():
                self._unauthorized()
                return

        if path in ("/api/stats", "/stats.json"):
            body = json.dumps(self.sampler.snapshot(), ensure_ascii=False).encode("utf-8")
            self._headers()
            self.wfile.write(body)
            return

        if path in ("/api/tokens", "/tokens.json"):
            body = json.dumps(self.sampler.ledger.dump(), ensure_ascii=False).encode("utf-8")
            self._headers()
            self.wfile.write(body)
            return

        if path == "/api/health":
            body = json.dumps({"ok": True, "version": VERSION,
                               "auth": bool(self.token)}).encode("utf-8")
            self._headers()
            self.wfile.write(body)
            return

        if path == "/":
            path = "/index.html"

        # static files from web/
        rel = os.path.normpath(path.lstrip("/")).replace("\\", "/")
        if rel.startswith("..") or rel.startswith("/"):
            self._headers(403, "text/plain; charset=utf-8")
            self.wfile.write(b"forbidden")
            return
        full = os.path.join(WEB_DIR, rel)
        if os.path.isfile(full):
            ctype = {
                ".html": "text/html; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
                ".svg": "image/svg+xml",
                ".json": "application/json; charset=utf-8",
                ".png": "image/png",
                ".ico": "image/x-icon",
            }.get(os.path.splitext(full)[1].lower(), "application/octet-stream")
            with open(full, "rb") as f:
                body = f.read()
            self._headers(200, ctype)
            self.wfile.write(body)
            return

        body = (
            "<!doctype html><meta charset=utf-8><title>Strata Monitor</title>"
            "<style>body{background:#070b14;color:#e8eefc;font:15px system-ui;"
            "display:grid;place-items:center;height:100vh;margin:0}"
            "a{color:#22d3ee}</style>"
            "<div><h1>Strata Monitor agent</h1>"
            "<p>API: <a href='/api/stats'>/api/stats</a></p></div>"
        ).encode("utf-8")
        self._headers(200, "text/html; charset=utf-8")
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


def main():
    ap = argparse.ArgumentParser(description="Strata/ComfyUI monitor agent")
    ap.add_argument("--host", default=os.environ.get("MONITOR_HOST", "0.0.0.0"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("MONITOR_PORT", "8787")))
    ap.add_argument("--strata", default=os.environ.get("STRATA_URL", ""),
                    help="Strata address (kept for compatibility, same as --engine)")
    ap.add_argument("--engine", default=os.environ.get("ENGINE_URL", ""),
                    help="engine address(es), comma separated: http://127.0.0.1:1234 or lmstudio=http://host:1234. "
                         "Default: look for Strata, llama.cpp, LM Studio, Ollama and vLLM on their usual local ports")
    ap.add_argument("--engine-kind", default=os.environ.get("ENGINE_KIND", "auto"),
                    help="auto | strata | llamacpp | lmstudio | ollama | vllm | openai")
    ap.add_argument("--comfy", default=os.environ.get("COMFY_URL", "http://127.0.0.1:8188"))
    ap.add_argument("--interval", type=float, default=float(os.environ.get("MONITOR_INTERVAL", "1.0")))
    ap.add_argument("--token", default=os.environ.get("TP_TOKEN", ""),
                    help="optional API token; empty keeps the API open")
    ap.add_argument("--demo", action="store_true", default=os.environ.get("TP_DEMO") == "1",
                    help="synthetic data, no GPU / Strata / ComfyUI needed")
    args = ap.parse_args()

    targets = []
    for spec in (args.strata, args.engine):
        for kind, url in engines.parse_targets(spec, engines.normalize_kind(args.engine_kind)):
            targets.append((kind, url, True))
    if not targets:
        for port in (8080, 1234, 11434, 8000):     # Strata / llama.cpp, LM Studio, Ollama, vLLM
            targets.append(("auto", "http://127.0.0.1:%d" % port, False))
    sampler = DemoSampler(args.interval) if args.demo else Sampler(targets, args.comfy, args.interval)
    Handler.sampler = sampler
    Handler.token = (args.token or "").strip()
    sampler.start()

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    srv.daemon_threads = True
    print("strata-monitor agent %s" % VERSION)
    print("  listen : http://%s:%d" % (args.host, args.port))
    print("  engines: %s" % ", ".join(u for _, u, _ in targets))
    print("  comfy  : %s" % args.comfy)
    print("  local  : http://127.0.0.1:%d" % args.port)
    print("  demo   : %s" % ("on" if args.demo else "off"))
    print("  auth   : %s" % ("token required" if Handler.token else "open (no token)"))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        sampler.stop()
        srv.server_close()


if __name__ == "__main__":
    main()
