#!/usr/bin/env bash
# 启动后端开发服务。Windows + Git Bash / WSL 下可直接 bash start.sh
# 端口默认 8000，被占用请改 APP_PORT
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "[start.sh] .env 不存在，已复制 .env.example，请填入真实 key 后再启动"
  cp .env.example .env
fi

# 端口探测，被占用就 +1
PORT="${APP_PORT:-8000}"
while lsof -i ":$PORT" >/dev/null 2>&1; do
  PORT=$((PORT + 1))
done
echo "[start.sh] 使用端口 $PORT"

exec python3 -m uvicorn backend.app:app --reload --host 0.0.0.0 --port "$PORT"