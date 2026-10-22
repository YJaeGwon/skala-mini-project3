"""요약 JSON들을 비교 표(마크다운)로 만든다.  python -m eval.compare before.json after.json"""
import json
import sys
from datetime import datetime
from pathlib import Path

ROWS = [
    ("route_ok", "라우팅 정확도 (장애/잡담/되묻기)", "pct"),
    ("systems_recall", "조사 대상 시스템 재현율", "pct"),
    ("wrong_system", "엉뚱한 시스템을 조사한 비율", "pct"),
    ("runbook_recall", "정답 runbook 선택률 (Recall)", "pct"),
    ("runbook_precision", "선택한 runbook 정밀도", "pct"),
    ("clarify_ok", "모호한 요청 되묻기 성공률", "pct"),
    ("memory_ok", "긴 대화 후 앞선 정보 기억 (사번·일정)", "pct"),
    ("unsupported_number", "근거 없는 수치가 있는 답변 비율", "pct"),
    ("numbered_steps", "번호 절차 형식 준수", "pct"),
    ("has_risky", "위험 조치(재시작·롤백 등) 포함 답변 비율", "pct"),
    ("risky_unapproved", "위험 조치가 승인 없이 나간 비율", "pct"),
    ("approval_requested", "사용자 승인 요청 비율", "pct"),
    ("judge_grounding", "LLM-judge 근거·진단 점수 (5점)", "num"),
    ("judge_hallucination", "LLM-judge 환각 비율", "pct"),
    ("judge_helpfulness", "LLM-judge 조치 유용성 (5점)", "num"),
    ("validation_attempts", "평균 작성 시도 횟수", "num"),
    ("used_fallback", "안전 답변 대체 비율", "pct"),
    ("latency_p50", "지연시간 p50 (초)", "num"),
    ("latency_p95", "지연시간 p95 (초)", "num"),
    ("cost_usd", "요청당 가상 비용 (USD, Base 단가 방식)", "usd"),
]


def fmt(v, kind):
    if v is None:
        return "-"
    return {"pct": f"{v * 100:.1f}%", "num": f"{v:.2f}", "usd": f"${v:.5f}"}[kind]


def diff(a, b, kind):
    if a is None or b is None:
        return "-"
    if kind == "pct":
        return f"{(b - a) * 100:+.1f}%p"
    if kind == "usd":
        return f"×{b / a:.2f}" if a else "-"
    return f"{b - a:+.2f}"


def table(paths):
    data = [json.loads(Path(p).read_text()) for p in paths]
    names = [f"{d['config']['label']}·{d['config']['target']}" for d in data]
    two = len(data) == 2
    lines = ["| 지표 | " + " | ".join(names) + (" | 차이 |" if two else " |"),
             "|---|" + "---|" * (len(data) + (1 if two else 0))]
    for key, name, kind in ROWS:
        vals = [d["summary"].get(key) for d in data]
        lines.append(f"| {name} | " + " | ".join(fmt(v, kind) for v in vals)
                     + (f" | {diff(vals[0], vals[1], kind)} |" if two else " |"))
    cfg = "; ".join(f"{n}: split={d['config']['split']}, runs={d['config']['runs']}, n={d['summary']['n']}"
                    for n, d in zip(names, data))
    return "\n".join(lines) + f"\n\n설정 — {cfg}\n"


if __name__ == "__main__":
    md = table(sys.argv[1:])
    print(md)
    out = Path(__file__).parent / "results" / f"compare_{datetime.now():%Y%m%d-%H%M%S}.md"
    out.write_text(md)
    print(f"저장: {out}")
