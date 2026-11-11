#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TokenPulse widget for Linux without tkinter: the web design in its own window.

The window shows exactly the page the browser monitor shows, so every web skin works
(pulse, console, calm, cockpit, onair, aurora), including the compact strip. It is the
Linux counterpart of the Windows `start-monitor.bat` + `frameless.py` combo: no title
bar, no tabs, no address bar, window kept above the others.

Needs GTK3 + WebKit2 through PyGObject:
    Debian/Ubuntu: sudo apt install python3-gi gir1.2-webkit2-4.0

  ./start-widget-web.sh                                  # this computer, http://127.0.0.1:8787
  ./start-widget-web.sh --server http://192.168.31.30:8787
  ./start-widget-web.sh --skin cockpit                   # pulse, console, calm, cockpit, onair, aurora
  ./start-widget-web.sh --skin auto                      # whatever was last chosen on the page
  ./start-widget-web.sh --mini                           # compact strip from the start
  ./start-widget-web.sh --no-top --size 520x900 --pos 1200x150
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Runs before the page scripts: give a fresh profile a default skin and close the
# first-run "СЕРВЕРЫ" sheet, so the widget opens on the dashboard.
BOOT_JS = """
(function () {
  try {
    if (!localStorage.getItem("tp2.skin")) {
      localStorage.setItem("tp2.skin", JSON.stringify("pulse"));
    }
  } catch (e) {}
  document.addEventListener("DOMContentLoaded", function () {
    var tries = 0;
    var t = setInterval(function () {
      var b = document.getElementById("fClose");
      if (b) { b.click(); clearInterval(t); }
      else if (++tries > 25) { clearInterval(t); }
    }, 200);
  });
})();
"""


def normalize_server(server):
    return server if server.startswith("http") else "http://" + server


def page_url(server, skin="pulse", mini=False):
    """Agent address -> page address, same query parameters the browser monitor uses."""
    server = normalize_server(server).rstrip("/")
    query = []
    if mini:
        query.append("mini=1")
    if skin and skin != "auto":
        query.append("skin=" + skin)
    return server + "/" + ("?" + "&".join(query) if query else "")


def parse_wh(text, default):
    """'520x900' -> (520, 900); anything unusable keeps the default."""
    try:
        w, h = (text or "").lower().split("x")
        return max(80, int(w)), max(40, int(h))
    except ValueError:
        return default


def agent_port(server):
    try:
        return int(normalize_server(server).split("//", 1)[1].split("/")[0].rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return 8787


def agent_alive(server):
    try:
        with urllib.request.urlopen(normalize_server(server).rstrip("/") + "/api/health",
                                    timeout=2) as r:
            return json.loads(r.read().decode("utf-8", "replace")).get("ok") is True
    except Exception:
        return False


def start_local_agent(server):
    """This computer is the server: make sure an agent is running before drawing."""
    if agent_alive(server):
        return
    agent = HERE / "agent.py"
    cmd = [sys.executable, str(agent)]
    if not agent.exists():
        agent = HERE / "TokenPulse-Agent"     # release archive: packaged agent next to this file
        cmd = [str(agent)]
    if not agent.exists():
        return
    subprocess.Popen(cmd + ["--port", str(agent_port(server))],
                     cwd=str(HERE), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    for _ in range(20):
        if agent_alive(server):
            return
        time.sleep(0.25)


def gtkWebKit():
    """(Gtk, WebKit2, Gdk) or None. Newer distros ship WebKit2 4.1 instead of 4.0."""
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        for version in ("4.0", "4.1"):
            try:
                gi.require_version("WebKit2", version)
                break
            except ValueError:
                continue
        # Gtk and WebKit2 first, Gdk last: loading Gdk before them would pick GTK4.
        from gi.repository import Gtk, WebKit2, Gdk
        return Gtk, WebKit2, Gdk
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description="TokenPulse widget: web design in a frameless window")
    ap.add_argument("--server", default="http://127.0.0.1:8787", help="agent address")
    ap.add_argument("--skin", default="pulse",
                    help="pulse, console, calm, cockpit, onair, aurora; 'auto' keeps the last choice")
    ap.add_argument("--mini", action="store_true", help="start as a compact strip")
    ap.add_argument("--size", default="", help="window size, e.g. 380x850")
    ap.add_argument("--pos", default="", help="window position, e.g. 1500x60")
    ap.add_argument("--no-top", action="store_true", help="do not keep the window above the others")
    ap.add_argument("--no-agent", action="store_true", help="never start a local agent")
    args = ap.parse_args()

    server = normalize_server(args.server)
    if not args.no_agent and ("127.0.0.1" in server or "localhost" in server):
        start_local_agent(server)

    libs = gtkWebKit()
    if libs is None:
        print("Нужны PyGObject и WebKit2: sudo apt install python3-gi gir1.2-webkit2-4.0",
              file=sys.stderr)
        print("Без них есть обычный виджет: ./start-widget.sh (см. «Если нет tkinter на Linux»)",
              file=sys.stderr)
        return 1
    Gtk, WebKit2, Gdk = libs

    width, height = parse_wh(args.size, (380, 150) if args.mini else (380, 850))

    win = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
    win.set_title("TokenPulse")
    win.set_decorated(False)                     # the page draws its own header
    win.set_default_size(width, height)
    win.set_keep_above(not args.no_top)
    win.set_type_hint(Gdk.WindowTypeHint.UTILITY)
    win.connect("destroy", Gtk.main_quit)

    css = Gtk.CssProvider()
    css.load_from_data(b"""
        #tp-grip { background:#0b1018; }
        #tp-grip label { color:#5d6b82; font:10px sans-serif; padding-left:10px; }
        #tp-close { background:transparent; border:none; color:#5d6b82;
                    font:13px sans-serif; padding:0 8px 2px 8px; }
        #tp-close:hover { color:#ff6b81; }
        window { background:#0b1018; }
    """)
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css,
                                             Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    folded = {"small": False, "height": height}

    def fold(*_a):
        """Right click on the grip: fold to a bar and back, like the desktop widget."""
        folded["small"] = not folded["small"]
        if folded["small"]:
            folded["height"] = win.get_size()[1]
            win.resize(win.get_size()[0], 34)
        else:
            win.resize(win.get_size()[0], folded["height"])

    # The window has no title bar: this 14 px strip is what you drag it by.
    grip = Gtk.EventBox()
    grip.set_name("tp-grip")
    grip.set_size_request(-1, 14)
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
    hint = Gtk.Label(label="⠿ TokenPulse")
    hint.set_xalign(0.0)
    hint.set_hexpand(True)
    close = Gtk.Button(label="×")
    close.set_name("tp-close")
    close.set_relief(Gtk.ReliefStyle.NONE)
    close.set_can_focus(False)
    close.connect("clicked", lambda *_: win.close())
    row.pack_start(hint, True, True, 0)
    row.pack_end(close, False, False, 0)
    grip.add(row)

    def on_press(_w, event):
        if event.button == 1:
            win.begin_move_drag(event.button, int(event.x_root), int(event.y_root), event.time)
        elif event.button == 3:
            fold()
        return True

    grip.connect("button-press-event", on_press)
    for child in row.get_children():
        if isinstance(child, Gtk.Label):
            child.connect("button-press-event", on_press)
    box.pack_start(grip, False, False, 0)

    manager = WebKit2.UserContentManager()
    manager.add_script(WebKit2.UserScript.new(
        BOOT_JS, WebKit2.UserContentInjectedFrames.TOP_FRAME,
        WebKit2.UserScriptInjectionTime.START, None, None))
    view = WebKit2.WebView.new_with_user_content_manager(manager)
    settings = view.get_settings()
    settings.set_enable_developer_extras(False)
    view.load_uri(page_url(server, args.skin, args.mini))
    box.pack_start(view, True, True, 0)

    def on_key(_w, event):
        if event.keyval == Gdk.KEY_Escape:
            win.close()
            return True
        return False

    win.connect("key-press-event", on_key)
    win.add(box)
    win.show_all()

    if args.pos:
        win.move(*parse_wh(args.pos, (0, 60)))
    else:
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        win.move(max(0, monitor.get_geometry().width - width - 24), 60)

    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
