#!/usr/bin/env bash
#
# [추가2] Before/After 평가 — 원본 Base 코드(Before) vs 과제1 개선판(After), 같은 질문·같은 모델.
#   bash sh/run_eval.sh          # test split × 3회 + gpt-4o 채점 (OpenAI 과금, 1달러 미만 추정)
#   RUNS=1 bash sh/run_eval.sh   # 빠르게 1회만
# 결과: eval/results/*.csv, *.json, compare_*.md
#
set -euo pipefail
cd "$(dirname "$0")/.."
RUNS="${RUNS:-3}"
PY=./.venv/bin/python3
read -r -p "OpenAI로 Before/After 평가를 실행할까요? (test × ${RUNS}회, 과금) [y/N] " ans
[[ "$ans" =~ ^[Yy]$ ]] || exit 0
LABEL="run$(date +%H%M)"
$PY -m eval.run_eval --target before --split test --runs "$RUNS" --judge openai --label "$LABEL"
$PY -m eval.run_eval --target after --split test --runs "$RUNS" --judge openai --label "$LABEL"
$PY -m eval.compare $(ls -t eval/results/${LABEL}_before_*.json | head -1) $(ls -t eval/results/${LABEL}_after_*.json | head -1)
