#!/usr/bin/env bash
# [추가5] 단위 테스트 — fake LLM + FakeMCP라 외부 호출·비용 없음
set -euo pipefail
cd "$(dirname "$0")/.."
./.venv/bin/python3 -m pytest -q "$@"
