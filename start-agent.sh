#!/usr/bin/env bash
# Запуск агента метрик (сервер с GPU). Открытый JSON API + веб-страница.
cd "$(dirname "$0")" || exit 1
exec python3 agent.py "$@"
