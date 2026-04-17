#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
API_DIR="$ROOT_DIR/apps/api"
WEB_DIR="$ROOT_DIR/apps/web"
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-4000}"
API_LOG="$ROOT_DIR/.dev-api.log"

cleanup() {
  if [[ -n "${API_PID:-}" ]] && kill -0 "$API_PID" >/dev/null 2>&1; then
    kill "$API_PID" >/dev/null 2>&1 || true
  fi
}

trap cleanup EXIT INT TERM

echo "[1/6] 检查 Python 虚拟环境..."
if [[ ! -d "$API_DIR/.venv" ]]; then
  python3 -m venv "$API_DIR/.venv"
fi

source "$API_DIR/.venv/bin/activate"

echo "[2/6] 安装 API 依赖..."
python -m pip install --upgrade pip >/dev/null
pip install -r "$API_DIR/requirements.txt" >/dev/null

echo "[3/6] 跳过演示数据初始化..."
cd "$API_DIR"

echo "[4/6] 启动 API 服务..."
uvicorn app.main:app --reload --port "$API_PORT" >"$API_LOG" 2>&1 &
API_PID=$!

sleep 2

if ! kill -0 "$API_PID" >/dev/null 2>&1; then
  echo "API 启动失败，请查看日志：$API_LOG"
  exit 1
fi

cd "$WEB_DIR"

echo "[5/6] 安装 Web 依赖..."
npm install >/dev/null

echo "[6/6] 启动 Web 服务..."
echo "Web: http://localhost:$WEB_PORT"
echo "API: http://localhost:$API_PORT"
echo "API Docs: http://localhost:$API_PORT/docs"
echo "API 日志: $API_LOG"

npm run dev -- --port "$WEB_PORT"
