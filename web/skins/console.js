/* Консоль: a text terminal for admins and engineers. Everything is monospace characters,
   every number is on screen, nothing animates except the cursor and the sparklines. */
TP.register({
  id: "console",
  name: "Консоль",
  who: "Админам и инженерам",
  swatch: ["#070b08", "#5dff8a", "#7fe8ff", "#9dffb0"],
  fonts: [],
  theme: {
    "--bg": "#070b08", "--bg2": "#0c130e", "--line": "#112017", "--line2": "#1d3a28",
    "--paper": "#9dffb0", "--dim": "#4f9a63", "--faint": "#2a5237",
    "--out": "#5dff8a", "--in": "#7fe8ff", "--warm": "#ffc247", "--hot": "#ff5a45",
    "--mono": '"JetBrains Mono","Cascadia Mono",Consolas,"DejaVu Sans Mono",monospace'
  },
  css: `
#sk-console{min-height:100vh;padding:10px 14px 24px;position:relative}
#sk-console::after{content:"";position:fixed;inset:0;pointer-events:none;z-index:20;
  background:repeating-linear-gradient(0deg,rgba(0,0,0,.22) 0 1px,transparent 1px 3px)}
#sk-console pre{font:500 clamp(10px,3.1vw,15px)/1.5 var(--mono);color:var(--paper);white-space:pre;margin:0 auto;
  width:46ch;max-width:100%;overflow:hidden;text-shadow:0 0 7px color-mix(in srgb,var(--paper) 40%,transparent)}
#sk-console .xg{color:var(--out)}#sk-console .xc{color:var(--in)}#sk-console .xw{color:var(--warm)}
#sk-console .xh{color:var(--hot)}#sk-console .xm{color:var(--dim)}#sk-console .xd{color:var(--faint)}
#sk-console .xb{font-weight:700}
#sk-console .xcur{animation:xblink 1.06s steps(1) infinite}
@keyframes xblink{50%{opacity:0}}
body.bgnone #sk-console::after{display:none}
`,
  html: `<pre id="cnOut" aria-live="off"></pre>`,

  mount(root, ctx) { this.out = root.querySelector("#cnOut"); this.last = ""; },

  update(v, ctx) {
    const { esc, f1, mtok, upt, fin, hist } = ctx;
    const W = 46;
    const X = (c, t) => `<span class="x${c}">${esc(t)}</span>`;
    const rule = X("d", "─".repeat(W));
    const sev = (p) => p >= 90 ? "h" : p >= 75 ? "w" : "g";
    const bar = (p, n, warn) => {
      p = fin(p) ? Math.max(0, Math.min(100, p)) : 0;
      const f = Math.round(p / 100 * n);
      return X(warn === false ? "g" : sev(p), "█".repeat(f)) + X("d", "░".repeat(n - f));
    };
    const spark = (arr, n, c) => {
      const a = arr.slice(-n), mx = Math.max(1, ...a), ch = "▁▂▃▄▅▆▇█";
      return X(c, a.map(x => x > 0 ? ch[Math.min(7, Math.max(0, Math.round(x / mx * 7)))] : "▁").join("").padStart(n, "▁"));
    };
    const num = (x, n, d = 0) => (fin(x) ? x.toFixed(d) : "—").padStart(n);
    const tcls = (t) => !fin(t) ? "m" : t >= 80 ? "h" : t >= 68 ? "w" : "m";
    const L = [];

    if (v.off) {
      L.push(X("b", (v.host || "—").slice(0, W)));
      L.push(X("h", "!! " + String(v.label || "нет связи").toUpperCase()));
      L.push(X("m", (v.url || "").slice(0, W)));
      L.push(rule);
      L.push(X("m", "ждём ответа агента, повтор каждую секунду"));
      L.push(X("m", "[S] серверы  [K] скин  [M] мини"));
      L.push("");
      L.push(X("g", "$ ") + '<span class="xg xcur">█</span>');
      const html = L.join("\n");
      if (html !== this.last) { this.out.innerHTML = html; this.last = html; }
      return;
    }

    const st = { generating: ["GEN", "g"], reading: ["READ", "c"], idle: ["IDLE", "m"], unloaded: ["NOLOAD", "w"] }[v.state] || ["?", "m"];
    const right = "● " + st[0];
    const head = v.host + " · " + v.engine;
    L.push(X("b", head.slice(0, W - right.length - 1).padEnd(W - right.length)) + X(st[1], right));
    L.push(X("m", ((v.model || "—") + " · ctx " + (v.ctx ? Math.round(v.ctx / 1024) + "K" : "—")).slice(0, W)));
    L.push(rule);

    const g = v.gpu, c = v.cpu, r = v.ram;
    const row = (name, pct, tail, warn) => X("m", name.padEnd(5)) + bar(pct, 20, warn) + " " + tail;
    L.push(row("GPU", g.util, X("b", num(g.util, 3) + "%") + X(tcls(g.temp), fin(g.temp) ? " " + String(Math.round(g.temp)).padStart(2) + "°C" : "     ") +
      X("m", fin(g.power) ? " " + String(Math.round(g.power)).padStart(3) + "W" : ""), false));
    L.push(row("VRAM", g.vpct, X("b", num(g.vu, 4, 1)) + X("m", "/" + (g.vt ? g.vt.toFixed(1) : "—") + "G")));
    L.push(row("CPU", c.pct, X("b", num(c.pct, 3) + "%") + X(tcls(c.temp), fin(c.temp) ? " " + String(Math.round(c.temp)).padStart(2) + "°C" : ""), false));
    L.push(row("RAM", r.pct, X("b", num(r.used, 4, 1)) + X("m", "/" + (fin(r.total) ? r.total.toFixed(1) : "—") + "G")));
    if (fin(g.powerLimit) && fin(g.power)) L.push(row("PWR", g.power / g.powerLimit * 100, X("b", num(g.power, 4)) + X("m", "/" + Math.round(g.powerLimit) + "W"), false));
    L.push(rule);

    const unit = v.speed === "avg" ? " avg " : " t/s ";
    L.push(X("m", "DEC  ") + (v.speed === "none" ? X("m", "   n/a") : X("g", f1(v.dec).padStart(6))) + X("m", v.speed === "none" ? "     " : unit) +
      spark(hist.dec, 24, "g"));
    L.push(X("m", "PRE  ") + (v.pre == null ? X("m", "   n/a") : X("c", f1(v.pre).padStart(6))) + X("m", " t/s ") + spark(hist.pre, 24, "c"));
    const p = v.progress || {};
    const act = v.rd && p.total ? "read " + Math.round((p.read || 0) / p.total * 100) + "% " + (p.read || 0) + "/" + p.total
      : v.gen && p.max ? "gen " + (p.generated || p.gen || 0) + "/" + p.max : v.state;
    L.push(X("m", ("run " + (v.running || 0) + " · queue " + v.queued + " · " + act).slice(0, W)));
    if (v.note) L.push(X("w", ("! " + v.note).slice(0, W)));
    L.push(rule);

    const t = v.today, a = v.all;
    L.push(X("m", "TODAY ") + "in " + X("c", mtok(t.prompt)) + "  out " + X("g", mtok(t.output)) + (fin(t.requests) ? X("m", "  " + t.requests + " req") : ""));
    L.push(X("m", "TOTAL ") + X("b", mtok(a.total)) + X("m", fin(a.requests) && a.requests ? "  " + a.requests + " req" : ""));
    L.push(rule);

    L.push(X("m", "REQ  in→out        sec    t/s"));
    if (v.recent.length) {
      v.recent.slice(0, 5).forEach((q, i) => {
        L.push(X("m", String(i + 1).padStart(2) + "   ") + (mtok(q.prompt) + "→" + mtok(q.out)).padEnd(13) +
          (fin(q.duration_s) ? q.duration_s.toFixed(1) : "—").padStart(7) + X("g", f1(q.tok_s).padStart(7)));
      });
    } else L.push(X("d", "  нет данных о запросах у этого движка"));
    L.push(rule);

    const chips = (v.engines || []).map(e => X(e.up ? (e.state === "generating" || e.state === "reading" ? "g" : "m") : "d", (e.up ? "●" : "○") + " " + e.name)).join("  ");
    L.push(X("m", "ENGINES ") + (chips || X("d", "—")));
    const cf = v.comfy;
    if (cf && cf.up) L.push(X("m", "COMFY   ") + "run " + (cf.running || 0) + " · queue " + (cf.pending || 0) + " · vram free " + (fin(cf.vram_free_gib) ? cf.vram_free_gib.toFixed(1) + "G" : "—"));
    const ag = v.agent || {};
    L.push(X("d", ("agent " + (ag.version || "—") + " · ping " + (fin(v.ping) ? Math.round(v.ping) + "ms" : "—") + " · up " + upt(v.uptime)).slice(0, W)));
    L.push("");
    L.push(X("g", "$ ") + '<span class="xg xcur">█</span>');

    const html = L.join("\n");
    if (html !== this.last) { this.out.innerHTML = html; this.last = html; }
  }
});
