#!/usr/bin/env bash
# 커밋 전에 실제 API 키가 섞여 들어가지 않았는지 검사한다 (.env, .venv는 검사 대상 아님).
set -uo pipefail
cd "$(dirname "$0")/.."
if grep -rnE "sk-(proj-)?[A-Za-z0-9_-]{20,}|lsv2_(pt|sk)_[A-Za-z0-9]{20,}" . \
        --exclude-dir=.venv --exclude-dir=.git --exclude-dir=data/vectordb --exclude=.env; then
    echo "❌ 실제 키로 보이는 문자열이 있습니다 — 커밋하지 마세요."; exit 1
fi
echo "✅ 키 노출 없음"
