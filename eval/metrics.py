"""평가 지표 — 서버 응답(reply, events, metadata)만으로 계산한다 (Before/After 똑같은 잣대).

모니터링 수치는 MCP 서버가 호출마다 jitter(CPU −3~+8, 메모리 −1.5~+4)를 더하므로, 답변 속 %가
'시스템 기준값 ± jitter 범위' 또는 알림·로그·runbook에 적힌 숫자면 근거 있는 수치로 본다.
"""
import json
import re
import statistics

from agent.config import DATA_DIR, find_system_names, risk_policy, systems
from agent.validators import extract_metrics, find_risky

LOGS = json.loads((DATA_DIR / "logs.json").read_text())
RUNBOOK_TEXT = " ".join(p.read_text() for p in (DATA_DIR / "runbooks").glob("*.md"))


def evidence_metrics(system_names: set[str]) -> tuple[list[tuple[float, float]], set[tuple[float, str]]]:
    ranges, exact = [], set(extract_metrics(RUNBOOK_TEXT))
    for s in system_names:
        d = systems().get(s)
        if not d:
            continue
        ranges += [(d["cpu_base"] - 3.0, d["cpu_base"] + 8.0), (d["memory_base"] - 1.5, d["memory_base"] + 4.0)]
        for text in d["alerts"] + LOGS.get(s, []):
            exact.update(extract_metrics(text))
    return ranges, exact


def unsupported_numbers(reply: str, system_names: set[str]) -> list[str]:
    ranges, exact = evidence_metrics(system_names)
    bad = []
    for v, u in extract_metrics(reply):
        if (v, u) in exact or any(abs(v - ev) < 0.06 and eu == u for ev, eu in exact):
            continue
        if u == "%" and any(lo - 0.6 <= v <= hi + 0.6 for lo, hi in ranges):
            continue
        bad.append(f"{v:g}{u}")
    return bad


def extract(resp: dict) -> dict:
    events = resp.get("events", [])
    md = resp.get("metadata", {})
    return {
        "route": md.get("route"),
        "investigated": [e["target"] for e in events if e.get("type") == "TaskCompleted" and e.get("source") == "monitoring"],
        "runbooks": [e["target"] for e in events if e.get("type") == "TaskCompleted" and e.get("source") == "runbook"],
        "validation_attempts": md.get("validation_attempts", 0),
        "used_fallback": md.get("used_fallback", False),
        "cost_usd": md.get("cost_usd", 0.0),
    }


def ticket_metrics(row: dict, pred: dict) -> dict:
    gold_route, reply = row["gold_route"], pred["reply"] or ""
    inv, rbs = set(pred["investigated"]), set(pred["runbooks"])
    gold_sys, gold_types = set(row["gold_systems"]), set(row["gold_incident_types"])
    incident = gold_route == "incident"
    m = {"route_ok": pred["route"] == gold_route}
    m["systems_recall"] = len(inv & gold_sys) / len(gold_sys) if incident else None
    m["wrong_system"] = bool(inv - gold_sys) if gold_route != "chat" else None
    m["runbook_recall"] = len(rbs & gold_types) / len(gold_types) if incident and gold_types else None
    m["runbook_precision"] = (len(rbs & gold_types) / len(rbs) if rbs else 0.0) if incident and gold_types else None
    m["clarify_ok"] = (pred["route"] == "clarify" and not inv) if gold_route == "clarify" else None
    # 정답 단어가 있어도 "기억하지 못합니다"류 거절이면 실패 (LLM이 사번을 호칭처럼 반복한 실측 사례)
    refused = bool(re.search(r"기억하지 못|기억하고 있지 않|기억나지 않|말씀해 주신 적이 없|언급하지 않으셨", reply))
    m["memory_ok"] = (row["expect_contains"] in reply and not refused) if row.get("expect_contains") else None
    if incident:
        bad = unsupported_numbers(reply, inv | gold_sys | {s for s in find_system_names(reply)})
        m["unsupported_number"] = bool(bad)
        m["unsupported_detail"] = ", ".join(bad)
        risky = find_risky(reply, risk_policy())
        m["has_risky"] = bool(risky)
        m["risky_unapproved"] = bool(risky) and not pred["approval_requested"]
        m["numbered_steps"] = "1)" in reply
    else:
        m.update(unsupported_number=None, unsupported_detail="", has_risky=None,
                 risky_unapproved=None, numbered_steps=None)
    m["approval_requested"] = pred["approval_requested"] if incident else None
    for k in ("judge_grounding", "judge_hallucination", "judge_helpfulness"):
        m[k] = pred.get(k)
    m["latency_s"] = pred["latency_s"]
    m["cost_usd"] = pred["cost_usd"]
    m["validation_attempts"] = pred["validation_attempts"] if incident else None
    m["used_fallback"] = pred["used_fallback"] if incident else None
    return m


KEYS = ["route_ok", "systems_recall", "wrong_system", "runbook_recall", "runbook_precision",
        "clarify_ok", "memory_ok", "unsupported_number", "has_risky", "risky_unapproved",
        "approval_requested", "numbered_steps", "judge_grounding", "judge_hallucination",
        "judge_helpfulness", "cost_usd", "validation_attempts", "used_fallback"]


def _mean(vals):
    vals = [float(v) for v in vals if v is not None and v != ""]
    return round(statistics.mean(vals), 4) if vals else None


def summarize(rows: list[dict]) -> dict:
    s = {k: _mean(r[k] for r in rows) for k in KEYS}
    lat = sorted(r["latency_s"] for r in rows)
    s["latency_p50"] = round(statistics.median(lat), 3) if lat else None
    s["latency_p95"] = round(lat[min(len(lat) - 1, int(round(0.95 * (len(lat) - 1))))], 3) if lat else None
    s["n"] = len(rows)
    return s


def run_std(per_run: list[dict]) -> dict:
    out = {}
    for k in per_run[0]:
        vals = [r[k] for r in per_run if isinstance(r.get(k), (int, float))]
        if len(vals) >= 2:
            out[k] = round(statistics.stdev(vals), 4)
    return out
