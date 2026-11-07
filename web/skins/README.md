# Skins

A skin is one file, `web/skins/<id>.js`: plain browser JavaScript, no build step, no dependencies.
It registers itself with `TP.register({...})`, and `index.html` mounts it into its own `<main>`
element, feeds it a **view model** once a second and calls its `frame()` on every animation frame
while it is on screen. The page already handles the server list, the compact strip, the
picture-in-picture window, the corner buttons and the skin picker, so a skin only has to draw.

A skin is a layout and a personality, not a recolouring: every skin in this folder answers a
different audience.

| id | name | for |
| --- | --- | --- |
| *(built in)* `pulse` | Пульс | enthusiasts: the pulse tape, comb meters, odometer |
| `console` | Консоль | admins and engineers: a text terminal, dense, every number |
| `calm` | Спокойный | everyone else: plain words, no jargon, one glance |
| `cockpit` | Приборы | gamers and overclockers: analog dials and warning lamps |
| `onair` | Эфир | streamers: a lower-third bar for OBS, transparent background possible |
| `aurora` | см. файл | the showpiece |

## Contract

```js
TP.register({
  id: "mine",                       // lower case, matches the file name
  name: "Мой скин",                 // shown in the picker (Russian UI)
  who: "Для кого",                  // one short line under the name
  swatch: [bg, colorA, colorB, ink],// 4 hex colours for the picker button
  fonts: ["https://fonts.googleapis.com/css2?family=...&display=swap"],  // optional, Google Fonts only
  theme: { "--bg": "#0a0a0b", ... },// required keys below, 6-digit hex values only
  css: `#sk-mine .x{...}`,          // all your CSS, scope every selector with #sk-<id>
  html: `<div class="x">...</div>`, // markup placed inside <main class="skin" id="sk-<id>">
  mount(root, ctx) {},              // once, after the markup exists: find elements, size canvases
  update(vm, ctx) {},               // once a second, with fresh data: write text, set targets
  frame(t, vm, ctx) {},             // every animation frame (t = ms): draw canvases, ease values
});
```

`theme` must define `--bg --bg2 --line --line2 --paper --dim --faint --out --in --warm --hot`
(6-digit hex, the canvas code of the page reads them) and may define the fonts `--num --mono --ui`.
Meaning: `--out` = generated (output) tokens, `--in` = prompt reading (input) tokens, `--warm`/`--hot`
= warning / danger, `--paper` = main ink, `--dim` / `--faint` = secondary ink. The compact strip,
the picture-in-picture window and the favicon take their colours from the same variables, so a
skin's theme also themes those.

`root` is the skin's own `<main>`; it is a block element that fills the window width and grows
with its content. Make it at least `min-height:100vh` if the skin owns the background.
The page draws 28 px buttons in the top-right corner (compact, window-on-top, servers) on every
skin except the first one: leave about 40 px of free space there.

## View model (`vm`)

When there is no connection: `vm.off === true`, `vm.label` is the reason ("Нет связи", "Нужен токен"),
`vm.host` the server name. All other lists are empty and objects are `{}` then.

| field | meaning |
| --- | --- |
| `host`, `url` | server name (the agent's host name), agent address |
| `engine`, `kind`, `model`, `ctx` | engine name ("Strata", "llama.cpp", "LM Studio"...), its kind id, loaded model, context size in tokens |
| `state` | `"generating"` \| `"reading"` (prompt being read) \| `"idle"` \| `"unloaded"`; `gen` / `rd` are the booleans |
| `dec`, `pre` | tokens/s to show for output (decode) and input (prefill): live when working, last or average otherwise; `null` when unknown |
| `live` | live decode tokens/s, only while generating, else `null` |
| `speed` | `"live"` \| `"avg"` (engine only reports an average) \| `"none"` (engine reports no speed: show that honestly) |
| `note` | a short Russian remark about what the engine can't tell, or `null` |
| `queued`, `running` | requests waiting / running |
| `progress` | `{read, total, gen, max}`: prompt tokens read of total while reading, tokens generated of max while generating |
| `gpu` | `{has, name, util %, vu, vt (VRAM GiB used/total), vpct, temp °C, tempMem, power W, powerLimit}`; any may be `null` |
| `cpu` | `{pct, temp, name}` |
| `ram` | `{used, total (GiB), pct}` |
| `tempMax` | hottest of GPU and CPU or `null` |
| `today`, `all` | `{prompt, output, total, requests}` token counters for today and for all time |
| `recent` | last requests: `{prompt, out, tok_s, prefill_tok_s, duration_s}`, newest first, may be empty |
| `comfy` | ComfyUI: `{up, running, pending, vram_free_gib, version}` |
| `engines` | every engine found on the server: `{kind, name, up, state, model}` |
| `ping` (ms), `uptime` (s), `agent` | link latency, server uptime, `{version, hostname, os}` |

## Helpers (`ctx`)

`ctx.C` live colour table `{bg, line, line2, paper, dim, faint, out, in, warm, hot}` (always the current
theme, read it at draw time), `ctx.FONT` `{num, mono, ui}` CSS font stacks for canvas `font`,
`ctx.hist` `{dec, pre, gpu, t}`: one sample per second, 150 long, newest last (`dec`/`pre` tokens/s,
`gpu` %; `t` is `performance.now()` of the last push, use `(performance.now()-t)/1000` for smooth
scrolling), `ctx.fit(canvas)` sizes a canvas to its CSS box at the device pixel ratio and returns
`[w, h, scale]`, `ctx.f1(n)` formats a speed, `ctx.mtok(n)` "41.4M", `ctx.upt(s)` uptime, `ctx.esc(s)`,
`ctx.rgba("#rrggbb", a)`, `ctx.mix(a, b, t)`, `ctx.heat(°C)` temperature colour, `ctx.ruCount(n, "запрос",
"запроса", "запросов")`, `ctx.odometer(el, n)` rolling-digit counter on an element with class `odo`
(style `.odo` and `.odo .d` yourself or reuse the page's).

## Rules

* Primary size is a narrow window, **364 × 812**; it must also be good at 1180 × 800 and at phone
  width. No horizontal scrolling, nothing cut off, no layout jumps while numbers change.
* Handle: no connection, `unloaded`, `speed` `"none"` / `"avg"`, no GPU, missing temperatures (`null`),
  long model names, `queued > 0`, ComfyUI present or absent, `prefers-reduced-motion`.
* Russian interface text. Concise: the whole state readable in a glance, details after.
* Keep it light: canvases sized by `ctx.fit`, no per-frame DOM writes, no allocations in `frame()`
  that you can avoid. Do not use `localStorage`, network requests or `eval`.
* Never touch anything outside your own `<main>`; do not edit `index.html`.

## Trying it

Open `web/index.html?demo=8&skin=<id>` straight from disk (no agent needed; `demo=8` plays the demo 8×
faster; add `&engine=llamacpp` or `&engine=lmstudio` for engines that report less; `&mini=1` for the
compact strip). The history tape needs 60 to 90 seconds to fill. Add `&bg=none` for a transparent
page background (OBS browser source). Screenshots with Playwright at 364 × 812, 1180 × 800, scale 2.
Against a real agent: `python3 agent.py --demo` serves the same demo data over HTTP.
