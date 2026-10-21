"""여러 평가 결과(CSV)를 '질문 단위'로 합친 요약.

평가용 질문(18개 × 3회)과 처음 보는 질문(20개 × 1회)을 합칠 때, 행을 그대로 합치면 평가용
질문이 3배로 반영된다. 그래서 질문마다 회차 평균을 먼저 내고, 질문 하나 = 같은 무게로 평균한다.

  python -m eval.combine before eval/results/final2_before_*.csv eval/results/holdout_before_*.csv
"""
import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

KEYS = ["route_ok", "systems_recall", "wrong_system", "runbook_recall", "runbook_precision",
        "clarify_ok", "memory_ok", "unsupported_number", "has_risky", "risky_unapproved",
        "approval_requested", "judge_grounding", "judge_hallucination", "judge_helpfulness",
        "cost_usd", "latency_s"]


def _num(v):
    if v in ("", None):
        return None
    if v in ("True", "False"):
        return 1.0 if v == "True" else 0.0
    return float(v)


def combine(paths: list[str]) -> dict:
    per_q = defaultdict(lambda: defaultdict(list))
    for i, p in enumerate(paths):
        for r in csv.DictReader(open(p)):
            qid = f"{i}:{r['id']}"           # 파일이 다르면 같은 id라도 다른 질문
            for k in KEYS:
                if (v := _num(r.get(k))) is not None:
                    per_q[qid][k].append(v)
    out = {}
    for k in KEYS:
        vals = [statistics.mean(q[k]) for q in per_q.values() if q[k]]
        out[k] = round(statistics.mean(vals), 4) if vals else None
    lat = sorted(statistics.mean(q["latency_s"]) for q in per_q.values() if q["latency_s"])
    out["latency_p50"] = round(statistics.median(lat), 3)
    out["questions"] = len(per_q)
    return out


if __name__ == "__main__":
    label, *paths = sys.argv[1:]
    result = combine(paths)
    print(json.dumps({"label": label, "files": paths, **result}, ensure_ascii=False, indent=2))
