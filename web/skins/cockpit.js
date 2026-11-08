/* Приборы: analog instruments for gamers and overclockers. One big speedometer for tokens per
   second, three small dials, warning lamps like a car dashboard, two fuel gauges, a mileage counter. */
TP.register({
  id: "cockpit",
  name: "Приборы",
  who: "Геймерам и оверклокерам",
  swatch: ["#0b0b0d", "#ff7a1a", "#4fd0ff", "#e8edf2"],
  fonts: ["https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;600;700&display=swap"],
  theme: {
    "--bg": "#0b0b0d", "--bg2": "#131316", "--line": "#1d1d22", "--line2": "#2d2d35",
    "--paper": "#e8edf2", "--dim": "#848c98", "--faint": "#464c56",
    "--out": "#ff7a1a", "--in": "#4fd0ff", "--warm": "#ffc247", "--hot": "#ff3b30",
    "--num": '"Rajdhani","Barlow Condensed","Bahnschrift","Arial Narrow",sans-serif'
  },
  css: `
:root[data-skin="cockpit"] body::after{opacity:.03}
#sk-cockpit{min-height:100vh;padding:6px 12px 18px;
  background:repeating-linear-gradient(135deg,rgba(255,255,255,.02) 0 2px,transparent 2px 7px),
    radial-gradient(460px 340px at 50% 22%,rgba(79,208,255,.075),transparent 70%),var(--bg)}
#sk-cockpit .ck-k{max-width:470px;margin:0 auto;display:grid;gap:12px;grid-template-columns:minmax(0,1fr)}
#sk-cockpit .ck-k>*{min-width:0}
#sk-cockpit .ck-lamps{display:grid;grid-template-columns:repeat(6,1fr);gap:5px;padding-right:0}
#sk-cockpit .ck-lamp{font:700 9px var(--mono);letter-spacing:.12em;text-align:center;padding:7px 0 6px;border:1px solid var(--line2);
  border-radius:3px;color:var(--faint);transition:color .25s,border-color .25s,box-shadow .25s,background .25s}
#sk-cockpit .ck-lamp.on{color:var(--lc);border-color:var(--lc);background:color-mix(in srgb,var(--lc) 10%,transparent);
  box-shadow:0 0 14px color-mix(in srgb,var(--lc) 45%,transparent)}
#sk-cockpit canvas{display:block;width:100%}
#sk-cockpit .ck-main{aspect-ratio:1/1}
#sk-cockpit .ck-col{display:contents}
#sk-cockpit .ck-small{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}
#sk-cockpit .ck-small canvas{aspect-ratio:1/1}
#sk-cockpit .ck-fuel{display:grid;grid-template-columns:42px 1fr 78px;align-items:center;gap:10px;font:700 11px var(--mono);color:var(--dim);letter-spacing:.1em}
#sk-cockpit .ck-fuel .ck-tk{position:relative;height:13px;border:1px solid var(--line2);padding:1px;
  background:repeating-linear-gradient(90deg,var(--line) 0 5px,transparent 5px 8px)}
#sk-cockpit .ck-fuel .ck-tk i{display:block;height:100%;width:0;transition:width .7s cubic-bezier(.2,.8,.2,1);
  background:repeating-linear-gradient(90deg,var(--fc,var(--in)) 0 5px,transparent 5px 8px)}
#sk-cockpit .ck-fuel b{text-align:right;font:700 17px var(--num);color:var(--paper);letter-spacing:.02em}
#sk-cockpit .ck-fuel b small{font:500 10px var(--mono);color:var(--dim);margin-left:2px}
#sk-cockpit .ck-trip{display:grid;grid-template-columns:auto 1fr;gap:12px;align-items:end;border-top:1px solid var(--line2);padding-top:10px}
#sk-cockpit .ck-trip .lbl{line-height:1.6}
#sk-cockpit .ck-trip .odo{justify-self:end;font-size:38px;color:var(--in)}
#sk-cockpit .ck-trip .odo .d{background:linear-gradient(var(--bg2),var(--bg) 50%,var(--bg2));border:1px solid var(--line);margin-left:2px;width:.56em}
#sk-cockpit .ck-meta{font:500 10px var(--mono);color:var(--faint);letter-spacing:.06em;display:flex;justify-content:space-between;gap:10px}
#sk-cockpit .ck-meta span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
@media (min-width:860px){
  #sk-cockpit .ck-k{max-width:980px;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);column-gap:26px;align-items:start}
  #sk-cockpit .ck-lamps,#sk-cockpit .ck-trip,#sk-cockpit .ck-meta{grid-column:1/-1}
  #sk-cockpit .ck-col{display:grid;gap:14px;align-content:center;align-self:center}
}
`,
  html: `<div class="ck-k">
  <div class="ck-lamps" id="ckLamps"></div>
  <canvas class="ck-main" id="ckMain"></canvas>
  <div class="ck-col">
    <div class="ck-small"><canvas id="ckGpu"></canvas><canvas id="ckTemp"></canvas><canvas id="ckPwr"></canvas></div>
    <div class="ck-fuel" id="ckVram"><span>VRAM</span><div class="ck-tk"><i></i></div><b>—</b></div>
    <div class="ck-fuel" id="ckRam"><span>RAM</span><div class="ck-tk"><i></i></div><b>—</b></div>
  </div>
  <div class="ck-trip"><span class="lbl">Токенов<br>сегодня</span><div class="odo" id="ckOdo"></div></div>
  <div class="ck-meta"><span id="ckL">—</span><span id="ckR">—</span></div>
</div>`,

  mount(root, ctx) {
    const q = id => root.querySelector("#" + id);
    this.q = q;
    this.cv = { main: q("ckMain"), gpu: q("ckGpu"), temp: q("ckTemp"), pwr: q("ckPwr") };
    this.lampDefs = [["GEN", "out"], ["READ", "in"], ["QUEUE", "warm"], ["HOT", "hot"], ["COMFY", "out"], ["LINK", "in"]];
    q("ckLamps").innerHTML = this.lampDefs.map((l, i) => `<div class="ck-lamp" data-i="${i}">${l[0]}</div>`).join("");
    this.lamps = [...root.querySelectorAll(".ck-lamp")];
    this.t = { tok: 0, max: 40, gpu: 0, temp: 20, pwr: 0, pwrMax: 200, pre: null, speed: "live", off: true, label: "" };
    this.d = { tok: 0, max: 40, gpu: 0, temp: 20, pwr: 0, pwrMax: 200 };
    this.cache = {};
  },

  update(v, ctx) {
    const { fin, f1, C, mtok, upt } = ctx, q = this.q, t = this.t, S = this.cache;
    t.off = !!v.off; t.label = v.label || "";
    if (!v.off) {
      t.speed = v.speed;
      t.tok = v.speed === "none" ? 0 : (v.dec || 0);
      t.pre = v.pre;
      const peak = Math.max(0, ...ctx.hist.dec.slice(-90), t.tok);
      const steps = [20, 40, 60, 80, 100, 150, 200, 300, 500, 1000, 2000];
      t.max = steps.find(s => s >= peak * 1.12) || 2000;
      t.gpu = fin(v.gpu.util) ? v.gpu.util : 0;
      t.temp = fin(v.gpu.temp) ? v.gpu.temp : (fin(v.cpu.temp) ? v.cpu.temp : 20);
      t.hasTemp = fin(v.gpu.temp) || fin(v.cpu.temp);
      t.pwr = fin(v.gpu.power) ? v.gpu.power : 0;
      t.pwrMax = fin(v.gpu.powerLimit) ? Math.ceil(v.gpu.powerLimit / 10) * 10 : 200;
      t.hasPwr = fin(v.gpu.power);
      t.pwrLimit = v.gpu.powerLimit;
    }
    const on = [!v.off && v.gen, !v.off && v.rd, !v.off && v.queued > 0, !v.off && (v.tempMax || 0) >= 80,
      !v.off && v.comfy && v.comfy.up && v.comfy.running > 0, true];
    this.lamps.forEach((el, i) => {
      const [name, col] = this.lampDefs[i];
      el.classList.toggle("on", !!on[i]);
      el.style.setProperty("--lc", C[i === 5 && v.off ? "hot" : col]);
      const txt = i === 5 ? (v.off ? "OFFLINE" : "LINK") : i === 2 && v.queued > 0 ? "Q " + v.queued : name;
      if (el.textContent !== txt) el.textContent = txt;
    });
    const setFuel = (id, pct, label, unit, color) => {
      const el = q(id); el.querySelector("i").style.width = Math.max(0, Math.min(100, pct || 0)) + "%";
      el.querySelector("i").style.setProperty("--fc", color);
      const b = el.querySelector("b"), h = label + "<small>" + unit + "</small>";
      if (S[id] !== h) { b.innerHTML = h; S[id] = h; }
    };
    if (!v.off) {
      const g = v.gpu, r = v.ram;
      setFuel("ckVram", g.vpct, fin(g.vu) ? g.vu.toFixed(1) : "—", fin(g.vt) ? "/" + Math.round(g.vt) + "G" : "", g.vpct >= 92 ? C.hot : g.vpct >= 80 ? C.warm : C.in);
      setFuel("ckRam", r.pct, fin(r.used) ? r.used.toFixed(1) : "—", fin(r.total) ? "/" + Math.round(r.total) + "G" : "", r.pct >= 92 ? C.hot : r.pct >= 80 ? C.warm : C.in);
      ctx.odometer(q("ckOdo"), v.today.total);
      const l = (v.engine || "") + (v.model ? " · " + v.model : "");
      const r2 = "ping " + (fin(v.ping) ? Math.round(v.ping) + "ms" : "—") + " · up " + upt(v.uptime);
      if (S.l !== l) { q("ckL").textContent = l; S.l = l; }
      if (S.r !== r2) { q("ckR").textContent = r2; S.r = r2; }
    } else {
      const l = (v.host || "") + " · " + (v.label || "нет связи");
      if (S.l !== l) { q("ckL").textContent = l; S.l = l; }
      if (S.r !== "") { q("ckR").textContent = ""; S.r = ""; }
    }
  },

  frame(tm, v, ctx) {
    const { C, FONT, fin, f1 } = ctx, t = this.t, d = this.d;
    const k = ctx.fin(d.tok) ? 0.13 : 1;
    ["tok", "gpu", "temp", "pwr"].forEach(n => { d[n] += ((t.off ? (n === "temp" ? 20 : 0) : t[n]) - d[n]) * k; });
    d.max += (t.max - d.max) * 0.08; d.pwrMax = t.pwrMax;
    const off = t.off;
    const major = (min, max) => { const steps = [5, 10, 20, 25, 50, 100, 200, 250, 500]; return steps.find(s => (max - min) / s <= 6) || 500; };

    const dial = (cv, o) => {
      const [w, h, s] = ctx.fit(cv), g = cv.getContext("2d");
      g.clearRect(0, 0, w, h);
      const big = !!o.big, cx = w / 2, cy = h * 0.5;
      const R = Math.min(w / 2, h / 2) - 4 * s;
      const A0 = Math.PI * 0.75, SW = Math.PI * 1.5;
      const ang = val => A0 + SW * Math.max(0, Math.min(1, (val - o.min) / (o.max - o.min)));
      // face + bezel
      const rg = g.createRadialGradient(cx, cy - R * 0.2, R * 0.1, cx, cy, R);
      rg.addColorStop(0, ctx.mix(C.bg, C.paper, 0.1)); rg.addColorStop(1, C.bg);
      g.fillStyle = rg; g.beginPath(); g.arc(cx, cy, R, 0, 7); g.fill();
      g.lineWidth = 3 * s; g.strokeStyle = C.line2; g.beginPath(); g.arc(cx, cy, R, 0, 7); g.stroke();
      g.lineWidth = s; g.strokeStyle = C.line; g.beginPath(); g.arc(cx, cy, R * 0.93, 0, 7); g.stroke();
      // track, red zone, value
      const rt = R * 0.8, lw = (big ? 8 : 6) * s;
      g.lineCap = "butt"; g.lineWidth = lw; g.strokeStyle = C.line;
      g.beginPath(); g.arc(cx, cy, rt, A0, A0 + SW); g.stroke();
      if (o.red != null && o.red < o.max) {
        g.strokeStyle = ctx.rgba(C.hot, 0.5); g.beginPath(); g.arc(cx, cy, rt, ang(o.red), A0 + SW); g.stroke();
      }
      const a1 = ang(o.val);
      if (a1 > A0 + 0.01) {
        g.save(); g.shadowColor = ctx.rgba(o.color, 0.8); g.shadowBlur = 12 * s;
        g.strokeStyle = o.color; g.beginPath(); g.arc(cx, cy, rt, A0, a1); g.stroke(); g.restore();
      }
      // ticks and numbers
      const step = o.step, first = Math.ceil(o.min / step) * step;
      g.textAlign = "center"; g.textBaseline = "middle";
      g.font = `600 ${Math.round((big ? 13 : 10) * s)}px ${FONT.num}`;
      for (let m = first; m <= o.max + 1e-6; m += step) {
        const a = ang(m), c = Math.cos(a), sn = Math.sin(a);
        g.strokeStyle = C.paper; g.lineWidth = 2 * s; g.beginPath();
        g.moveTo(cx + c * R * 0.9, cy + sn * R * 0.9); g.lineTo(cx + c * R * 0.82, cy + sn * R * 0.82); g.stroke();
        if (big || o.labels) { g.fillStyle = C.dim; g.fillText(String(Math.round(m)), cx + c * R * 0.64, cy + sn * R * 0.64); }
        for (let j = 1; j < 4; j++) {
          const mm = m + step * j / 4; if (mm > o.max + 1e-6) break;
          const b = ang(mm), cc = Math.cos(b), ss = Math.sin(b);
          g.strokeStyle = C.faint; g.lineWidth = s; g.beginPath();
          g.moveTo(cx + cc * R * 0.9, cy + ss * R * 0.9); g.lineTo(cx + cc * R * 0.86, cy + ss * R * 0.86); g.stroke();
        }
      }
      // needle
      g.save(); g.translate(cx, cy); g.rotate(a1);
      g.shadowColor = ctx.rgba(o.color, 0.9); g.shadowBlur = 10 * s;
      g.strokeStyle = o.color; g.lineWidth = (big ? 4 : 3) * s; g.lineCap = "round";
      g.beginPath(); g.moveTo(-R * 0.14, 0); g.lineTo(R * 0.76, 0); g.stroke(); g.restore();
      g.fillStyle = C.bg; g.strokeStyle = C.paper; g.lineWidth = 2 * s;
      g.beginPath(); g.arc(cx, cy, R * (big ? 0.07 : 0.085), 0, 7); g.fill(); g.stroke();
      // readout
      g.fillStyle = o.dead ? C.faint : C.paper; g.font = `700 ${Math.round(R * (big ? 0.36 : 0.3))}px ${FONT.num}`;
      g.fillText(o.text, cx, cy + R * (big ? 0.5 : 0.46));
      g.fillStyle = C.dim; g.font = `500 ${Math.round((big ? 10 : 8) * s)}px ${FONT.mono}`;
      if (g.letterSpacing !== undefined) g.letterSpacing = `${s}px`;
      g.fillText(o.label, cx, big ? cy - R * 0.32 : cy + R * 0.82);
      if (g.letterSpacing !== undefined) g.letterSpacing = "0px";
      if (o.sub) { g.fillStyle = o.subColor; g.font = `600 ${Math.round(11 * s)}px ${FONT.num}`; g.fillText(o.sub, cx, cy + R * 0.82); }
    };

    const none = !off && t.speed === "none";
    const sub = off ? t.label.toUpperCase() : none ? "СКОРОСТЬ НЕДОСТУПНА" : (t.pre ? "ЧТЕНИЕ " + f1(t.pre) : "");
    dial(this.cv.main, {
      big: true, min: 0, max: d.max, val: d.tok, step: major(0, d.max), red: null, color: C.out,
      text: off || none ? "—" : f1(d.tok), label: t.speed === "avg" ? "ТОК/С СРЕДНЕЕ" : "ТОК/С", dead: off || none, sub, subColor: off ? C.hot : C.in
    });
    dial(this.cv.gpu, { min: 0, max: 100, val: d.gpu, step: 25, red: 92, color: C.out, text: off ? "—" : Math.round(d.gpu) + "", label: "GPU %", dead: off });
    dial(this.cv.temp, { min: 20, max: 110, val: d.temp, step: 30, red: 85, color: d.temp >= 80 ? C.hot : d.temp >= 68 ? C.warm : C.in, text: off || !t.hasTemp ? "—" : Math.round(d.temp) + "°", label: "ТЕМП", dead: off || !t.hasTemp });
    dial(this.cv.pwr, { min: 0, max: d.pwrMax, val: d.pwr, step: major(0, d.pwrMax), red: t.pwrLimit ? t.pwrLimit * 0.92 : null, color: C.warm, text: off || !t.hasPwr ? "—" : Math.round(d.pwr) + "", label: "ВТ", dead: off || !t.hasPwr });
  }
});
