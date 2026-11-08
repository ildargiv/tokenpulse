#!/usr/bin/env python3
"""Remove the title bar and border of the TokenPulse monitor window (Windows, stdlib only).

Run it after the monitor window is open (start-monitor-frameless.bat does that).
Afterwards the window can be dragged by its top 40 px (leave the right 120 px: the
corner buttons live there). Close it with Alt+F4 or from the taskbar.
Run `python frameless.py --restore` to give the frame back.
"""
import ctypes, sys, time
from ctypes import wintypes as W

if sys.platform != "win32":
    sys.exit("frameless.py works on Windows only")

u, k = ctypes.windll.user32, ctypes.windll.kernel32
GWL_STYLE = -16
WS_CAPTION, WS_THICKFRAME, WS_SYSMENU = 0x00C00000, 0x00040000, 0x00080000
SWP = 0x0001 | 0x0002 | 0x0004 | 0x0020  # NOSIZE NOMOVE NOZORDER FRAMECHANGED
u.GetWindowLongW.restype = ctypes.c_long
u.GetAsyncKeyState.restype = ctypes.c_short
restore = "--restore" in sys.argv


def find():
    found = []
    cb = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)

    def each(h, _):
        if not u.IsWindowVisible(h):
            return True
        cls = ctypes.create_unicode_buffer(64); u.GetClassNameW(h, cls, 64)
        n = u.GetWindowTextLengthW(h)
        buf = ctypes.create_unicode_buffer(n + 1); u.GetWindowTextW(h, buf, n + 1)
        if cls.value == "Chrome_WidgetWin_1" and ("TokenPulse" in buf.value or "ток/с" in buf.value):
            found.append(h)
        return True
    u.EnumWindows(cb(each), 0)
    return found


def strip(h):
    st = u.GetWindowLongW(h, GWL_STYLE)
    bits = WS_CAPTION | WS_THICKFRAME | WS_SYSMENU
    st = (st | bits) if restore else (st & ~bits)
    u.SetWindowLongW(h, GWL_STYLE, st)
    u.SetWindowPos(h, 0, 0, 0, 0, 0, SWP)


hs = []
for _ in range(40):
    hs = find()
    if hs:
        break
    time.sleep(0.5)
if not hs:
    sys.exit("monitor window not found: start the monitor first")
for h in hs:
    strip(h)
print(("frame restored" if restore else "frame removed") + f" on {len(hs)} window(s)")
if restore:
    sys.exit(0)

# drag by the top strip, as long as the window exists
pt, rc = W.POINT(), W.RECT()
drag = None
while u.IsWindow(hs[0]):
    down = u.GetAsyncKeyState(0x01) & 0x8000
    u.GetCursorPos(ctypes.byref(pt)); u.GetWindowRect(hs[0], ctypes.byref(rc))
    if down and drag is None:
        if rc.left <= pt.x < rc.right - 120 and rc.top <= pt.y < rc.top + 40:
            drag = (pt.x - rc.left, pt.y - rc.top, pt.x, pt.y, False)
        else:
            drag = False
    elif down and drag:
        ox, oy, sx, sy, moving = drag
        if moving or abs(pt.x - sx) + abs(pt.y - sy) > 4:
            u.SetWindowPos(hs[0], 0, pt.x - ox, pt.y - oy, 0, 0, 0x0001 | 0x0004 | 0x0010)
            drag = (ox, oy, sx, sy, True)
    elif not down:
        drag = None
    time.sleep(0.01)
