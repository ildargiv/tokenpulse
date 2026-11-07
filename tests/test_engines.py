# -*- coding: utf-8 -*-
"""Engine adapters against fake servers that answer in each engine's real response format.
Run:  python3 -m unittest discover -s tests -v   (from the repository root)"""
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engines  # noqa: E402

LLAMA_METRICS = """# HELP llamacpp:prompt_tokens_total Number of prompt tokens processed.
# TYPE llamacpp:prompt_tokens_total counter
llamacpp:prompt_tokens_total 1200
llamacpp:prompt_seconds_total 2.5
llamacpp:tokens_predicted_total 4500
llamacpp:tokens_predicted_seconds_total 90.0
llamacpp:prompt_tokens_seconds 480.0
llamacpp:predicted_tokens_seconds 50.0
llamacpp:requests_processing 1
llamacpp:requests_deferred 2
"""
VLLM_METRICS = """# TYPE vllm:num_requests_running gauge
vllm:num_requests_running{model_name="Qwen/Qwen2.5-7B-Instruct"} 2.0
vllm:num_requests_waiting{model_name="Qwen/Qwen2.5-7B-Instruct"} 1.0
vllm:gpu_cache_usage_perc{model_name="Qwen/Qwen2.5-7B-Instruct"} 0.37
vllm:prompt_tokens_total{model_name="Qwen/Qwen2.5-7B-Instruct"} %(p)d
vllm:generation_tokens_total{model_name="Qwen/Qwen2.5-7B-Instruct"} %(g)d
"""
STATE = {"vllm_p": 1000, "vllm_g": 5000}


def routes(kind):
    if kind == "llamacpp":
        return {"/health": {"status": "ok"},
                "/props": {"default_generation_settings": {"n_ctx": 8192}, "total_slots": 1,
                           "model_path": "/models/Qwen3-8B-Q4_K_M.gguf", "build_info": "b4567-abc"},
                "/slots": [{"id": 0, "n_ctx": 8192, "is_processing": True}],
                "/metrics": LLAMA_METRICS}
    if kind == "vllm":
        STATE["vllm_g"] += 70
        return {"/metrics": VLLM_METRICS % {"p": STATE["vllm_p"], "g": STATE["vllm_g"]},
                "/v1/models": {"data": [{"id": "Qwen/Qwen2.5-7B-Instruct", "max_model_len": 32768}]}}
    if kind == "lmstudio":
        return {"/api/v0/models": {"object": "list", "data": [
            {"id": "qwen2.5-7b-instruct", "type": "llm", "state": "loaded", "quantization": "Q4_K_M",
             "max_context_length": 32768, "loaded_context_length": 4096},
            {"id": "text-embedding-nomic", "type": "embeddings", "state": "not-loaded"}]},
            "/v1/models": {"data": [{"id": "qwen2.5-7b-instruct"}]}}
    if kind == "ollama":
        return {"/api/version": {"version": "0.5.1"},
                "/api/ps": {"models": [{"name": "llama3:8b", "size_vram": 6442450944, "context_length": 4096,
                                        "details": {"quantization_level": "Q4_0"}}]}}
    if kind == "openai":
        return {"/v1/models": {"data": [{"id": "my-model"}]}}
    return {}


def serve(kind):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            table = routes(kind)
            body = table.get(self.path.split("?")[0])
            if body is None:
                self.send_response(404)
                self.end_headers()
                return
            data = body if isinstance(body, str) else json.dumps(body)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain" if isinstance(body, str) else "application/json")
            self.end_headers()
            self.wfile.write(data.encode())

        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "http://127.0.0.1:%d" % srv.server_address[1]


class EngineTests(unittest.TestCase):
    def check(self, kind):
        srv, base = serve(kind)
        self.addCleanup(srv.shutdown)
        self.assertEqual(engines.detect(base), kind)
        return engines.make_adapter(kind, base)

    def test_prom_parser(self):
        p = engines.parse_prom(VLLM_METRICS % {"p": 1, "g": 2})
        self.assertEqual(engines.psum(p, "vllm:num_requests_running"), 2.0)
        self.assertEqual(p["vllm:prompt_tokens_total"][0][0]["model_name"], "Qwen/Qwen2.5-7B-Instruct")

    def test_llamacpp(self):
        r = self.check("llamacpp").sample()
        self.assertTrue(r["up"])
        self.assertEqual((r["model"], r["context"], r["state"], r["queued"]), ("Qwen3-8B-Q4_K_M", 8192, "generating", 2))
        self.assertEqual(r["decode_tok_s_avg"], 50.0)
        self.assertEqual(r["speed"], "avg")
        self.assertEqual(r["engine_totals"]["output_tokens"], 4500)

    def test_vllm_live_rate(self):
        a = self.check("vllm")
        a.sample()
        import time
        time.sleep(0.2)
        r = a.sample()
        self.assertEqual((r["model"], r["running"], r["queued"], r["context"]), ("Qwen/Qwen2.5-7B-Instruct", 2, 1, 32768))
        self.assertGreater(r["tok_s"], 0)
        self.assertEqual(r["hardware"]["kv_cache_percent"], 37.0)

    def test_lmstudio(self):
        a = self.check("lmstudio")
        busy = a.sample(gpu_util=90)
        self.assertEqual((busy["model"], busy["context"], busy["state"], busy["speed"]),
                         ("qwen2.5-7b-instruct Q4_K_M", 4096, "generating", "none"))
        self.assertEqual(a.sample(gpu_util=3)["state"], "idle")
        self.assertEqual(a.sample(gpu_util=90, other_busy=True)["state"], "idle")   # ComfyUI is the busy one

    def test_ollama(self):
        r = self.check("ollama").sample(gpu_util=5)
        self.assertEqual((r["model"], r["version"], r["state"]), ("llama3:8b Q4_0", "0.5.1", "idle"))
        self.assertEqual(r["hardware"]["vram_used_gib"], 6.0)

    def test_openai_fallback(self):
        r = self.check("openai").sample(gpu_util=0)
        self.assertEqual((r["up"], r["model"]), (True, "my-model"))

    def test_down_and_targets(self):
        self.assertFalse(engines.make_adapter("ollama", "http://127.0.0.1:9").sample()["up"])
        self.assertEqual(engines.parse_targets("lmstudio=host:1234, http://x:8080/", "auto"),
                         [("lmstudio", "http://host:1234"), ("auto", "http://x:8080")])


if __name__ == "__main__":
    unittest.main()
