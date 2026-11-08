/* Эбру — the showpiece skin.
 *
 * The server's work is marbled onto water, the way paper marbling (ebru) is made by hand.
 * Every drop of ink that lands on the bath is a batch of generated tokens; it pushes all earlier
 * ink outward with the exact, area-preserving ink-drop displacement, so the drops of one request
 * build one "stone" of concentric rings. Reading a prompt draws a comb through the bath: the comb's
 * position is the share of the prompt read, and it feathers whatever ink it passes. The bath turns
 * slowly with the GPU load, old ink pales with age, and an unloaded model lets the colour settle.
 * Beside the plate the numbers are set like a book page; on a wide window the whole thing is an
 * open book with the marbled plate on the left page.
 */
(function () {
  "use strict";
  const TAU = Math.PI * 2;
  const MAXD = 132, CAP = 520, SEG2 = 7.5 * 7.5;
  const K_INK = 0, K_PALE = 1, K_INK2 = 2, K_IN = 3, K_INPALE = 4;
  const TOK_PER_DROP = 16, PROMPT_PER_DROP = 800;
  const MQ = typeof matchMedia === "function" ? matchMedia("(prefers-reduced-motion: reduce)") : null;
  const reduced = () => !!(MQ && MQ.matches);
  const clamp = (v, a, b) => v < a ? a : v > b ? b : v;
  const fin = v => typeof v === "number" && isFinite(v);

  /* ------------------------------------------------------------------ state */
  const pool = [];
  for (let i = 0; i < MAXD; i++) pool.push({p: new Float32Array(CAP * 2), n: 0, cx: 0, cy: 0, r: 0, R: 0, born: 0, kind: 0, live: false, grow: false});
  const order = [];                              // live drops, oldest first (drawn in this order)
  const scratch = new Float32Array(CAP * 2);
  const growing = new Float32Array(48 * 3);      // per frame: cx, cy, delta (r2^2 - r1^2)
  const ripples = [];
  for (let i = 0; i < 14; i++) ripples.push({x: 0, y: 0, t: -9, R: 0, a: 0});
  let ripI = 0;

  const S = {
    ready: false, ctx: null, root: null, el: {},
    bath: null, g: null, W: 0, H: 0, k: 1, s: 1, hx: 500, hy: 500,
    base: null, glass: null, sheen: null, dry: null, dirty: true, offDrawn: false, seeded: false,
    ink: null, ig: null, iW: 0, iH: 0, iK: 1,
    last: 0, accG: 0, accR: 0, genRate: 0, readRate: 0, omega: 0, omegaT: 0, veil: 0, veilT: 0,
    nibX: 0, nibY: 0, stoneN: 0, wasBusy: false, wasRd: false,
    comb: {x: -900, v: 0, a: 0, at: 0, dir: -1, prog: 0, on: false},
    beads: 0, beadA: 0, tempK: 0, baseTemp: -1, cullAt: 0, refineTick: 0,
    lastHT: -1, abs: 0, inkMax: 30, preMax: 600,
    sm: null, sm2: null, vm: {off: true}
  };
  const P = {};                                   // palette, read from ctx.C
  const dash = [1, 3];
  const noDash = [];

  /* --------------------------------------------------------------- palette */
  function hex(h) { return [1, 3, 5].map(i => parseInt(h.substr(i, 2), 16)); }
  function mixc(a, b, t) { const A = hex(a), B = hex(b); return "#" + A.map((v, i) => Math.round(v + (B[i] - v) * t).toString(16).padStart(2, "0")).join(""); }
  function readPalette() {
    const C = S.ctx.C;
    if (P.src === C.out + C.bg + C.in) return false;
    P.src = C.out + C.bg + C.in;
    P.bg = C.bg; P.ink = C.paper; P.out = C.out; P.in = C.in; P.warm = C.warm; P.hot = C.hot; P.dim = C.dim; P.line2 = C.line2;
    P.bath = mixc(C.bg, "#ffffff", 0.34);
    P.light = "#fffaf0";
    P.fill = [C.out, mixc(P.bath, "#fffdf7", 0.75), mixc(C.out, P.bath, 0.45), C.in, mixc(mixc(P.bath, "#fffdf7", 0.6), C.in, 0.12)];
    P.rim = [mixc(C.out, "#000000", 0.35), mixc(P.bath, C.out, 0.3), mixc(C.out, "#000000", 0.15), mixc(C.in, "#000000", 0.3), mixc(P.bath, C.in, 0.35)];
    P.sepia = mixc(C.warm, C.paper, 0.45);
    return true;
  }

  /* ---------------------------------------------------------------- drops */
  function freeDrop() {
    if (order.length >= MAXD) { const d = order.shift(); d.live = false; return d; }
    for (let i = 0; i < MAXD; i++) if (!pool[i].live) return pool[i];
    const d = order.shift(); d.live = false; return d;
  }
  function spawn(x, y, R, kind, born, instant) {
    const d = freeDrop();
    d.live = true; d.cx = x; d.cy = y; d.R = R; d.kind = kind; d.born = born; d.r = 0.5; d.n = 36;
    for (let i = 0; i < 36; i++) { const a = i / 36 * TAU; d.p[i * 2] = x + Math.cos(a) * 0.5; d.p[i * 2 + 1] = y + Math.sin(a) * 0.5; }
    order.push(d);
    if (instant) { d.grow = false; growing[0] = x; growing[1] = y; growing[2] = R * R - 0.25; d.r = R; displace(1); refineAll(); }
    else d.grow = true;
    return d;
  }
  // exact marbling: a drop of radius r at c moves every point p to c + (p-c)·sqrt(1 + r²/|p-c|²);
  // growing a drop from r1 to r2 is the same map with r² replaced by r2² - r1². Applied for several drops at once.
  function displace(m) {
    for (let o = 0; o < order.length; o++) {
      const q = order[o], a = q.p, n = q.n * 2;
      for (let i = 0; i < n; i += 2) {
        let x = a[i], y = a[i + 1];
        for (let j = 0; j < m; j++) {
          const cx = growing[j * 3], cy = growing[j * 3 + 1], dx = x - cx, dy = y - cy, dd = dx * dx + dy * dy;
          if (dd < 1e-6) continue;
          const k = Math.sqrt(1 + growing[j * 3 + 2] / dd);
          x = cx + dx * k; y = cy + dy * k;
        }
        a[i] = x; a[i + 1] = y;
      }
    }
  }
  // the bath turns slowly; angular speed falls off with radius, which shears rings into spirals (area-preserving)
  function swirl(w) {
    if (Math.abs(w) < 1e-7) return;
    const inv = 1 / (560 * 560);
    for (let o = 0; o < order.length; o++) {
      const q = order[o], a = q.p, n = q.n * 2;
      for (let i = 0; i < n; i += 2) {
        const x = a[i], y = a[i + 1];
        let f = 1 / (1 + (x * x + y * y) * inv); f *= f;
        const t = w * f, c = 1 - t * t * 0.5;
        a[i] = x * c - y * t; a[i + 1] = x * t + y * c;
      }
    }
  }
  // the comb: a row of tines moving along x; each pin drags the film near it with a viscous,
  // Gaussian falloff (ink right at a pin lags behind it and is drawn out into a feather)
  function combDrag(cx, dx, hy) {
    const T = 9, sx = 1 / (30 * 30), sy = 1 / (24 * 24), reach = 80, y0 = -hy * 0.88, ys = hy * 1.76 / (T - 1);
    for (let o = 0; o < order.length; o++) {
      const q = order[o], a = q.p, n = q.n * 2;
      for (let i = 0; i < n; i += 2) {
        const ddx = a[i] - cx;
        if (ddx > reach || ddx < -reach) continue;
        const y = a[i + 1];
        let j = Math.round((y - y0) / ys); if (j < 0) j = 0; else if (j > T - 1) j = T - 1;
        const dy = y - (y0 + j * ys), e = ddx * ddx * sx + dy * dy * sy;
        if (e > 9) continue;
        a[i] += dx * 0.55 * Math.exp(-e);
      }
    }
  }
  function refine(q) {
    const a = q.p, n = q.n;
    if (n >= CAP) return;
    let m = 0, added = false;
    for (let i = 0; i < n; i++) {
      const j = i + 1 === n ? 0 : i + 1, x0 = a[i * 2], y0 = a[i * 2 + 1], x1 = a[j * 2], y1 = a[j * 2 + 1];
      scratch[m++] = x0; scratch[m++] = y0;
      const dx = x1 - x0, dy = y1 - y0;
      if (dx * dx + dy * dy > SEG2 && m / 2 + (n - i) < CAP) { scratch[m++] = (x0 + x1) * 0.5; scratch[m++] = (y0 + y1) * 0.5; added = true; }
    }
    if (added) { for (let i = 0; i < m; i++) a[i] = scratch[i]; q.n = m / 2; }
  }
  function refineAll() { for (let o = 0; o < order.length; o++) refine(order[o]); }
  function cull() {
    const mx = S.hx + 70, my = S.hy + 70;
    for (let o = order.length - 1; o >= 0; o--) {
      const q = order[o], a = q.p, n = q.n * 2;
      let inside = false;
      for (let i = 0; i < n; i += 2) { const x = a[i], y = a[i + 1]; if (x > -mx && x < mx && y > -my && y < my) { inside = true; break; } }
      if (!inside && !q.grow) { q.live = false; order.splice(o, 1); }
    }
  }
  function ripple(x, y, R, a) {
    const r = ripples[ripI]; ripI = (ripI + 1) % ripples.length;
    r.x = x; r.y = y; r.R = R; r.t = S.last; r.a = a;
  }
  function newStone() {
    const hx = S.hx, hy = S.hy;
    let bx = 0, by = 0, best = -1;
    for (let i = 0; i < 5; i++) {
      const x = (Math.random() * 2 - 1) * hx * 0.5, y = (Math.random() * 2 - 1) * hy * 0.42;
      const d = (x - S.nibX) * (x - S.nibX) + (y - S.nibY) * (y - S.nibY);
      if (d > best) { best = d; bx = x; by = y; }
    }
    S.nibX = bx; S.nibY = by; S.stoneN = 0;
  }
  const STONE = [K_INK, K_PALE, K_INK2, K_PALE];
  function spawnGen(now, rm) {
    const kind = STONE[S.stoneN++ % STONE.length];
    const R = (kind === K_PALE ? 22 : 25) + Math.random() * 9;
    const x = S.nibX + (Math.random() - 0.5) * 12, y = S.nibY + (Math.random() - 0.5) * 12;
    spawn(x, y, R, kind, now, rm);
    if (!rm) ripple(x, y, R, 0.55);
  }
  function spawnRead(now, rm) {
    const c = S.comb, hx = S.hx, hy = S.hy;
    // prompt ink is laid in the path of the comb's pins, so the pins catch it and draw it into feathers
    const ahead = c.on ? c.x + c.dir * (40 + Math.random() * 150) : (Math.random() * 2 - 1) * hx * 0.8;
    const x = clamp(ahead, -hx * 0.94, hx * 0.94), y = tineY(Math.floor(Math.random() * 9), hy) + (Math.random() - 0.5) * 14;
    const kind = Math.random() < 0.6 ? K_IN : K_INPALE;
    spawn(x, y, 8 + Math.random() * 7, kind, now, rm);
    if (!rm) ripple(x, y, 9, 0.3);
  }
  function tineY(j, hy) { return -hy * 0.88 + j * hy * 1.76 / 8; }
  function seed(now) {
    // a quiet, old pattern so the plate is never blank on first open; it pales like any old ink
    const hx = S.hx, hy = S.hy;
    for (let st = 0; st < 6; st++) {
      newStone();
      const cnt = 10 + Math.floor(Math.random() * 12);
      for (let k = 0; k < cnt; k++) {
        const kind = STONE[S.stoneN++ % STONE.length];
        spawn(S.nibX + (Math.random() - 0.5) * 12, S.nibY + (Math.random() - 0.5) * 12, (kind === K_PALE ? 22 : 25) + Math.random() * 9, kind, now - 520 + st * 70 + k, true);
      }
      if (st === 2) {
        for (let k = 0; k < 22; k++) spawn((Math.random() * 2 - 1) * hx * 0.85, tineY(k % 9, hy) + (Math.random() - 0.5) * 12, 8 + Math.random() * 7, Math.random() < 0.6 ? K_IN : K_INPALE, now - 330, true);
        for (let x = -hx - 40; x < hx + 40; x += 12) { combDrag(x, 12, hy); refineAll(); }
      }
    }
    S.stoneN = 0;
  }

  /* ------------------------------------------------------------- sizing */
  function off(w, h) { const c = document.createElement("canvas"); c.width = Math.max(1, w); c.height = Math.max(1, h); return c; }
  function resize() {
    S.dirty = false;
    const r = S.bath.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) { S.W = 0; return; }
    let k = Math.min(devicePixelRatio || 1, 2);
    if (r.width * r.height * k * k > 2.3e6) k = Math.sqrt(2.3e6 / (r.width * r.height));
    const W = Math.round(r.width * k), H = Math.round(r.height * k);
    if (S.bath.width !== W || S.bath.height !== H) { S.bath.width = W; S.bath.height = H; }
    S.W = W; S.H = H; S.k = k; S.s = Math.max(W, H) / 1000; S.hx = W / 2 / S.s; S.hy = H / 2 / S.s;
    readPalette();
    renderBase(); renderGlass(); renderSheen(); renderDry();
    S.offDrawn = false;
    const ir = S.ctx.fit(S.ink); S.iW = ir[0]; S.iH = ir[1]; S.iK = ir[2];
  }
  function renderBase() {
    const W = S.W, H = S.H, c = S.base && S.base.width === W && S.base.height === H ? S.base : (S.base = off(W, H)), g = c.getContext("2d");
    const warm = S.tempK;
    g.globalCompositeOperation = "source-over";
    g.fillStyle = warm > 0 ? mixc(P.bath, P.warm, warm * 0.13) : P.bath; g.fillRect(0, 0, W, H);
    let gr = g.createRadialGradient(W * 0.28, H * 0.16, 0, W * 0.28, H * 0.16, Math.max(W, H) * 1.05);
    gr.addColorStop(0, "rgba(255,252,244,0.55)"); gr.addColorStop(0.55, "rgba(255,252,244,0.08)"); gr.addColorStop(1, "rgba(60,44,20,0.10)");
    g.fillStyle = gr; g.fillRect(0, 0, W, H);
    S.baseTemp = warm;
  }
  function grain(g, W, H, density, k) {
    // paper: fine specks and a few fibres, deterministic so it never crawls
    let s = 1234567;
    const rnd = () => (s = (s * 16807) % 2147483647) / 2147483647;
    g.fillStyle = "#3a2e1e";
    const n = Math.round(W * H / 1e6 * density);
    for (let i = 0; i < n; i++) { g.globalAlpha = 0.02 + rnd() * 0.05; const z = (0.5 + rnd()) * k; g.fillRect(rnd() * W, rnd() * H, z, z); }
    g.strokeStyle = "#3a2e1e"; g.lineWidth = 0.6 * k;
    const f = Math.round(n / 60);
    for (let i = 0; i < f; i++) {
      const x = rnd() * W, y = rnd() * H, a = rnd() * TAU, l = (6 + rnd() * 16) * k;
      g.globalAlpha = 0.025 + rnd() * 0.03; g.beginPath(); g.moveTo(x, y);
      g.quadraticCurveTo(x + Math.cos(a + 0.6) * l * 0.5, y + Math.sin(a + 0.6) * l * 0.5, x + Math.cos(a) * l, y + Math.sin(a) * l); g.stroke();
    }
    g.globalAlpha = 1;
  }
  function renderGlass() {
    const W = S.W, H = S.H, k = S.k, c = S.glass && S.glass.width === W && S.glass.height === H ? S.glass : (S.glass = off(W, H)), g = c.getContext("2d");
    g.clearRect(0, 0, W, H);
    grain(g, W, H, 9000, k);
    // the bath is sunk into the page: shade along the edges, light on the far lip
    const e = 16 * k;
    let gr = g.createLinearGradient(0, 0, 0, e); gr.addColorStop(0, "rgba(40,30,16,0.16)"); gr.addColorStop(1, "rgba(40,30,16,0)"); g.fillStyle = gr; g.fillRect(0, 0, W, e);
    gr = g.createLinearGradient(0, 0, e, 0); gr.addColorStop(0, "rgba(40,30,16,0.10)"); gr.addColorStop(1, "rgba(40,30,16,0)"); g.fillStyle = gr; g.fillRect(0, 0, e, H);
    gr = g.createLinearGradient(W, 0, W - e * 0.6, 0); gr.addColorStop(0, "rgba(40,30,16,0.06)"); gr.addColorStop(1, "rgba(40,30,16,0)"); g.fillStyle = gr; g.fillRect(W - e, 0, e, H);
    gr = g.createLinearGradient(0, H, 0, H - e * 0.5); gr.addColorStop(0, "rgba(255,250,238,0.5)"); gr.addColorStop(1, "rgba(255,250,238,0)"); g.fillStyle = gr; g.fillRect(0, H - e, W, e);
  }
  function renderSheen() {
    const W = S.W, H = S.H, c = S.sheen && S.sheen.width === W * 2 && S.sheen.height === H ? S.sheen : (S.sheen = off(W * 2, H)), g = c.getContext("2d");
    g.clearRect(0, 0, W * 2, H);
    g.save(); g.translate(W, H / 2); g.transform(1, 0, -0.55, 1, 0, 0);
    const bw = Math.max(W, H) * 0.34;
    const gr = g.createLinearGradient(-bw, 0, bw, 0);
    gr.addColorStop(0, "rgba(255,253,246,0)"); gr.addColorStop(0.42, "rgba(255,253,246,0.10)"); gr.addColorStop(0.5, "rgba(255,253,246,0.17)");
    gr.addColorStop(0.58, "rgba(255,253,246,0.10)"); gr.addColorStop(1, "rgba(255,253,246,0)");
    g.fillStyle = gr; g.fillRect(-bw, -H, bw * 2, H * 2); g.restore();
  }
  function renderDry() {
    // no connection: the bath has dried; only a tide-mark of the last drop is left on the paper
    const W = S.W, H = S.H, k = S.k, c = S.dry && S.dry.width === W && S.dry.height === H ? S.dry : (S.dry = off(W, H)), g = c.getContext("2d");
    g.globalAlpha = 1; g.fillStyle = mixc(P.bg, "#ffffff", 0.16); g.fillRect(0, 0, W, H);
    const rings = [[0.42, 0.46, 0.2, 1.7], [0.63, 0.6, 0.09, 4.1]];
    for (const [fx, fy, fr, ph] of rings) {
      const cx = W * fx, cy = H * fy, R = Math.min(W, H) * fr * 1.6;
      for (let L = 0; L < 26; L++) {
        const rr = R - L * 0.55 * k;
        g.globalAlpha = L === 0 ? 0.32 : 0.15 * Math.exp(-L / 6);
        g.strokeStyle = P.sepia; g.lineWidth = (L === 0 ? 1.4 : 0.8) * k;
        g.beginPath();
        for (let i = 0; i <= 160; i++) {
          const a = i / 160 * TAU, w = rr + Math.sin(a * 3 + ph) * 2.6 * k + Math.sin(a * 7 + ph * 2) * 1.3 * k + Math.sin(a * 13 + ph) * 0.6 * k;
          const x = cx + Math.cos(a) * w, y = cy + Math.sin(a) * w;
          i ? g.lineTo(x, y) : g.moveTo(x, y);
        }
        g.stroke();
      }
    }
    g.globalAlpha = 1;
    g.drawImage(S.glass, 0, 0);
  }

  /* ------------------------------------------------------------ simulate */
  function simulate(now, dt) {
    const rm = reduced();
    if (!S.seeded) { S.seeded = true; seed(now); }
    if (S.genRate > 0) { S.accG += S.genRate * dt; let c = 0; while (S.accG >= 1 && c++ < 4) { S.accG -= 1; spawnGen(now, rm); } } else S.accG = 0.6;
    if (S.readRate > 0) { S.accR += S.readRate * dt; let c = 0; while (S.accR >= 1 && c++ < 4) { S.accR -= 1; spawnRead(now, rm); } } else S.accR = 0.5;
    // ink spreads like a diffusing film: fast at first, then settling (r ~ sqrt(1 - e^(-t/τ)))
    let m = 0;
    for (let o = 0; o < order.length && m < 48; o++) {
      const q = order[o];
      if (!q.grow) continue;
      const f = 1 - Math.exp(-(now - q.born) / 0.38);
      let r = q.R * Math.sqrt(f);
      if (f > 0.996) { r = q.R; q.grow = false; }
      if (r > q.r) { growing[m * 3] = q.cx; growing[m * 3 + 1] = q.cy; growing[m * 3 + 2] = r * r - q.r * q.r; q.r = r; m++; }
    }
    if (m) displace(m);
    S.omega += (S.omegaT - S.omega) * Math.min(1, dt * 0.7);
    if (!rm) swirl(S.omega * dt);
    // comb on a damped spring: heavy, it overshoots a hair and settles
    const c = S.comb, hx = S.hx;
    const span = hx * 0.94, tx = c.on ? (c.dir > 0 ? -span + c.prog * 2 * span : span - c.prog * 2 * span) : (c.dir > 0 ? hx + 120 : -hx - 120);
    const x0 = c.x;
    if (rm) { c.x = tx; c.v = 0; }
    else { const kk = 7.5, dd = 2 * Math.sqrt(kk) * 0.82; c.v += (kk * (tx - c.x) - dd * c.v) * dt; c.v = clamp(c.v, -700, 700); c.x += c.v * dt; }
    c.a += ((c.on ? 1 : 0) - c.a) * Math.min(1, dt * (c.on ? 4 : 1.6));
    if (c.a > 0.25 && Math.abs(c.x - x0) > 0.01) combDrag(c.x, c.x - x0, S.hy);
    if (++S.refineTick % 2 === 0 || m) refineAll();
    if (now - S.cullAt > 1.2) { S.cullAt = now; cull(); }
    S.veil += (S.veilT - S.veil) * Math.min(1, dt * 0.5);
  }

  /* ---------------------------------------------------------------- draw */
  function tracePath(g, q) {
    const a = q.p, n = q.n;
    let px = a[(n - 1) * 2], py = a[(n - 1) * 2 + 1];
    g.moveTo((px + a[0]) * 0.5, (py + a[1]) * 0.5);
    for (let i = 0; i < n; i++) {
      const x = a[i * 2], y = a[i * 2 + 1], j = i + 1 === n ? 0 : i + 1;
      g.quadraticCurveTo(x, y, (x + a[j * 2]) * 0.5, (y + a[j * 2 + 1]) * 0.5);
    }
    g.closePath();
  }
  function drawBath(now, dt, vm) {
    const g = S.g, W = S.W, H = S.H;
    if (!W) return;
    if (vm.off) {
      if (!S.offDrawn) { g.setTransform(1, 0, 0, 1, 0, 0); g.globalAlpha = 1; g.drawImage(S.dry, 0, 0); S.offDrawn = true; }
      return;
    }
    S.offDrawn = false;
    simulate(now, dt);
    const tk = clamp(((vm.gpu && vm.gpu.temp) || 40) - 50, 0, 40) / 40;
    S.tempK += (tk - S.tempK) * Math.min(1, dt * 0.3);
    if (Math.abs(S.tempK - S.baseTemp) > 0.04) renderBase();

    const s = S.s, k = S.k;
    g.setTransform(1, 0, 0, 1, 0, 0); g.globalAlpha = 1; g.globalCompositeOperation = "source-over";
    g.drawImage(S.base, 0, 0);
    g.setTransform(s, 0, 0, s, W / 2, H / 2);
    g.lineJoin = "round";
    const rimW = 0.9 * k / s;
    for (let o = 0; o < order.length; o++) {
      const q = order[o], age = now - q.born;
      const life = 0.3 + 0.68 * Math.exp(-Math.max(0, age) / 260);
      g.beginPath(); tracePath(g, q);
      g.globalAlpha = life * (q.kind === K_PALE || q.kind === K_INPALE ? 1 : 0.94);
      g.fillStyle = P.fill[q.kind]; g.fill();
      g.globalAlpha = life * 0.42; g.strokeStyle = P.rim[q.kind]; g.lineWidth = rimW; g.stroke();
    }
    // ripples on the surface where a drop lands
    g.strokeStyle = P.light;
    for (let i = 0; i < ripples.length; i++) {
      const r = ripples[i], age = now - r.t;
      if (age < 0 || age > 1.7) continue;
      const f = 1 - age / 1.7;
      g.globalAlpha = r.a * f * f; g.lineWidth = (1.6 * f + 0.4) * k / s;
      g.beginPath(); g.arc(r.x, r.y, r.R + 150 * Math.sqrt(age), 0, TAU); g.stroke();
      g.globalAlpha = r.a * 0.45 * f * f * f;
      g.beginPath(); g.arc(r.x, r.y, r.R * 0.6 + 90 * Math.sqrt(age), 0, TAU); g.stroke();
    }
    g.setTransform(1, 0, 0, 1, 0, 0);
    if (S.veil > 0.01) { g.globalAlpha = S.veil; g.fillStyle = P.bath; g.fillRect(0, 0, W, H); }
    // a slow band of light drifts over the water
    const sh = reduced() ? 0.5 : 0.5 + 0.32 * Math.sin(now / 11) + 0.08 * Math.sin(now / 4.3);
    g.globalAlpha = 1; g.drawImage(S.sheen, -W * sh, 0);
    drawComb(g, now);
    g.globalAlpha = 1; g.drawImage(S.glass, 0, 0);
    drawBeads(g, now);
  }
  function drawComb(g, now) {
    const c = S.comb;
    if (c.a < 0.02) return;
    const W = S.W, H = S.H, k = S.k, s = S.s, X = W / 2 + c.x * s;
    if (X < -20 * k || X > W + 20 * k) return;
    const T = 9, y0 = -S.hy * 0.88, ys = S.hy * 1.76 / (T - 1), lean = clamp(-c.v * 0.004, -0.25, 0.25);
    // shadow on the water
    g.globalAlpha = 0.13 * c.a; g.strokeStyle = "#2a1f10"; g.lineWidth = 3.2 * k;
    g.beginPath(); g.moveTo(X + 5 * k, 0); g.lineTo(X + 5 * k + lean * H * 0.1, H); g.stroke();
    // wakes behind each tine
    g.strokeStyle = P.light; g.lineWidth = 0.9 * k;
    const back = -c.dir * 16 * k * clamp(Math.abs(c.v) / 60, 0.25, 1.4);
    for (let j = 0; j < T; j++) {
      const y = H / 2 + (y0 + j * ys) * s;
      g.globalAlpha = 0.5 * c.a;
      g.beginPath(); g.moveTo(X + back, y - 6 * k); g.lineTo(X, y); g.lineTo(X + back, y + 6 * k); g.stroke();
    }
    // the brass rod and its pins
    g.globalAlpha = 0.85 * c.a; g.strokeStyle = mixc(P.warm, P.ink, 0.55); g.lineWidth = 1.5 * k;
    g.beginPath(); g.moveTo(X, -2); g.lineTo(X, H + 2); g.stroke();
    g.fillStyle = P.ink;
    for (let j = 0; j < T; j++) {
      const y = H / 2 + (y0 + j * ys) * s;
      g.globalAlpha = 0.9 * c.a; g.beginPath(); g.arc(X, y, 1.9 * k, 0, TAU); g.fill();
    }
    g.globalAlpha = 1;
  }
  function drawBeads(g, now) {
    // requests waiting: ink beads hanging from the rim of the bath, swinging like pendulums
    S.beadA += ((S.beads > 0 ? 1 : 0) - S.beadA) * 0.08;
    if (S.beadA < 0.02 || S.beads <= 0) return;
    const k = S.k, n = Math.min(S.beads, 7), rm = reduced();
    g.fillStyle = P.out;
    for (let i = 0; i < n; i++) {
      const x = (16 + i * 13) * k, y = 0, a = rm ? 0 : Math.sin(now * 2.1 + i * 1.3) * 0.12;
      const ca = Math.cos(a), sa = Math.sin(a);
      g.setTransform(ca * k, sa * k, -sa * k, ca * k, x, y);
      g.globalAlpha = 0.9 * S.beadA;
      g.beginPath(); g.moveTo(0, 0);
      g.bezierCurveTo(-1.2, 4, -4, 6, -4, 9); g.arc(0, 9, 4, Math.PI, 0, true); g.bezierCurveTo(4, 6, 1.2, 4, 0, 0); g.fill();
      g.globalAlpha = 0.6 * S.beadA; g.fillStyle = P.light; g.beginPath(); g.arc(-1.4, 8.2, 1.1, 0, TAU); g.fill(); g.fillStyle = P.out;
    }
    g.setTransform(1, 0, 0, 1, 0, 0); g.globalAlpha = 1;
  }
  function hash(n) { n = (n ^ 61) ^ (n >>> 16); n = n + (n << 3); n = n ^ (n >>> 4); n = Math.imul(n, 0x27d4eb2d); n = n ^ (n >>> 15); return (n >>> 0) / 4294967296; }
  function drawInk(vm) {
    // the brush line: 150 seconds of speed written as one stroke; its width is tokens per second
    const g = S.ig, W = S.iW, H = S.iH, k = S.iK, hist = S.ctx.hist;
    if (!W || !hist) return;
    const N = hist.dec.length;
    if (!S.sm || S.sm.length !== N) { S.sm = new Float32Array(N); S.sm2 = new Float32Array(N); }
    if (hist.t !== S.lastHT) { S.lastHT = hist.t; S.abs++; }
    const frac = reduced() ? 0 : clamp((performance.now() - hist.t) / 1000, 0, 1);
    g.setTransform(1, 0, 0, 1, 0, 0); g.clearRect(0, 0, W, H);
    const mid = Math.round(H * 0.46) + 0.5, step = W / (N - 2), d = hist.dec, p = hist.pre;
    let mx = 0, mp = 0;
    for (let i = 0; i < N; i++) { const a = d[i - 1] || d[i], b = d[i + 1] || d[i]; S.sm[i] = (a + 2 * d[i] + b) / 4; if (d[i] > mx) mx = d[i];
      const pa = p[i - 1] || p[i], pb = p[i + 1] || p[i]; S.sm2[i] = (pa + 2 * p[i] + pb) / 4; if (p[i] > mp) mp = p[i]; }
    S.inkMax += (Math.max(20, mx * 1.08) - S.inkMax) * 0.05; S.preMax += (Math.max(200, mp * 1.08) - S.preMax) * 0.05;
    // hairline and 30-second ticks that travel with the stroke
    g.globalAlpha = 1; g.strokeStyle = P.line2; g.lineWidth = k; g.setLineDash(dash);
    g.beginPath(); g.moveTo(0, mid); g.lineTo(W, mid); g.stroke(); g.setLineDash(noDash);
    g.lineWidth = k; g.strokeStyle = P.dim; g.globalAlpha = 0.55;
    g.beginPath();
    for (let i = 0; i < N; i++) {
      if ((S.abs - (N - 1 - i)) % 30 !== 0) continue;
      const x = Math.round(W - (N - 1 - i + frac) * step) + 0.5;
      g.moveTo(x, H - 5 * k); g.lineTo(x, H - 1);
    }
    g.stroke();
    ribbon(g, S.sm2, S.preMax, W, H, mid, step, frac, N, P.in, k, 0.36);
    ribbon(g, S.sm, S.inkMax, W, H, mid, step, frac, N, P.out, k, 1);
    bristles(g, S.sm2, S.preMax * 2.78, W, H, mid, step, frac, N, k, 3);
    bristles(g, S.sm, S.inkMax, W, H, mid, step, frac, N, k, 5);
    // the brush tip, wet, at "now"
    if (vm.gen || vm.rd) {
      const v = vm.rd ? S.sm2[N - 1] / S.preMax * 0.36 : S.sm[N - 1] / S.inkMax, hw = Math.max(2 * k, v * H * 0.4);
      g.globalAlpha = 0.9; g.fillStyle = vm.rd ? P.in : P.out;
      g.beginPath(); g.ellipse(W - frac * step - 1.5 * k, mid - hw * 0.1, 2.2 * k, hw * 0.9, 0, 0, TAU); g.fill();
    }
    g.globalAlpha = 1;
  }
  // dry-brush: bristles leave paper showing through, fixed to the stroke so they scroll with it
  function bristles(g, sm, max, W, H, mid, step, frac, N, k, nb) {
    g.strokeStyle = P.bg; g.lineWidth = 0.75 * k; g.globalAlpha = 0.55;
    for (let b = 0; b < nb; b++) {
      const o = (b - (nb - 1) / 2) / (nb * 0.54);
      g.beginPath();
      let pen = false;
      for (let i = 1; i < N; i++) {
        const hw = sm[i] / max * H * 0.4;
        const on = hw > 2.2 * k && hash(((S.abs - (N - 1 - i)) >> 1) * 7 + b * 131 + nb) > 0.58;
        const x = W - (N - 1 - i + frac) * step, y = mid + o * (o < 0 ? hw : hw * 0.8);
        if (on) { pen ? g.lineTo(x, y) : g.moveTo(x, y); pen = true; } else pen = false;
      }
      g.stroke();
    }
  }
  function ribbon(g, sm, max, W, H, mid, step, frac, N, col, k, wmul) {
    let any = false;
    for (let i = 0; i < N; i++) if (sm[i] > 0.01) { any = true; break; }
    if (!any) return;
    g.fillStyle = col; g.globalAlpha = 0.9;
    g.beginPath();
    for (let i = 0; i < N; i++) {
      const hw = sm[i] / max * H * 0.4 * wmul, wob = (hash(S.abs - (N - 1 - i)) - 0.5) * 0.7 * k;
      const x = W - (N - 1 - i + frac) * step, y = mid - hw + wob;
      i ? g.lineTo(x, y) : g.moveTo(x, y);
    }
    for (let i = N - 1; i >= 0; i--) {
      const hw = sm[i] / max * H * 0.4 * wmul, wob = (hash(S.abs - (N - 1 - i) + 9) - 0.5) * 0.7 * k;
      g.lineTo(W - (N - 1 - i + frac) * step, mid + hw * 0.8 + wob);
    }
    g.closePath(); g.fill();
  }

  /* --------------------------------------------------------------- text */
  const NB = " ";
  const f1 = v => !fin(v) ? "—" : v >= 100 ? String(Math.round(v)) : v.toFixed(1).replace(".", ",");
  const grp = n => !fin(n) ? "—" : String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, NB);
  const mt = n => S.ctx.mtok(n).replace(".", ",");
  function set(el, v) { v = v == null ? "" : String(v); if (el.textContent !== v) el.textContent = v; }
  function setMeter(id, val, unit, sub, pct, col, hot) {
    const m = S.el[id];
    set(m.v, val); set(m.u, unit); set(m.s, sub);
    const p = fin(pct) ? clamp(pct, 0, 100) : 0;
    const lp = p.toFixed(1) + "%";
    if (m.mk.style.left !== lp) { m.mk.style.left = lp; m.fl.style.transform = "scaleX(" + (p / 100).toFixed(3) + ")"; }
    m.root.classList.toggle("aurora-none", !fin(pct));
    const c = col || "";
    if (m.dot.style.background !== c) m.dot.style.background = c;
    m.root.classList.toggle("aurora-hot", !!hot);
  }
  const STATE = {generating: "Генерация", reading: "Чтение промпта", idle: "Ожидание", unloaded: "Модель выгружена"};

  TP.register({
    id: "aurora",
    name: "Эбру",
    who: "Мысль чернилами по воде",
    swatch: ["#e8e0cf", "#283a74", "#2f7a70", "#1f1c18"],
    fonts: ["https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,500;0,600;1,400;1,500&family=IBM+Plex+Mono:wght@400;500&display=swap"],
    theme: {
      "--bg": "#e8e0cf", "--bg2": "#ded5c1", "--line": "#d2c7b0", "--line2": "#b9ab90",
      "--paper": "#1f1c18", "--dim": "#6c6355", "--faint": "#9d927c",
      "--out": "#283a74", "--in": "#2f7a70", "--warm": "#b5791a", "--hot": "#b1381f",
      "--num": "\"Cormorant Garamond\",\"EB Garamond\",Garamond,\"Times New Roman\",serif",
      "--ui": "\"Cormorant Garamond\",\"EB Garamond\",Garamond,\"Times New Roman\",serif",
      "--mono": "\"IBM Plex Mono\",\"JetBrains Mono\",Consolas,\"DejaVu Sans Mono\",monospace"
    },
    css: `
#sk-aurora{--serif:"Cormorant Garamond","EB Garamond",Garamond,"Times New Roman",serif;--pm:"IBM Plex Mono","JetBrains Mono",Consolas,"DejaVu Sans Mono",monospace;
  min-height:100vh;color:var(--paper);color-scheme:light;font:12px/1.4 var(--pm);
  background:var(--grain,none),radial-gradient(120% 70% at 22% 0%,#f3eddf 0%,rgba(243,237,223,0) 60%),radial-gradient(90% 60% at 100% 100%,#d9cfba 0%,rgba(217,207,186,0) 70%),var(--bg);
  background-size:220px 220px,auto,auto,auto}
#sk-aurora *{box-sizing:border-box}
#sk-aurora .aurora-bk{position:relative;max-width:1180px;margin:0 auto;padding:calc(20px - var(--aurora-top,0px) * .45) 16px 18px;display:grid;grid-template-columns:minmax(0,1fr);
  grid-template-areas:"hd" "pl" "hero" "ink" "met" "tok" "ft";row-gap:0}
#sk-aurora .aurora-lb{font:500 8.5px/1 var(--pm);letter-spacing:.2em;text-transform:uppercase;color:var(--dim)}
/* header */
#sk-aurora .aurora-hd{grid-area:hd;min-width:0}
#sk-aurora .aurora-meta{padding-right:var(--aurora-dock,104px);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font:500 9px/14px var(--pm);letter-spacing:.18em;text-transform:uppercase;color:var(--dim)}
#sk-aurora .aurora-meta b{font-weight:500;color:var(--paper)}
#sk-aurora .aurora-st{margin:9px 0 0;font:italic 500 35px/1 var(--serif);letter-spacing:-.005em;color:var(--paper);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;transition:color .8s}
#sk-aurora .aurora-st small{font:500 9px/1 var(--pm);letter-spacing:.16em;text-transform:uppercase;color:var(--warm);margin-left:10px;vertical-align:.95em;font-style:normal}
#sk-aurora .aurora-model{margin-top:7px;font:400 10.5px/1.3 var(--pm);color:var(--paper);opacity:.78;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#sk-aurora .aurora-model em{font-style:normal;color:var(--dim)}
/* plate */
#sk-aurora .aurora-pl{grid-area:pl;margin:15px 0 0;min-width:0;display:flex;flex-direction:column}
#sk-aurora .aurora-bath{position:relative;height:232px;box-shadow:0 0 0 1px var(--line2),0 0 0 4px var(--bg),0 0 0 4.6px var(--line2),0 14px 22px -16px rgba(60,40,10,.45)}
#sk-aurora .aurora-bath canvas{position:absolute;inset:0;width:100%;height:100%;display:block}
#sk-aurora .aurora-reg{position:absolute;width:9px;height:9px;pointer-events:none}
#sk-aurora .aurora-reg::before,#sk-aurora .aurora-reg::after{content:"";position:absolute;background:var(--faint)}
#sk-aurora .aurora-reg::before{left:4px;top:0;width:1px;height:9px}#sk-aurora .aurora-reg::after{top:4px;left:0;height:1px;width:9px}
#sk-aurora .aurora-r1{left:-14px;top:-14px}#sk-aurora .aurora-r2{right:-14px;top:-14px}#sk-aurora .aurora-r3{left:-14px;bottom:-14px}#sk-aurora .aurora-r4{right:-14px;bottom:-14px}
#sk-aurora figcaption{display:flex;align-items:baseline;gap:8px;margin-top:11px;min-width:0}
#sk-aurora .aurora-fig{font:italic 500 14px/1 var(--serif);color:var(--dim)}
#sk-aurora .aurora-cap{flex:1;min-width:0;font:italic 400 14.5px/1.15 var(--serif);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#sk-aurora .aurora-key{flex:none;font:400 8.5px/1 var(--pm);letter-spacing:.08em;color:var(--dim);white-space:nowrap}
#sk-aurora .aurora-prog{position:relative;height:1px;margin-top:7px;background:var(--line)}
#sk-aurora .aurora-prog i{position:absolute;left:0;top:-.5px;height:2px;width:100%;transform-origin:0 50%;transform:scaleX(0);background:var(--out);transition:transform 1s cubic-bezier(.22,.8,.3,1),background .6s}
/* hero number */
#sk-aurora .aurora-hero{grid-area:hero;margin-top:15px;display:grid;grid-template-columns:auto minmax(0,1fr);align-items:end;column-gap:12px}
#sk-aurora .aurora-n{font:500 80px/.8 var(--serif);letter-spacing:-.03em;font-variant-numeric:lining-nums tabular-nums;color:var(--out);transition:color .8s;white-space:nowrap}
#sk-aurora .aurora-n.aurora-rest{color:var(--paper)}
#sk-aurora .aurora-n.aurora-nil{font-size:46px;font-weight:400;color:var(--faint);transform:translateY(-14px)}
#sk-aurora .aurora-n.aurora-in{color:var(--in)}
#sk-aurora .aurora-hu{padding-bottom:4px;min-width:0}
#sk-aurora .aurora-u{font:italic 500 22px/1 var(--serif);color:var(--paper)}
#sk-aurora .aurora-q{margin-top:6px;font:400 9.5px/1.35 var(--pm);color:var(--dim)}
#sk-aurora .aurora-q b{font-weight:500;color:var(--paper)}
#sk-aurora .aurora-alt{margin-top:3px;font:400 9.5px/1.35 var(--pm);color:var(--dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#sk-aurora .aurora-alt b{font-weight:500}
/* brush line */
#sk-aurora .aurora-ink{grid-area:ink;margin-top:15px}
#sk-aurora .aurora-ih{display:flex;justify-content:space-between;align-items:baseline}
#sk-aurora .aurora-ink canvas{display:block;width:100%;height:40px;margin-top:5px}
#sk-aurora .aurora-ax{display:flex;justify-content:space-between;margin-top:3px;font:italic 400 11.5px/1 var(--serif);color:var(--dim)}
/* meters */
#sk-aurora .aurora-met{grid-area:met;margin-top:12px;display:grid;grid-template-columns:1fr 1fr;column-gap:22px;row-gap:11px;padding-top:11px;border-top:1px solid var(--line)}
#sk-aurora .aurora-m{min-width:0}
#sk-aurora .aurora-mv{margin-top:5px;display:flex;align-items:baseline;gap:5px;white-space:nowrap}
#sk-aurora .aurora-mv b{font:500 29px/.9 var(--serif);font-variant-numeric:lining-nums tabular-nums;letter-spacing:-.01em}
#sk-aurora .aurora-mv i{font:italic 500 14px/1 var(--serif);color:var(--dim)}
#sk-aurora .aurora-m.aurora-hot .aurora-mv b{color:var(--hot)}
#sk-aurora .aurora-mh{display:flex;justify-content:space-between;align-items:baseline;gap:6px;min-width:0}
#sk-aurora .aurora-ms{min-width:0;font:400 8.5px/1 var(--pm);color:var(--dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#sk-aurora .aurora-rule{position:relative;height:7px;margin-top:7px;background:repeating-linear-gradient(90deg,var(--line2) 0 1px,transparent 1px 10%) 0 100%/100% 3px no-repeat,linear-gradient(var(--line2),var(--line2)) 0 100%/100% 1px no-repeat}
#sk-aurora .aurora-rule .aurora-fl{position:absolute;left:0;right:0;bottom:0;height:1px;background:var(--paper);opacity:.7;transform-origin:0 50%;transform:scaleX(0);transition:transform 1.4s cubic-bezier(.2,.9,.25,1.06)}
#sk-aurora .aurora-rule .aurora-mk{position:absolute;left:0;width:0;top:0;bottom:0;transition:left 1.4s cubic-bezier(.2,.9,.25,1.06)}
#sk-aurora .aurora-rule .aurora-mk b{position:absolute;left:-3.5px;bottom:-3px;width:7px;height:7px;border-radius:50%;background:var(--paper);box-shadow:0 0 0 2px var(--bg)}
#sk-aurora .aurora-m.aurora-none .aurora-rule .aurora-mk,#sk-aurora .aurora-m.aurora-none .aurora-rule .aurora-fl{opacity:0}
/* tokens */
#sk-aurora .aurora-tok{grid-area:tok;margin-top:12px;padding-top:11px;border-top:1px solid var(--line);display:grid;grid-template-columns:minmax(0,1fr) auto;column-gap:12px;align-items:end}
#sk-aurora .aurora-tn{margin-top:6px;font:500 30px/.95 var(--serif);font-variant-numeric:lining-nums tabular-nums;white-space:nowrap}
#sk-aurora .aurora-tn i{font:italic 500 15px/1 var(--serif);color:var(--dim);margin-left:4px}
#sk-aurora .aurora-ts{margin-top:5px;font:400 9px/1.3 var(--pm);color:var(--dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#sk-aurora .aurora-ts b{font-weight:500}
#sk-aurora .aurora-ta{text-align:right;font:400 9px/1.4 var(--pm);color:var(--dim)}
#sk-aurora .aurora-ta b{display:block;font:italic 500 17px/1 var(--serif);color:var(--paper);margin-top:4px}
/* footer, set like a colophon */
#sk-aurora .aurora-ft{grid-area:ft;margin-top:14px;padding-top:9px;border-top:1px solid var(--line);font:400 9px/1.55 var(--pm);color:var(--dim)}
#sk-aurora .aurora-ft b{font-weight:500;color:var(--paper)}
#sk-aurora .aurora-ft .aurora-cf{display:block}
#sk-aurora .aurora-fo{display:block;text-align:center;margin-top:8px;font:italic 400 12px/1 var(--serif);color:var(--faint);letter-spacing:.06em}
#sk-aurora .aurora-offp{display:none;grid-area:met;margin-top:18px;font:italic 400 17px/1.35 var(--serif);color:var(--paper);max-width:34ch}
#sk-aurora .aurora-offp code{font:400 10.5px/1 var(--pm);font-style:normal;color:var(--dim);display:block;margin-top:10px;word-break:break-all}
#sk-aurora.aurora-off .aurora-ink,#sk-aurora.aurora-off .aurora-met,#sk-aurora.aurora-off .aurora-tok,#sk-aurora.aurora-off .aurora-hero{display:none}
#sk-aurora.aurora-off .aurora-offp{display:block}
#sk-aurora.aurora-off .aurora-st{color:var(--hot)}
/* wide: an open book, the plate on the left page and the text on the right */
@media (min-width:860px){
  #sk-aurora .aurora-bk{min-height:calc(100vh - var(--aurora-top,0px));padding:calc(46px - var(--aurora-top,0px)) 56px 30px;grid-template-columns:minmax(0,1fr) minmax(0,1fr);column-gap:88px;
    grid-template-rows:auto auto auto auto auto 1fr;grid-template-areas:"pl hd" "pl hero" "pl ink" "pl met" "pl tok" "pl ft"}
  #sk-aurora .aurora-bk::before{content:"";position:absolute;top:0;bottom:0;left:50%;width:120px;margin-left:-60px;pointer-events:none;
    background:linear-gradient(90deg,rgba(80,60,30,0) 0%,rgba(80,60,30,.05) 38%,rgba(80,60,30,.13) 49.6%,rgba(255,252,242,.45) 50.4%,rgba(255,252,242,.12) 58%,rgba(255,252,242,0) 100%)}
  #sk-aurora .aurora-pl{margin:6px 0 0;min-height:calc(100vh - 82px)}
  #sk-aurora .aurora-bath{flex:1;height:auto;min-height:420px}
  #sk-aurora .aurora-hd{padding-top:0}
  #sk-aurora .aurora-meta{padding-right:var(--aurora-dock,96px)}
  #sk-aurora .aurora-st{font-size:46px;margin-top:16px}
  #sk-aurora .aurora-hero{margin-top:26px}
  #sk-aurora .aurora-n{font-size:118px}
  #sk-aurora .aurora-u{font-size:26px}
  #sk-aurora .aurora-ink{margin-top:26px}
  #sk-aurora .aurora-ink canvas{height:58px}
  #sk-aurora .aurora-met{margin-top:22px;row-gap:16px}
  #sk-aurora .aurora-tok{margin-top:20px}
  #sk-aurora .aurora-ft{align-self:end}
  #sk-aurora .aurora-offp{grid-area:hero;font-size:21px}
}
@media (min-width:860px) and (max-height:700px){#sk-aurora .aurora-n{font-size:96px}#sk-aurora .aurora-hero,#sk-aurora .aurora-ink{margin-top:16px}}
@media (min-width:390px) and (max-width:859px) and (min-height:860px){#sk-aurora .aurora-bath{height:300px}}
@media (prefers-reduced-motion:reduce){#sk-aurora *{transition:none!important}}
`,
    html: `
<div class="aurora-bk">
  <header class="aurora-hd">
    <div class="aurora-meta" id="aurora-aMeta">TokenPulse</div>
    <h1 class="aurora-st" id="aurora-aState">Подключение</h1>
    <div class="aurora-model" id="aurora-aModel">&nbsp;</div>
  </header>
  <figure class="aurora-pl">
    <div class="aurora-bath"><canvas id="aurora-aBath"></canvas><i class="aurora-reg aurora-r1"></i><i class="aurora-reg aurora-r2"></i><i class="aurora-reg aurora-r3"></i><i class="aurora-reg aurora-r4"></i></div>
    <figcaption><span class="aurora-fig" id="aurora-aFig">I.</span><span class="aurora-cap" id="aurora-aCap">&nbsp;</span><span class="aurora-key" id="aurora-aKey"></span></figcaption>
    <div class="aurora-prog"><i id="aurora-aProg"></i></div>
  </figure>
  <section class="aurora-hero">
    <div class="aurora-n aurora-rest" id="aurora-aNum">—</div>
    <div class="aurora-hu"><div class="aurora-u">ток/с</div><div class="aurora-q" id="aurora-aQual">&nbsp;</div><div class="aurora-alt" id="aurora-aAlt">&nbsp;</div></div>
  </section>
  <section class="aurora-ink">
    <div class="aurora-ih"><span class="aurora-lb">почерк скорости</span><span class="aurora-lb" id="aurora-aMax"></span></div>
    <canvas id="aurora-aInk"></canvas>
    <div class="aurora-ax"><span>2½ минуты назад</span><span>сейчас</span></div>
  </section>
  <section class="aurora-met">
    <div class="aurora-m" id="aurora-mGpu"><div class="aurora-mh"><span class="aurora-lb">видеокарта</span><span class="aurora-ms"></span></div><div class="aurora-mv"><b>—</b><i></i></div><div class="aurora-rule"><i class="aurora-fl"></i><i class="aurora-mk"><b></b></i></div></div>
    <div class="aurora-m" id="aurora-mVram"><div class="aurora-mh"><span class="aurora-lb">видеопамять</span><span class="aurora-ms"></span></div><div class="aurora-mv"><b>—</b><i></i></div><div class="aurora-rule"><i class="aurora-fl"></i><i class="aurora-mk"><b></b></i></div></div>
    <div class="aurora-m" id="aurora-mTemp"><div class="aurora-mh"><span class="aurora-lb">температура</span><span class="aurora-ms"></span></div><div class="aurora-mv"><b>—</b><i></i></div><div class="aurora-rule"><i class="aurora-fl"></i><i class="aurora-mk"><b></b></i></div></div>
    <div class="aurora-m" id="aurora-mPwr"><div class="aurora-mh"><span class="aurora-lb">мощность</span><span class="aurora-ms"></span></div><div class="aurora-mv"><b>—</b><i></i></div><div class="aurora-rule"><i class="aurora-fl"></i><i class="aurora-mk"><b></b></i></div></div>
  </section>
  <section class="aurora-tok">
    <div><div class="aurora-lb">токенов сегодня</div><div class="aurora-tn"><span id="aurora-aTok">—</span></div><div class="aurora-ts" id="aurora-aTokS">&nbsp;</div></div>
    <div class="aurora-ta">за всё время<b id="aurora-aAll">—</b></div>
  </section>
  <p class="aurora-offp" id="aurora-aOffP"></p>
  <footer class="aurora-ft"><span id="aurora-aFoot">&nbsp;</span><span class="aurora-cf" id="aurora-aComfy"></span><span class="aurora-fo" id="aurora-aFolio">~</span></footer>
</div>`,

    mount(root, ctx) {
      S.ctx = ctx; S.root = root;
      const q = id => root.querySelector("#aurora-" + id);
      ["aMeta", "aState", "aModel", "aCap", "aKey", "aProg", "aNum", "aQual", "aAlt", "aMax", "aTok", "aTokS", "aAll", "aOffP", "aFoot", "aComfy", "aFolio", "aFig"].forEach(id => S.el[id] = q(id));
      ["mGpu", "mVram", "mTemp", "mPwr"].forEach(id => { const m = q(id);
        S.el[id] = {root: m, v: m.querySelector(".aurora-mv b"), u: m.querySelector(".aurora-mv i"), s: m.querySelector(".aurora-ms"), mk: m.querySelector(".aurora-mk"), fl: m.querySelector(".aurora-fl"), dot: m.querySelector(".aurora-mk b")}; });
      S.bath = q("aBath"); S.g = S.bath.getContext("2d");
      S.ink = q("aInk"); S.ig = S.ink.getContext("2d");
      if (typeof ResizeObserver === "function") { const ro = new ResizeObserver(() => { S.dirty = true; }); ro.observe(S.bath); ro.observe(S.ink); }
      addEventListener("resize", () => { S.dirty = true; });
      // the page itself is laid paper: a tile of specks and fibres, made once
      try {
        const c = off(220, 220), g = c.getContext("2d");
        grain(g, 220, 220, 52000, 1);
        root.style.setProperty("--grain", "url(" + c.toDataURL() + ")");
      } catch (e) {}
      // newer pages float the corner buttons over a transparent top border of this element: use it instead of our own clearance
      try { const bt = parseFloat(getComputedStyle(root).borderTopWidth) || 0;
        if (bt >= 24) { root.style.setProperty("--aurora-top", bt + "px"); root.style.setProperty("--aurora-dock", "0px"); } } catch (e) {}
      S.ready = true;
    },

    update(vm, ctx) {
      S.vm = vm;
      if (readPalette()) S.dirty = true;
      const E = S.el, root = S.root;
      root.classList.toggle("aurora-off", !!vm.off);
      if (vm.off) {
        set(E.aMeta, (vm.host || "сервер") + " · нет данных");
        set(E.aState, vm.label || "Нет связи");
        set(E.aModel, vm.url === "demo" ? "встроенные тестовые данные" : vm.url || "");
        set(E.aCap, vm.label === "Нужен токен" ? "агент просит токен — ванна закрыта" : "агент молчит — ванна высохла");
        set(E.aKey, ""); E.aProg.style.transform = "scaleX(0)";
        set(E.aOffP, vm.label === "Нужен токен"
          ? "Агент отвечает, но просит токен. Откройте список серверов в правом верхнем углу и впишите его."
          : "Агент не отвечает. Проверьте, что agent.py запущен на сервере и порт открыт; монитор переподключится сам.");
        set(E.aFoot, ""); set(E.aComfy, ""); set(E.aFolio, "");
        S.genRate = S.readRate = 0; S.omegaT = 0; S.beads = 0; S.wasBusy = S.wasRd = false;
        if (S.comb.on) S.comb.on = false;
        return;
      }
      const g = vm.gpu || {}, st = vm.state, busy = st === "generating" || st === "reading", pr = vm.progress || {};
      // --- simulation targets
      if (busy && !S.wasBusy) newStone();
      if (vm.rd && !S.wasRd) { const c = S.comb; c.dir = -c.dir; c.on = true; c.prog = 0; c.x = c.dir > 0 ? -S.hx - 60 : S.hx + 60; c.v = 0; }
      if (!vm.rd) S.comb.on = false;
      else S.comb.prog = fin(pr.total) && pr.total > 0 && fin(pr.read) ? clamp(pr.read / pr.total, 0, 1) : Math.min(0.9, S.comb.prog + 0.08);
      S.wasBusy = busy; S.wasRd = vm.rd;
      const sp = vm.speed !== "none" ? (fin(vm.live) ? vm.live : vm.dec) : null;
      S.genRate = st === "generating" ? clamp((fin(sp) ? sp : 32) / TOK_PER_DROP, 0.4, 7) : 0;
      S.readRate = vm.rd ? clamp((fin(vm.pre) ? vm.pre : 500) / PROMPT_PER_DROP, 0.4, 4) : 0;
      S.omegaT = st === "unloaded" ? 0 : 0.004 + 0.03 * clamp((fin(g.util) ? g.util : 0) / 100, 0, 1);
      S.veilT = st === "unloaded" ? 0.6 : 0;
      S.beads = vm.queued || 0;

      // --- header
      const kindName = vm.engineUp ? vm.engine : (vm.comfy && vm.comfy.up ? "ComfyUI" : "без движка");
      E.aMeta.innerHTML = "<b>" + ctx.esc(vm.host || "сервер") + "</b> · " + ctx.esc(kindName) + (fin(vm.ctx) && vm.ctx ? " · " + Math.round(vm.ctx / 1024) + "K" : "");
      let title = STATE[st] || st;
      if (!vm.engineUp) title = vm.comfy && vm.comfy.up ? (vm.comfy.running ? "ComfyUI рисует" : "ComfyUI ждёт") : "Только железо";
      const qtag = vm.queued > 0 ? "<small>очередь " + vm.queued + "</small>" : "";
      const sh = ctx.esc(title) + qtag;
      if (E.aState.innerHTML !== sh) E.aState.innerHTML = sh;
      E.aState.style.color = st === "generating" && vm.engineUp ? "var(--out)" : vm.rd ? "var(--in)" : "";
      set(E.aModel, vm.model || (vm.comfy && vm.comfy.up ? "ComfyUI " + (vm.comfy.version || "") : g.name || "модель не загружена"));

      // --- caption under the plate
      let cap, key = vm.speed === "none" ? "капли условные" : "капля ≈ " + TOK_PER_DROP + " ток.";
      if (st === "generating" && vm.engineUp) cap = fin(pr.max) && pr.max ? "ответ: " + grp(pr.gen) + " из " + grp(pr.max) + " ток." : "капли падают — идёт ответ";
      else if (vm.rd) { cap = fin(pr.total) && pr.total ? "гребень читает: " + grp(pr.read) + " из " + grp(pr.total) : "гребень читает промпт"; key = "гребень = доля промпта"; }
      else if (st === "unloaded") { cap = "модель выгружена — краска оседает"; key = ""; }
      else if (!vm.engineUp && vm.comfy && vm.comfy.running) cap = "ComfyUI рисует, капли — без счёта";
      else { const r = (vm.recent || [])[0]; cap = r && fin(r.out) ? "последний ответ: " + grp(r.out) + " ток." + (fin(r.duration_s) ? " за " + r.duration_s.toFixed(1).replace(".", ",") + " с" : "") : "вода спокойна — ждёт запроса"; }
      if (vm.queued > 0) cap += " · ждут " + vm.queued;
      set(E.aCap, cap); set(E.aKey, key);
      const pp = vm.rd && pr.total ? pr.read / pr.total : st === "generating" && pr.max ? pr.gen / pr.max : 0;
      const ptr = "scaleX(" + clamp(pp || 0, 0, 1).toFixed(3) + ")";
      if (E.aProg.style.transform !== ptr) E.aProg.style.transform = ptr;
      E.aProg.style.background = vm.rd ? "var(--in)" : "var(--out)";

      // --- headline
      let num, qual, alt = "";
      E.aNum.classList.toggle("aurora-in", !!vm.rd);
      E.aNum.classList.toggle("aurora-rest", !vm.rd && !(st === "generating" && vm.engineUp));
      if (vm.rd) { num = f1(vm.pre); qual = "<b>читает промпт</b> · сейчас"; alt = "вывод: " + (vm.speed === "none" ? "не сообщается" : f1(vm.dec) + " ток/с, последний"); }
      else if (vm.speed === "none") { num = "—"; qual = "<b>движок не сообщает скорость</b>"; alt = vm.note || ""; }
      else {
        num = f1(vm.dec);
        qual = vm.speed === "avg" ? "<b>среднее</b> по движку" : st === "generating" && vm.engineUp ? "<b>генерация</b> · сейчас" : "<b>последний ответ</b>";
        alt = fin(vm.pre) ? "чтение: " + f1(vm.pre) + " ток/с" + (vm.speed === "avg" ? ", среднее" : "") : (vm.note || "");
      }
      set(E.aNum, num); E.aNum.classList.toggle("aurora-nil", num === "—");
      if (E.aQual.innerHTML !== qual) E.aQual.innerHTML = qual;
      set(E.aAlt, alt);
      set(E.aMax, vm.speed === "none" ? "скорость не сообщается" : "толщина ∝ ток/с · макс " + Math.round(S.inkMax));

      // --- meters
      const has = g.has;
      const gname = (g.name || "").replace(/^NVIDIA\s+|GeForce\s+|AMD\s+|Radeon\s+/g, "");
      setMeter("mGpu", has && fin(g.util) ? Math.round(g.util) : "—", has && fin(g.util) ? "%" : "", has ? gname || "загрузка" : "видеокарта не найдена", has ? g.util : null);
      setMeter("mVram", g.vt ? g.vu.toFixed(1).replace(".", ",") : "—", g.vt ? "из " + Math.round(g.vt) + " ГБ" : "", g.vt ? Math.round(g.vpct) + " % занято" : "нет данных", g.vt ? g.vpct : null, null, g.vpct >= 97);
      const tC = fin(g.temp) ? g.temp : null, tC2 = fin(vm.cpu && vm.cpu.temp) ? vm.cpu.temp : null, tShow = tC != null ? tC : tC2;
      setMeter("mTemp", tShow != null ? Math.round(tShow) : "—", tShow != null ? "°C" : "",
        tShow == null ? "датчики молчат" : tC != null ? (fin(g.tempMem) ? "память " + Math.round(g.tempMem) + "°" : "") + (tC2 != null ? (fin(g.tempMem) ? " · " : "") + "ЦП " + Math.round(tC2) + "°" : "") || "видеокарта" : "ЦП, видеокарта молчит",
        tShow != null ? (tShow - 30) / 60 * 100 : null, tShow != null ? ctx.heat(tShow) : null, tShow >= 80);
      setMeter("mPwr", fin(g.power) ? Math.round(g.power) : "—", fin(g.power) ? "Вт" : "", fin(g.powerLimit) ? "предел " + Math.round(g.powerLimit) + " Вт" : fin(g.power) ? "" : "нет данных",
        fin(g.power) && fin(g.powerLimit) && g.powerLimit ? g.power / g.powerLimit * 100 : null);

      // --- tokens
      const td = vm.today || {}, al = vm.all || {};
      set(E.aTok, grp(td.total));
      set(E.aTokS, fin(td.total) ? "вход " + mt(td.prompt) + " · вывод " + mt(td.output) + " · " + (fin(td.requests) ? td.requests + " " + ctx.ruCount(td.requests, "запрос", "запроса", "запросов") : "") : "счётчик пуст");
      set(E.aAll, mt(al.total));

      // --- colophon
      const c = vm.cpu || {}, rm = vm.ram || {};
      set(E.aFoot, "ЦП " + (fin(c.pct) ? Math.round(c.pct) + " %" : "—") + (fin(c.temp) ? " · " + Math.round(c.temp) + "°" : "") +
        "  ·  ОЗУ " + (fin(rm.used) ? rm.used.toFixed(1).replace(".", ",") + (fin(rm.total) ? "/" + Math.round(rm.total) : "") + " ГБ" : "—") +
        "  ·  отклик " + (fin(vm.ping) ? Math.round(vm.ping) + " мс" : "—"));
      const cf = vm.comfy || {};
      set(E.aComfy, cf.up ? "ComfyUI " + (cf.version || "") + " · рендер " + (cf.running || 0) + " · ждут " + (cf.pending || 0) + (fin(cf.vram_free_gib) ? " · свободно " + cf.vram_free_gib.toFixed(1).replace(".", ",") + " ГБ" : "") : "");
      set(E.aFolio, "~ работает " + ctx.upt(vm.uptime) + " ~");
    },

    frame(t, vm, ctx) {
      if (!S.ready) return;
      const now = t / 1000;
      let dt = now - S.last; S.last = now;
      if (!(dt > 0)) dt = 0; else if (dt > 0.05) dt = 0.05;
      if (S.dirty) resize();
      drawBath(now, dt, vm || S.vm);
      if (!(vm && vm.off)) drawInk(vm || S.vm);
    }
  });
})();
