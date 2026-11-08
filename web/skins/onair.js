/* Эфир: a broadcast lower-third for streamers and screen recordings. A glass bar with a LIVE tag,
   the model like a "now playing" line, the speed as a headline number and an equalizer that
   dances to the real token rate. Add &bg=none to the address for a transparent page (OBS browser source). */
TP.register({
  id: "onair",
  name: "Эфир",
  who: "Стримерам и для записи экрана",
  swatch: ["#0d0b14", "#ff4fa3", "#ffb23d", "#ffffff"],
  fonts: ["https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&display=swap"],
  theme: {
    "--bg": "#0d0b14", "--bg2": "#171326", "--line": "#261f3d", "--line2": "#3b3060",
    "--paper": "#ffffff", "--dim": "#aaa0cb", "--faint": "#5d5483",
    "--out": "#ff4fa3", "--in": "#ffb23d", "--warm": "#ffb23d", "--hot": "#ff4f4f",
    "--num": '"Barlow Condensed","Bahnschrift","Arial Narrow",sans-serif'
  },
  css: `
:root[data-skin="onair"] body{background:radial-gradient(720px 420px at 12% -5%,rgba(255,79,163,.2),transparent 62%),
  radial-gradient(620px 420px at 100% 105%,rgba(255,178,61,.13),transparent 60%),var(--bg)}
:root[data-skin="onair"] body.bgnone{background:transparent}
:root[data-skin="onair"] body::after{opacity:.025}
#sk-onair{padding:4px 12px 14px}
#sk-onair .oa{position:relative;max-width:1120px;margin:0 auto;border-radius:24px;padding:16px 18px 16px 24px;display:grid;gap:12px;
  background:linear-gradient(135deg,rgba(255,255,255,.1),rgba(255,255,255,.025));
  box-shadow:inset 0 0 0 1px rgba(255,255,255,.12),0 24px 70px rgba(0,0,0,.5);backdrop-filter:blur(18px)}
#sk-onair .oa::before{content:"";position:absolute;left:0;top:16px;bottom:16px;width:6px;border-radius:0 5px 5px 0;
  background:linear-gradient(var(--out),var(--in))}
#sk-onair .oa-tag{justify-self:start;font:700 12px var(--mono);letter-spacing:.2em;padding:6px 12px;border-radius:999px;
  background:var(--hot);color:#fff;white-space:nowrap}
#sk-onair .oa-tag.rd{background:var(--in);color:#1b1100}
#sk-onair .oa-tag.idle{background:rgba(255,255,255,.14);color:var(--dim)}
#sk-onair .oa-tag.off{background:var(--faint);color:#fff}
#sk-onair .oa-tag i{display:inline-block;width:8px;height:8px;border-radius:50%;background:currentColor;margin-right:8px;animation:oaP 1.2s ease-in-out infinite}
#sk-onair .oa-tag.idle i,#sk-onair .oa-tag.off i{animation:none;opacity:.5}
@keyframes oaP{50%{opacity:.25}}
#sk-onair .oa-now{min-width:0}
#sk-onair .oa-now small{display:block;font:500 10px var(--mono);letter-spacing:.2em;color:var(--dim);text-transform:uppercase}
#sk-onair .oa-now b{display:block;margin-top:5px;font:700 28px/1.05 var(--num);letter-spacing:.01em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#sk-onair .oa-now em{font:500 12px var(--mono);font-style:normal;color:var(--dim)}
#sk-onair .oa-big{display:flex;align-items:flex-end;gap:12px;min-width:0}
#sk-onair .oa-big .oa-n{font:700 104px/.8 var(--num);letter-spacing:-.01em;background:linear-gradient(95deg,var(--out),var(--in));
  -webkit-background-clip:text;background-clip:text;color:transparent;font-variant-numeric:tabular-nums;min-width:2ch}
#sk-onair .oa-big .oa-n.oa-dead{background:none;color:var(--faint)}
#sk-onair .oa-big .oa-u{font:600 13px var(--mono);letter-spacing:.16em;color:var(--dim);padding-bottom:4px;line-height:1.5}
#sk-onair canvas{display:block;width:100%;height:70px}
#sk-onair .oa-chips{display:flex;flex-wrap:wrap;gap:6px}
#sk-onair .oa-chips span{font:600 13px var(--mono);padding:7px 11px;border-radius:10px;background:rgba(255,255,255,.07);color:var(--paper);white-space:nowrap}
#sk-onair .oa-chips span small{font:500 10px var(--mono);color:var(--dim);letter-spacing:.14em;margin-right:7px}
#sk-onair .oa-chips span.oa-w{color:var(--warm)}#sk-onair .oa-chips span.oa-h{color:var(--hot)}
#sk-onair .oa-day{display:flex;justify-content:space-between;align-items:baseline;gap:12px;border-top:1px solid rgba(255,255,255,.1);padding-top:10px}
#sk-onair .oa-day small{font:500 10px var(--mono);letter-spacing:.2em;color:var(--dim)}
#sk-onair .oa-day b{font:700 34px/1 var(--num);font-variant-numeric:tabular-nums}
@media (min-width:760px){
  #sk-onair .oa{grid-template-columns:auto minmax(0,1.1fr) minmax(220px,1fr) auto;align-items:center;column-gap:26px;padding:16px 26px}
  #sk-onair .oa .oa-rowb{grid-column:1/-1}
  #sk-onair .oa-day{border-top:0;padding:0;flex-direction:column;align-items:flex-end;gap:2px}
  #sk-onair .oa-big .oa-n{font-size:92px}
}
`,
  html: `<div class="oa">
  <div class="oa-tag idle" id="oaTag"><i></i><span>ОЖИДАНИЕ</span></div>
  <div class="oa-now"><small>сейчас запущено</small><b id="oaModel">—</b><em id="oaEng"></em></div>
  <div class="oa-big"><div class="oa-n" id="oaNum">—</div><div class="oa-u" id="oaUnit">ТОК<br>/С</div></div>
  <canvas id="oaEq"></canvas>
  <div class="oa-chips oa-rowb" id="oaChips"></div>
  <div class="oa-day oa-rowb"><small>ТОКЕНОВ СЕГОДНЯ</small><b id="oaDay">—</b></div>
</div>`,

  mount(root, ctx) {
    this.q = id => root.querySelector("#" + id);
    this.cache = {};
    this.eq = this.q("oaEq");
    this.bars = new Float32Array(40);
    this.level = 0; this.mode = "idle";
  },

  update(v, ctx) {
    const { fin, f1, esc } = ctx, q = this.q, S = this.cache;
    const set = (id, t) => { if (S[id] !== t) { q(id).textContent = t; S[id] = t; } };
    const html = (id, h) => { if (S[id] !== h) { q(id).innerHTML = h; S[id] = h; } };
    let mode = "idle", label = "ОЖИДАНИЕ";
    if (v.off) { mode = "off"; label = (v.label || "НЕТ СВЯЗИ").toUpperCase(); }
    else if (v.gen) { mode = "gen"; label = "LIVE · ГЕНЕРАЦИЯ"; }
    else if (v.rd) { mode = "rd"; label = "LIVE · ЧТЕНИЕ"; }
    else if (v.state === "unloaded") label = "МОДЕЛЬ НЕ ЗАГРУЖЕНА";
    this.mode = mode;
    const tag = q("oaTag"), cls = "oa-tag " + (mode === "gen" ? "" : mode === "rd" ? "rd" : mode === "off" ? "off" : "idle");
    if (tag.className !== cls) tag.className = cls;
    const sp = tag.querySelector("span"); if (sp.textContent !== label) sp.textContent = label;

    set("oaModel", v.off ? (v.host || "—") : (v.model || v.engine || "—"));
    set("oaEng", v.off ? (v.url || "") : (v.host + " · " + v.engine + (v.ctx ? " · " + Math.round(v.ctx / 1024) + "K" : "")));
    const none = !v.off && v.speed === "none";
    const n = v.off || none ? "—" : f1(mode === "rd" ? v.pre : v.dec);
    set("oaNum", n); q("oaNum").classList.toggle("oa-dead", v.off || none);
    html("oaUnit", v.off ? "" : none ? "НЕТ ДАННЫХ<br>О СКОРОСТИ" : mode === "rd" ? "ТОК/С<br>ЧТЕНИЕ" : v.speed === "avg" ? "ТОК/С<br>СРЕДНЕЕ" : "ТОК/С");

    if (v.off) { html("oaChips", ""); set("oaDay", "—"); this.level = 0; return; }
    const g = v.gpu, T = v.tempMax;
    const chip = (k, t, c) => `<span class="${c || ""}"><small>${k}</small>${esc(t)}</span>`;
    const chips = [];
    if (fin(g.util)) chips.push(chip("GPU", Math.round(g.util) + "%", g.util >= 97 ? "oa-w" : ""));
    if (fin(g.vu) && g.vt) chips.push(chip("VRAM", g.vu.toFixed(1) + "/" + Math.round(g.vt) + "G", g.vpct >= 92 ? "oa-h" : g.vpct >= 80 ? "oa-w" : ""));
    if (fin(T)) chips.push(chip("T°", Math.round(T) + "°", T >= 80 ? "oa-h" : T >= 68 ? "oa-w" : ""));
    if (fin(g.power)) chips.push(chip("ВТ", Math.round(g.power)));
    if (v.queued) chips.push(chip("ОЧЕРЕДЬ", String(v.queued), "oa-w"));
    html("oaChips", chips.join(""));
    set("oaDay", fin(v.today.total) ? Math.round(v.today.total).toLocaleString("ru-RU") : "—");
    const peak = Math.max(40, ...ctx.hist.dec.slice(-90));
    this.level = mode === "gen" ? Math.min(1, 0.25 + 0.75 * ((v.live || v.dec || 30) / peak)) : mode === "rd" ? 0.7 : 0.05;
  },

  frame(t, v, ctx) {
    const { C } = ctx, [w, h, s] = ctx.fit(this.eq), g = this.eq.getContext("2d");
    g.clearRect(0, 0, w, h);
    const n = this.bars.length, bw = w / n, gap = Math.max(2 * s, bw * 0.28);
    const gr = g.createLinearGradient(0, h, 0, 0); gr.addColorStop(0, C.out); gr.addColorStop(1, C.in);
    for (let i = 0; i < n; i++) {
      let target;
      if (this.mode === "gen") target = this.level * (0.18 + 0.82 * (0.5 + 0.5 * Math.sin(t / 150 + i * 1.7) * Math.sin(t / 290 + i * 0.83 + 1.3)));
      else if (this.mode === "rd") target = 0.12 + 0.8 * Math.pow(0.5 + 0.5 * Math.sin(t / 260 - i * 0.55), 3);
      else target = 0.05 + (this.mode === "off" ? 0 : 0.02 * Math.sin(t / 900 + i));
      this.bars[i] += (target - this.bars[i]) * 0.2;
      const bh = Math.max(3 * s, this.bars[i] * h);
      g.fillStyle = this.mode === "rd" ? C.in : this.mode === "off" ? C.faint : gr;
      g.globalAlpha = this.mode === "idle" || this.mode === "off" ? 0.5 : 1;
      const x = i * bw + gap / 2, r = Math.min((bw - gap) / 2, 4 * s);
      g.beginPath(); g.roundRect ? g.roundRect(x, h - bh, bw - gap, bh, r) : g.rect(x, h - bh, bw - gap, bh); g.fill();
    }
    g.globalAlpha = 1;
  }
});
