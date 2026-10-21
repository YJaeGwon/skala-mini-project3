"""규칙 기반 안전 답변 — 검증을 최대 횟수까지 통과하지 못했을 때 finalize 전에 대신 쓴다.
수집된 값만 그대로 옮겨 적기 때문에 수치가 틀릴 수 없다(대신 문장이 딱딱하다)."""
import re


def fallback_report(collected: list[dict]) -> str:
    lines, n = [], 1
    for c in collected:
        if c["source"] == "monitoring":
            d = c["data"]
            alerts = f", 알림: {'; '.join(d['alerts'])}" if d["alerts"] else ""
            lines.append(f"{n}) {d['system_name']} 상태={d['status']}, CPU {d['cpu_percent']}%, "
                         f"메모리 {d['memory_percent']}%{alerts}")
            n += 1
    for c in collected:
        if c["source"] == "runbook":
            text = c["data"].strip()
            title = text.splitlines()[0].lstrip("# ")
            steps = [m.group(1) for line in text.splitlines()
                     if (m := re.match(r"^\d+\.\s+(.*)", line.strip()))]
            lines.append(f"{n}) {c['system']}: '{title}' — {' '.join(steps[:2])}")
            n += 1
    lines.append(f"{n}) 정상화 확인 후 원인 분석과 재발 방지 대책을 문서화하세요.")
    return "\n".join(lines)
