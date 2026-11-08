/* Спокойный: for people who just want to know "is the AI busy?". Plain words instead of numbers,
   one soft orb that breathes, thinks or rests, three short sentences about the machine. */
TP.register({
  id: "calm",
  name: "Спокойный",
  who: "Всем остальным: без терминов",
  swatch: ["#f4efe7", "#2f9e77", "#4f6bd8", "#2b2a28"],
  fonts: ["https://fonts.googleapis.com/css2?family=Nunito:wght@600;700;800&display=swap"],
  theme: {
    "--bg": "#f4efe7", "--bg2": "#ebe4d9", "--line": "#e3dbcd", "--line2": "#d0c6b4",
    "--paper": "#2b2a28", "--dim": "#7d766b", "--faint": "#b3aa9a",
    "--out": "#2f9e77", "--in": "#4f6bd8", "--warm": "#e0922f", "--hot": "#d9534a",
    "--ui": '"Nunito","Segoe UI",system-ui,sans-serif', "--num": '"Nunito","Segoe UI",system-ui,sans-serif',
    "color-scheme": "light"
  },
  css: `
:root[data-skin="calm"] body{font-family:var(--ui)}
:root[data-skin="calm"] body::after{display:none}
#sk-calm{min-height:100vh;padding:18px 18px 28px;font-family:var(--ui);
  background:radial-gradient(560px 460px at 50% -40px,color-mix(in srgb,var(--tone,var(--out)) 16%,transparent),transparent 72%),var(--bg);
  --tone:var(--out);transition:--tone .6s}
#sk-calm[data-s="reading"]{--tone:var(--in)}
#sk-calm[data-s="generating"]{--tone:var(--warm)}
#sk-calm[data-s="off"]{--tone:var(--hot)}
#sk-calm[data-s="unloaded"]{--tone:var(--faint)}
#sk-calm .cm-w{max-width:440px;margin:0 auto;display:grid;gap:20px;justify-items:center;text-align:center}
#sk-calm .cm-host{font:700 13px var(--ui);color:var(--dim)}
#sk-calm .cm-orb{position:relative;width:188px;height:188px;display:grid;place-items:center}
#sk-calm .cm-orb i{position:absolute;border-radius:50%;background:var(--tone);transition:background .6s}
#sk-calm .cm-orb i:nth-child(1){inset:0;opacity:.13;animation:cmR var(--sp,5s) ease-in-out infinite}
#sk-calm .cm-orb i:nth-child(2){inset:20px;opacity:.22;animation:cmR var(--sp,5s) ease-in-out .5s infinite}
#sk-calm .cm-orb i:nth-child(3){inset:44px;opacity:1;animation:cmB var(--sp,5s) ease-in-out infinite;
  background:radial-gradient(circle at 34% 28%,color-mix(in srgb,var(--tone) 45%,#fff),var(--tone) 70%);
  box-shadow:0 18px 44px color-mix(in srgb,var(--tone) 42%,transparent)}
#sk-calm[data-s="generating"]{--sp:1.5s}
#sk-calm[data-s="reading"]{--sp:2.4s}
#sk-calm[data-s="off"],#sk-calm[data-s="unloaded"]{--sp:0s}
#sk-calm[data-s="off"] .cm-orb i,#sk-calm[data-s="unloaded"] .cm-orb i{animation:none}
@keyframes cmR{0%,100%{transform:scale(.94)}50%{transform:scale(1.04)}}
@keyframes cmB{0%,100%{transform:scale(.97)}50%{transform:scale(1.03)}}
#sk-calm .cm-icon{position:relative;z-index:2;color:#fff;width:50px;height:30px}
#sk-calm .cm-icon svg{width:100%;height:100%;overflow:visible}
#sk-calm .cm-dots circle{animation:cmD 1s ease-in-out infinite}
#sk-calm .cm-dots circle:nth-child(2){animation-delay:.16s}#sk-calm .cm-dots circle:nth-child(3){animation-delay:.32s}
@keyframes cmD{0%,60%,100%{transform:translateY(0)}30%{transform:translateY(-7px)}}
#sk-calm .cm-spin{animation:cmS 1.4s linear infinite;transform-origin:25px 15px}
@keyframes cmS{to{transform:rotate(360deg)}}
#sk-calm .cm-title{font:800 32px/1.1 var(--ui);letter-spacing:-.01em}
#sk-calm .cm-sub{margin-top:8px;font:600 16px/1.35 var(--ui);color:var(--dim);min-height:22px}
#sk-calm .cm-card{width:100%;background:#fffdf9;border-radius:22px;padding:4px 18px;
  box-shadow:0 1px 0 var(--line),0 14px 34px rgba(80,55,20,.07);text-align:left}
#sk-calm .cm-v{display:grid;grid-template-columns:36px 1fr auto;gap:12px;align-items:center;padding:13px 0;border-bottom:1px solid var(--line)}
#sk-calm .cm-v:last-child{border-bottom:0}
#sk-calm .cm-v .cm-ic{width:36px;height:36px;border-radius:12px;display:grid;place-items:center;
  background:color-mix(in srgb,var(--c) 14%,transparent);color:var(--c)}
#sk-calm .cm-v .cm-ic svg{width:19px;height:19px;stroke:currentColor;fill:none;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
#sk-calm .cm-v b{display:block;font:700 15px var(--ui)}
#sk-calm .cm-v .cm-bar{margin-top:7px;height:6px;border-radius:6px;background:var(--line);overflow:hidden}
#sk-calm .cm-v .cm-bar i{display:block;height:100%;border-radius:6px;background:var(--c);transition:width .8s cubic-bezier(.2,.8,.2,1)}
#sk-calm .cm-v .cm-pill{font:700 13px var(--ui);color:var(--c);background:color-mix(in srgb,var(--c) 12%,transparent);padding:5px 11px;border-radius:999px;white-space:nowrap}
#sk-calm .cm-foot{font:700 14px/1.5 var(--ui);color:var(--dim)}
#sk-calm .cm-foot b{color:var(--paper)}
#sk-calm .cm-hint{font:600 12px var(--ui);color:var(--faint)}
`,
  html: `<div class="cm-w">
  <div class="cm-host" id="cmHost">—</div>
  <div class="cm-orb" id="cmOrb"><i></i><i></i><i></i><div class="cm-icon" id="cmIcon"></div></div>
  <div><div class="cm-title" id="cmTitle">—</div><div class="cm-sub" id="cmSub"></div></div>
  <div class="cm-card" id="cmCard"></div>
  <div class="cm-foot" id="cmFoot"></div>
</div>`,

  mount(root, ctx) {
    this.el = id => root.querySelector("#" + id);
    this.cache = {};
    this.icons = {
      idle: '<svg viewBox="0 0 50 30"><path d="M14 16l8 8 15-17" fill="none" stroke="currentColor" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
      dots: '<svg class="cm-dots" viewBox="0 0 50 30"><circle cx="10" cy="17" r="4.5" fill="currentColor"/><circle cx="25" cy="17" r="4.5" fill="currentColor"/><circle cx="40" cy="17" r="4.5" fill="currentColor"/></svg>',
      spin: '<svg viewBox="0 0 50 30"><g class="cm-spin"><path d="M25 5a10 10 0 1 1-9.5 6.9" fill="none" stroke="currentColor" stroke-width="4.5" stroke-linecap="round"/></g></svg>',
      off: '<svg viewBox="0 0 50 30"><path d="M16 6l18 18M34 6L16 24" fill="none" stroke="currentColor" stroke-width="5" stroke-linecap="round"/></svg>',
      unloaded: '<svg viewBox="0 0 50 30"><path d="M14 15h22" fill="none" stroke="currentColor" stroke-width="5" stroke-linecap="round"/></svg>'
    };
    this.svg = {
      gpu: '<svg viewBox="0 0 24 24"><rect x="3" y="7" width="18" height="11" rx="2"/><path d="M7 11h4M7 14h6M17 21v-3M7 21v-3M21 10h1.5"/></svg>',
      mem: '<svg viewBox="0 0 24 24"><rect x="3" y="8" width="18" height="8" rx="1.5"/><path d="M7 8V5M11 8V5M15 8V5M19 8V5M7 16v3M11 16v3M15 16v3M19 16v3"/></svg>',
      temp: '<svg viewBox="0 0 24 24"><path d="M10 14.5V5a2 2 0 0 1 4 0v9.5a4 4 0 1 1-4 0z"/><path d="M12 9v7"/></svg>',
      speed: '<svg viewBox="0 0 24 24"><path d="M4 17a8 8 0 1 1 16 0"/><path d="M12 17l4-5"/></svg>'
    };
  },

  update(v, ctx) {
    const { fin, ruCount, esc } = ctx, el = this.el, S = this.cache;
    const set = (id, t) => { if (S[id] !== t) { el(id).textContent = t; S[id] = t; } };
    const setHTML = (id, h) => { if (S[id] !== h) { el(id).innerHTML = h; S[id] = h; } };
    const word = (x, t) => { for (const [lim, w] of t) if (x < lim) return w; return t[t.length - 1][1]; };

    let key, title, sub, icon;
    if (v.off) {
      key = "off"; title = v.label === "Нужен токен" ? "Нужен пароль" : "Нет связи";
      sub = v.label === "Нужен токен" ? "Откройте «Серверы» и введите токен" : "Не получается достучаться до сервера";
      icon = this.icons.off;
    } else if (v.state === "generating") {
      key = "generating"; title = "Отвечает";
      sub = v.queued ? "Пишет ответ, ещё " + v.queued + " " + (v.queued === 1 ? "ждёт" : "ждут") + " своей очереди" : "Пишет ответ прямо сейчас";
      icon = this.icons.dots;
    } else if (v.state === "reading") {
      key = "reading"; title = "Читает запрос";
      sub = v.queued ? "Изучает, что ему прислали. В очереди ещё " + v.queued : "Изучает, что ему прислали";
      icon = this.icons.spin;
    } else if (v.state === "unloaded") {
      key = "unloaded"; title = "Не готов"; sub = "Модель ещё не загружена в память"; icon = this.icons.unloaded;
    } else {
      key = "idle"; title = "Свободен"; sub = "Можно отправлять запрос"; icon = this.icons.idle;
    }
    const root = this.el("cmOrb").parentNode.parentNode;
    if (root.dataset.s !== key) root.dataset.s = key;
    set("cmHost", v.off ? (v.host || "") : v.host + (v.model ? " · " + v.model : ""));
    set("cmTitle", title); set("cmSub", sub);
    setHTML("cmIcon", icon);

    if (v.off) { setHTML("cmCard", ""); set("cmFoot", ""); return; }

    const row = (ic, label, pct, w, color) =>
      `<div class="cm-v" style="--c:${color}"><div class="cm-ic">${this.svg[ic]}</div><div><b>${label}</b><div class="cm-bar"><i style="width:${Math.max(3, Math.min(100, pct || 0))}%"></i></div></div><span class="cm-pill">${esc(w)}</span></div>`;
    const C = ctx.C;
    const rows = [];
    const g = v.gpu;
    if (fin(g.util)) rows.push(row("gpu", "Видеокарта", g.util,
      word(g.util, [[10, "отдыхает"], [40, "работает спокойно"], [75, "заметно занята"], [92, "сильно занята"], [999, "на пределе"]]), g.util >= 97 ? C.warm : C.in));
    if (fin(g.vpct)) rows.push(row("mem", "Видеопамять", g.vpct,
      word(g.vpct, [[50, "много места"], [80, "хватает"], [92, "почти заполнена"], [999, "заполнена"]]), g.vpct < 80 ? C.out : g.vpct < 92 ? C.warm : C.hot));
    const T = v.tempMax;
    if (fin(T)) rows.push(row("temp", "Температура", (T - 25) / 65 * 100,
      word(T, [[50, "прохладно"], [65, "в норме"], [78, "тепло"], [85, "горячо"], [999, "перегрев"]]), T < 65 ? C.out : T < 80 ? C.warm : C.hot));
    if (v.speed !== "none" && fin(v.dec) && v.dec > 0)
      rows.push(row("speed", "Скорость ответа", v.dec / 80 * 100, word(v.dec, [[15, "медленно"], [40, "нормально"], [999, "быстро"]]), C.out));
    setHTML("cmCard", rows.join(""));

    const n = v.today && v.today.requests;
    let foot = fin(n) && n > 0 ? "Сегодня ИИ ответил на <b>" + n + "</b> " + ruCount(n, "запрос", "запроса", "запросов") : "";
    if (v.comfy && v.comfy.up && v.comfy.running) foot += (foot ? "<br>" : "") + "Ещё рисует картинку в ComfyUI";
    setHTML("cmFoot", foot);
  }
});
