#!/usr/bin/env bash
# 一键启动智能旅行助手：依赖检查 → 可选 --setup 自动准备 RAG → 双终端启动 → 打开浏览器
# 用法：bash scripts/dev.sh [--setup]（首次运行加 --setup：自动下载模型/生成语料/入库）
set -euo pipefail
cd "$(dirname "$0")/.."

SETUP=false
[[ "${1:-}" == "--setup" ]] && SETUP=true

fail() { echo "❌ $1" >&2; exit 1; }

[[ -d backend/.venv ]] || fail '后端未初始化：cd backend && python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"'
[[ -d frontend/node_modules ]] || fail "前端未初始化：cd frontend && npm install"
[[ -n "${DEEPSEEK_API_KEY:-}" ]] || fail "未配置 DEEPSEEK_API_KEY：export DEEPSEEK_API_KEY=sk-xxx（DeepSeek 平台申请）"

RAG_READY=false
[[ -f backend/data/poi_corpus.jsonl && -n "$(ls -A backend/data/chroma 2>/dev/null)" ]] && RAG_READY=true

if [[ "$SETUP" == true ]]; then
  echo "==> 准备 RAG 知识库（下载 BGE 模型 / 生成 34 省语料 / 向量入库）…"
  (cd backend && .venv/Scripts/python -m app.rag.download_model \
    && .venv/Scripts/python -m app.rag.generate \
    && .venv/Scripts/python -m app.rag.ingest)
  RAG_READY=true
fi

[[ "$RAG_READY" == true ]] || fail "RAG 知识库未就绪：首次运行请执行 bash scripts/dev.sh --setup"

cleanup() {
  [[ -n "${UV_PID:-}" ]] && kill "$UV_PID" 2>/dev/null || true
  [[ -n "${VITE_PID:-}" ]] && kill "$VITE_PID" 2>/dev/null || true
}
trap cleanup EXIT

echo "==> 启动后端 http://localhost:8000 与前端 http://localhost:5173（Ctrl+C 退出并停止两端）"
(cd backend && .venv/Scripts/uvicorn app.main:app --port 8000) & UV_PID=$!
(cd frontend && npm run dev) & VITE_PID=$!
sleep 4
cmd //c start http://localhost:5173
wait
