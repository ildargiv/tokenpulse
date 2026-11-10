#!/usr/bin/env bash
# Виджет TokenPulse на Linux без tkinter: та же веб-страница со скинами, но в собственном
# окне без рамки и поверх остальных окон (GTK + WebKit2).
#   ./start-widget-web.sh                              http://127.0.0.1:8787
#   ./start-widget-web.sh http://192.168.31.30:8787   агент на другом компьютере
#   ./start-widget-web.sh --skin cockpit               пульс, консоль, спокойный, приборы, эфир, збру
#   ./start-widget-web.sh --mini                       компактная полоска
cd "$(dirname "$0")" || exit 1

SERVER=""
case "${1:-}" in
    "")                             ;;      # default: this computer
    -*)                             ;;      # an option, not an address
    *) SERVER="$1"; shift ;;                # first argument may be the agent address
esac
[ -n "$SERVER" ] || SERVER="http://127.0.0.1:8787"
case "$SERVER" in http*) ;; *) SERVER="http://$SERVER" ;; esac

# Один экземпляр: повторный клик по ярлыку не должен открывать второе окно.
LOCK="${XDG_RUNTIME_DIR:-/tmp}/tokenpulse-widget-web.lock"
if command -v flock >/dev/null 2>&1; then
    exec 9>"$LOCK"
    if ! flock -n 9; then
        echo "Виджет уже запущен"
        exit 0
    fi
fi

if ! python3 -c "import gi" 2>/dev/null; then
    echo "Нет PyGObject/WebKit2. Установка: sudo apt install python3-gi gir1.2-webkit2-4.0" >&2
    echo "Или обычный виджет: ./start-widget.sh" >&2
    exit 1
fi

exec python3 widget_web.py --server "$SERVER" "$@"
