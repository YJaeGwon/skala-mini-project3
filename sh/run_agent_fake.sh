#!/usr/bin/env bash
# fake 모드(외부 호출·비용 없음)로 백엔드 기동 — 데모·동작 확인용. 종료: Ctrl+C
set -euo pipefail
cd "$(dirname "$0")/.."
[ -x ".venv/bin/python3" ] && export PATH="$PWD/.venv/bin:$PATH"
lsof -ti:8100 | xargs kill -9 2>/dev/null || true
rm -f session.db checkpoints.db checkpoints.db-*
trap 'lsof -ti:8100 | xargs kill -9 2>/dev/null || true' EXIT
LANGCHAIN_TRACING_V2=false LLM_BACKEND=fake SUPERVISOR_VERSION=v2 python3 server.py &
for _ in $(seq 1 60); do curl -s http://127.0.0.1:8100/health >/dev/null 2>&1 && break; sleep 0.5; done
curl -s http://127.0.0.1:8100/health | python3 -m json.tool --no-ensure-ascii
echo "백엔드(fake)가 떠 있습니다. 새 터미널에서 bash sh/run_frontend.sh → http://localhost:8600"
wait
