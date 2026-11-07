# -*- coding: utf-8 -*-
"""
Inference-engine adapters for the TokenPulse agent (standard library only).

Every adapter turns one engine's own API into the same dict the clients draw
(the same keys the agent has always produced for Strata):

    up, kind, name, model, context, version, state, tok_s, prefill_tok_s_mean,
    generated, max_tokens, prompt_tokens, prompt_read, prompt_total, queued,
    engine_totals, recent, history, speed, note

state  : "generating" | "reading" | "idle" | "unloaded"
speed  : "live"  - tok/s measured now (Strata, vLLM, llama.cpp with /slots progress)
         "avg"   - only an average the engine reports (llama.cpp /metrics)
         "none"  - the engine does not expose speed (LM Studio, Ollama, plain OpenAI API)

What each engine gives, and what it does not:

  Strata     /metrics                      everything (agent.collect_strata handles it)
  llama.cpp  /props /slots /metrics        state, context, queue, speed; start the server
             (llama-server)                with --metrics for token totals and averages
  vLLM       /metrics (Prometheus)         queue, live tok/s from counters, KV-cache use
  LM Studio  /api/v0/models                loaded model and context only; no speed
  Ollama     /api/ps /api/version          loaded model, VRAM use; no speed
  other      /v1/models                    model name only (any OpenAI-compatible server)

For the engines that do not report activity (LM Studio, Ollama, other) the state is
inferred from GPU load, and the result says so in "note".
"""

import json
import re
import time
from urllib.request import Request, urlopen

KINDS = ("strata", "llamacpp", "vllm", "lmstudio", "ollama", "openai")
NAMES = {"strata": "Strata", "llamacpp": "llama.cpp", "vllm": "vLLM",
         "lmstudio": "LM Studio", "ollama": "Ollama", "openai": "OpenAI API"}
ALIASES = {"llama": "llamacpp", "llama.cpp": "llamacpp", "llama-server": "llamacpp",
           "lm-studio": "lmstudio", "lm_studio": "lmstudio", "lms": "lmstudio",
           "openai-compatible": "openai", "other": "openai"}
GPU_BUSY = 35.0     # % GPU load that counts as "working" for engines without activity info


# --------------------------------------------------------------------------- #
# http + prometheus text
# --------------------------------------------------------------------------- #

def http_text(url, timeout=1.5):
    try:
        req = Request(url, headers={"User-Agent": "tokenpulse-agent",
                                    "Accept": "application/json, text/plain, */*"})
        with urlopen(req, timeout=timeout) as r:
            return r.read(4 * 1024 * 1024).decode("utf-8", "replace")
    except Exception:
        return None


def http_json(url, timeout=1.5):
    text = http_text(url, timeout)
    if text is None:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


_PROM = re.compile(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^}]*\})?\s+([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?|NaN|[-+]Inf)\s*$')


def parse_prom(text):
    """Prometheus text format -> {metric name: [(labels dict, value), ...]}."""
    out = {}
    for line in (text or "").splitlines():
        if not line or line[0] == "#":
            continue
        m = _PROM.match(line.strip())
        if not m:
            continue
        name, lab, val = m.groups()
        try:
            v = float(val)
        except ValueError:
            continue
        if v != v or v in (float("inf"), float("-inf")):
            continue
        labels = dict(re.findall(r'(\w+)="((?:[^"\\]|\\.)*)"', lab or ""))
        out.setdefault(name, []).append((labels, v))
    return out


def psum(prom, *names):
    """Sum of every series of the first metric name that exists, else None."""
    for n in names:
        if n in prom:
            return sum(v for _, v in prom[n])
    return None


def pmax(prom, *names):
    for n in names:
        if n in prom:
            return max(v for _, v in prom[n])
    return None


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _short_model(name):
    name = str(name or "")
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    return re.sub(r"\.gguf$", "", name, flags=re.I) or None


# --------------------------------------------------------------------------- #
# detection
# --------------------------------------------------------------------------- #

def detect(base):
    """Ask the server which engine it is. Returns a kind from KINDS or None."""
    base = base.rstrip("/")
    m = http_json(base + "/metrics", 1.2)
    if isinstance(m, dict) and isinstance(m.get("engine"), dict) and "live" in m:
        return "strata"
    props = http_json(base + "/props", 1.2)
    if isinstance(props, dict) and ("default_generation_settings" in props or "total_slots" in props):
        return "llamacpp"
    if isinstance(http_json(base + "/api/ps", 1.2), dict) and \
            isinstance(http_json(base + "/api/version", 1.2), dict):
        return "ollama"
    lm = http_json(base + "/api/v0/models", 1.2)
    if isinstance(lm, dict) and isinstance(lm.get("data"), list):
        return "lmstudio"
    prom = http_text(base + "/metrics", 1.2)
    if prom and "vllm:" in prom:
        return "vllm"
    models = http_json(base + "/v1/models", 1.2)
    if isinstance(models, dict) and isinstance(models.get("data"), list):
        return "openai"
    return None


def normalize_kind(kind):
    kind = (kind or "auto").strip().lower()
    kind = ALIASES.get(kind, kind)
    return kind if kind in KINDS else "auto"


# --------------------------------------------------------------------------- #
# adapters
# --------------------------------------------------------------------------- #

def _empty(kind, base):
    return {"up": False, "kind": kind, "name": NAMES.get(kind, kind), "url": base}


def _base_result(kind, base):
    return {"up": True, "kind": kind, "name": NAMES[kind], "url": base,
            "model": None, "context": None, "version": None, "state": "idle",
            "tok_s": None, "tok_s_mean": None, "prefill_tok_s_mean": None,
            "decode_tok_s_last": None, "prefill_tok_s_last": None,
            "decode_tok_s_avg": None, "prefill_tok_s_avg": None,
            "generated": None, "max_tokens": None, "prompt_tokens": None,
            "prompt_read": None, "prompt_total": None, "elapsed_s": None,
            "queued": 0, "running": 0, "total_requests": None,
            "total_output_tokens": None, "total_prompt_tokens": None,
            "engine_totals": None, "recent": [], "history": {"tok_s": []},
            "hardware": {}, "speed": "none", "note": None}


class Adapter(object):
    kind = "openai"

    def __init__(self, base):
        self.base = base.rstrip("/")
        self.t_prev = None
        self.prev = {}
        self.hist = []

    # rates from monotonic counters between two samples
    def rate(self, key, value, now):
        prev = self.prev.get(key)
        self.prev[key] = (value, now)
        if prev is None or value is None or prev[0] is None:
            return None
        dv, dt = value - prev[0], now - prev[1]
        if dv < 0 or dt <= 0:
            return None
        return dv / dt

    def push_hist(self, v):
        self.hist.append(round(float(v or 0), 2))
        del self.hist[:-60]
        return list(self.hist)

    def sample(self, gpu_util=None, other_busy=False):
        raise NotImplementedError


class LlamaCpp(Adapter):
    kind = "llamacpp"

    def sample(self, gpu_util=None, other_busy=False):
        now = time.time()
        health = http_json(self.base + "/health", 1.2)
        props = http_json(self.base + "/props", 1.2)
        if props is None and health is None:
            return _empty(self.kind, self.base)
        r = _base_result(self.kind, self.base)
        props = props if isinstance(props, dict) else {}
        gen = props.get("default_generation_settings") or {}
        r["context"] = _num(gen.get("n_ctx")) or _num((gen.get("params") or {}).get("n_ctx"))
        r["model"] = props.get("model_alias") or _short_model(props.get("model_path"))
        r["version"] = props.get("build_info")
        loading = isinstance(health, dict) and health.get("status") not in (None, "ok")
        if loading:
            r["state"] = "unloaded"
            r["note"] = "модель загружается"

        slots = http_json(self.base + "/slots", 1.2)
        busy = 0
        decoded_total = 0
        have_progress = False
        if isinstance(slots, list):
            for s in slots:
                if not isinstance(s, dict):
                    continue
                if not r["context"]:
                    r["context"] = _num(s.get("n_ctx"))
                if s.get("is_processing"):
                    busy += 1
                nxt = s.get("next_token")
                nxt = nxt[0] if isinstance(nxt, list) and nxt else nxt
                if isinstance(nxt, dict) and _num(nxt.get("n_decoded")) is not None:
                    have_progress = True
                    if s.get("is_processing"):
                        decoded_total += nxt["n_decoded"]
            r["running"] = busy

        prom = parse_prom(http_text(self.base + "/metrics", 1.2))
        if prom:
            proc = psum(prom, "llamacpp:requests_processing")
            if proc is not None:
                busy = max(busy, int(proc))
                r["running"] = busy
            r["queued"] = int(psum(prom, "llamacpp:requests_deferred") or 0)
            r["decode_tok_s_avg"] = _round(psum(prom, "llamacpp:predicted_tokens_seconds"))
            r["prefill_tok_s_avg"] = _round(psum(prom, "llamacpp:prompt_tokens_seconds"))
            pt = psum(prom, "llamacpp:prompt_tokens_total")
            ot = psum(prom, "llamacpp:tokens_predicted_total")
            if pt is not None and ot is not None:
                r["total_prompt_tokens"], r["total_output_tokens"] = int(pt), int(ot)
                r["engine_totals"] = {"prompt_tokens": int(pt), "output_tokens": int(ot),
                                      "requests": 0, "reused": 0}

        live = None
        if have_progress:
            live = self.rate("decoded", decoded_total if busy else 0, now)
        if not loading:
            r["state"] = "generating" if busy else "idle"
        if busy and live is not None and live > 0:
            r["tok_s"] = r["tok_s_mean"] = round(live, 1)
            r["speed"] = "live"
        elif r["decode_tok_s_avg"]:
            r["speed"] = "avg"
            if busy:
                r["note"] = "скорость: среднее по движку"
        elif busy:
            r["note"] = "запустите llama-server с --metrics, чтобы видеть скорость"
        if not prom and not loading:
            r["note"] = r["note"] or "запустите llama-server с --metrics, чтобы видеть скорость и токены"
        r["history"] = {"tok_s": self.push_hist(r["tok_s"] if r["state"] == "generating" else 0)}
        return r


class VLLM(Adapter):
    kind = "vllm"

    def sample(self, gpu_util=None, other_busy=False):
        now = time.time()
        text = http_text(self.base + "/metrics", 1.5)
        prom = parse_prom(text)
        if not prom:
            return _empty(self.kind, self.base)
        r = _base_result(self.kind, self.base)
        running = int(psum(prom, "vllm:num_requests_running") or 0)
        waiting = int(psum(prom, "vllm:num_requests_waiting") or 0)
        r["running"], r["queued"] = running, waiting
        pt = psum(prom, "vllm:prompt_tokens_total")
        gt = psum(prom, "vllm:generation_tokens_total")
        if pt is not None and gt is not None:
            r["total_prompt_tokens"], r["total_output_tokens"] = int(pt), int(gt)
            r["engine_totals"] = {"prompt_tokens": int(pt), "output_tokens": int(gt),
                                  "requests": int(psum(prom, "vllm:request_success_total") or 0), "reused": 0}
        dec = self.rate("gen", gt, now)
        pre = self.rate("prompt", pt, now)
        if running or waiting:
            r["state"] = "generating" if (dec or 0) > 0 or not (pre or 0) else "reading"
            if (pre or 0) > 0 and not (dec or 0):
                r["state"] = "reading"
        if dec is not None and dec > 0:
            r["tok_s"] = r["tok_s_mean"] = round(dec, 1)
        if pre is not None and pre > 0:
            r["prefill_tok_s_mean"] = round(pre, 1)
        r["speed"] = "live"
        for labels, _ in (prom.get("vllm:num_requests_running") or prom.get("vllm:prompt_tokens_total") or []):
            if labels.get("model_name"):
                r["model"] = labels["model_name"]
                break
        cache = pmax(prom, "vllm:gpu_cache_usage_perc", "vllm:kv_cache_usage_perc")
        if cache is not None:
            r["hardware"] = {"kv_cache_percent": round(cache * 100, 1)}
        models = http_json(self.base + "/v1/models", 1.2)
        if isinstance(models, dict) and models.get("data"):
            m0 = models["data"][0]
            r["model"] = r["model"] or m0.get("id")
            r["context"] = _num(m0.get("max_model_len"))
        r["history"] = {"tok_s": self.push_hist(r["tok_s"] if r["state"] == "generating" else 0)}
        return r


class _Inferred(Adapter):
    """Engines with no activity API: loaded model from the engine, state from GPU load."""

    def infer(self, r, loaded, gpu_util, other_busy):
        if not loaded:
            r["state"] = "unloaded"
            return
        busy = (gpu_util is not None and gpu_util >= GPU_BUSY and not other_busy)
        r["state"] = "generating" if busy else "idle"
        r["note"] = ("работает: по загрузке GPU, этот движок не отдаёт скорость" if busy
                     else "этот движок не отдаёт скорость генерации")
        r["history"] = {"tok_s": self.push_hist(0)}


class LMStudio(_Inferred):
    kind = "lmstudio"

    def sample(self, gpu_util=None, other_busy=False):
        data = http_json(self.base + "/api/v0/models", 1.5)
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            return _empty(self.kind, self.base)
        r = _base_result(self.kind, self.base)
        llms = [m for m in data["data"] if isinstance(m, dict) and m.get("type", "llm") in ("llm", "vlm")]
        loaded = [m for m in llms if m.get("state") == "loaded"]
        pick = loaded[0] if loaded else (llms[0] if llms else None)
        if pick:
            r["model"] = pick.get("id")
            r["context"] = _num(pick.get("loaded_context_length")) or _num(pick.get("max_context_length"))
            q = pick.get("quantization")
            if q and r["model"]:
                r["model"] = "%s %s" % (r["model"], q)
        r["running"] = len(loaded)
        self.infer(r, bool(loaded), gpu_util, other_busy)
        return r


class Ollama(_Inferred):
    kind = "ollama"

    def sample(self, gpu_util=None, other_busy=False):
        ver = http_json(self.base + "/api/version", 1.2)
        ps = http_json(self.base + "/api/ps", 1.5)
        if not isinstance(ps, dict) and not isinstance(ver, dict):
            return _empty(self.kind, self.base)
        r = _base_result(self.kind, self.base)
        r["version"] = (ver or {}).get("version")
        models = (ps or {}).get("models") or []
        if models:
            m = models[0]
            r["model"] = m.get("name") or m.get("model")
            r["context"] = _num(m.get("context_length"))
            det = m.get("details") or {}
            if det.get("quantization_level") and r["model"]:
                r["model"] = "%s %s" % (r["model"], det["quantization_level"])
            vram = _num(m.get("size_vram"))
            if vram:
                r["hardware"] = {"vram_used_gib": round(vram / 1073741824.0, 2)}
        r["running"] = len(models)
        self.infer(r, bool(models), gpu_util, other_busy)
        return r


class OpenAICompat(_Inferred):
    kind = "openai"

    def sample(self, gpu_util=None, other_busy=False):
        data = http_json(self.base + "/v1/models", 1.5)
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            return _empty(self.kind, self.base)
        r = _base_result(self.kind, self.base)
        items = [m for m in data["data"] if isinstance(m, dict)]
        if items:
            r["model"] = items[0].get("id")
            r["context"] = _num(items[0].get("max_model_len")) or _num(items[0].get("context_length"))
        r["running"] = len(items)
        self.infer(r, bool(items), gpu_util, other_busy)
        return r


def _round(v, nd=1):
    return round(v, nd) if isinstance(v, (int, float)) and v > 0 else None


ADAPTERS = {"llamacpp": LlamaCpp, "vllm": VLLM, "lmstudio": LMStudio,
            "ollama": Ollama, "openai": OpenAICompat}


def make_adapter(kind, base):
    return ADAPTERS[kind](base)


def parse_targets(spec, default_kind="auto"):
    """'http://host:1234' | 'lmstudio=http://host:1234' | comma-separated list -> [(kind, url)]"""
    out = []
    for part in re.split(r"[,\s;]+", spec or ""):
        part = part.strip()
        if not part:
            continue
        kind = default_kind
        if "=" in part and not part.lower().startswith("http"):
            k, part = part.split("=", 1)
            kind = normalize_kind(k)
        if not re.match(r"^https?://", part, re.I):
            part = "http://" + part
        out.append((kind, part.rstrip("/")))
    return out
