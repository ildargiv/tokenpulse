#!/usr/bin/env bash
# Запуск агента метрик (сервер с GPU). Открытый JSON API + веб-страница.
cd "$(dirname "$0")" || exit 1

# Второй экземпляр не нужен: он всё равно не сможет занять порт.
PORT="${MONITOR_PORT:-8787}"
prev=""
for a in "$@"; do
    if [ "$prev" = "--port" ]; then PORT="$a"; fi
    case "$a" in --port=*) PORT="${a#*=}" ;; esac
    prev="$a"
done
if command -v curl >/dev/null 2>&1 && \
   curl -fsS -m 2 "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
    echo "Агент уже работает: http://127.0.0.1:$PORT/"
    exit 0
fi

exec python3 agent.py "$@"
