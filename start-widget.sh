#!/usr/bin/env bash
# Запуск десктоп-виджета. Локальный Tkinter подхватывается из ~/.local/opt/tk,
# если системный python3-tk не установлен.
cd "$(dirname "$0")" || exit 1

# Один экземпляр: повторный клик по ярлыку не должен открывать второе окно.
LOCK="${XDG_RUNTIME_DIR:-/tmp}/tokenpulse-widget.lock"
if command -v flock >/dev/null 2>&1; then
    exec 9>"$LOCK"
    if ! flock -n 9; then
        echo "Виджет уже запущен"
        exit 0
    fi
fi

TKROOT="${TK_ROOT:-$HOME/.local/opt/tk/usr}"
if ! python3 -c "import tkinter" 2>/dev/null; then
    if [ -d "$TKROOT/lib/python3.10/tkinter" ]; then
        export PYTHONPATH="$TKROOT/lib/python3.10:$TKROOT/lib/python3.10/lib-dynload${PYTHONPATH:+:$PYTHONPATH}"
        export LD_LIBRARY_PATH="$TKROOT/lib/x86_64-linux-gnu:$TKROOT/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
        export TK_LIBRARY="$TKROOT/share/tcltk/tk8.6"
        export TCL_LIBRARY="${TCL_LIBRARY:-/usr/share/tcltk/tcl8.6}"
    else
        echo "Нет tkinter. Установите: sudo apt install python3-tk" >&2
        exit 1
    fi
fi
exec python3 widget.py "$@"
