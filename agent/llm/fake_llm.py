"""LLM_BACKEND=fake — 외부 호출 없는 결정론적 LLM (테스트·오프라인 데모용). Base fake_llm.py 확장.

- route: Base의 정규식 규칙 + 운영 키워드
- resolve_systems: 별칭만으로 찾고, 못 찾으면 빈 리스트(→ 되묻기)
- write: Base처럼 1차 초안은 일부러 짧게(검증 반려 재현), 2차부터 수집된 사실로 구조화된 답변
- summarize: 사용자 발화를 이어 붙인 요약 (이름 같은 사실이 보존되는지 테스트용)
"""
import re

from ..config import find_systems_by_alias


def _usage(name: str, usd_per_1k: float, prompt: str, completion: str) -> dict:
    tokens = (len(prompt) + len(completion)) // 4 + 1
    return {"model": name, "tokens": tokens, "usd": round(tokens / 1000 * usd_per_1k, 6)}


INCIDENT_RE = re.compile(r"장애|진단|다운|지연|느려|느린|급증|타임아웃|에러|오류|실패|안 돼|안돼|부족|"
                         r"메모리|CPU|cpu|디스크|로그|상태|확인|인증서|알림|이상|incident|티켓")


class FakeFastLLM:
    def __init__(self, name: str = "fake-fast", usd_per_1k_tokens: float = 0.00015):
        self.name, self.usd_per_1k = name, usd_per_1k_tokens

    async def route(self, query, history, summary=""):
        result = {"route": "incident" if INCIDENT_RE.search(query) else "chat",
                  "needs_analysis": bool(re.search(r"공통|비교|둘 다|같이", query))}
        return result, _usage(self.name, self.usd_per_1k, query, str(result))

    async def resolve_systems(self, query, history, summary, catalog):
        systems = find_systems_by_alias(query)
        return systems, _usage(self.name, self.usd_per_1k, query + catalog, str(systems))

    async def analyze(self, collected):
        mon = [c["data"] for c in collected if c["source"] == "monitoring"]
        degraded = [d["system_name"] for d in mon if d.get("status") != "healthy"]
        summary = (f"{', '.join(degraded)} 복수 시스템이 동시에 저하됨 — 공유 의존성 등 공통 원인이 의심됨"
                   if len(degraded) >= 2 else "특이 패턴 없음")
        return summary, _usage(self.name, self.usd_per_1k, str(collected), summary)

    async def summarize(self, previous, messages):
        users = [m["content"] for m in messages if m["role"] == "user"]
        summary = " / ".join(x for x in [previous] + users if x)[:600]
        return summary, _usage(self.name, self.usd_per_1k, str(messages), summary)

    async def chat(self, query, history, summary="", on_token=None):
        reply = "안녕하세요! 운영 지원 에이전트입니다. 장애나 시스템 상태를 물어보세요."
        if re.search(r"이름이 뭐", query):
            for text in [summary] + [m.get("content", "") for m in reversed(history)]:
                m = re.search(r"제 이름은 (\S+?)입니다", text or "")
                if m:
                    reply = f"{m.group(1)}님이라고 말씀하셨어요. 무엇을 도와드릴까요?"
                    break
        if on_token:
            on_token(reply)
        return reply, _usage(self.name, self.usd_per_1k, query + summary, reply)


class FakeQualityLLM:
    def __init__(self, name: str = "fake-quality", usd_per_1k_tokens: float = 0.005):
        self.name, self.usd_per_1k = name, usd_per_1k_tokens

    async def write(self, query, collected, procedure, attempt, feedback, on_token=None):
        if attempt == 1:
            draft = "재시작하면 됩니다."
        else:
            lines, n = [], 1
            for c in collected:
                if c["source"] == "monitoring":
                    d = c["data"]
                    lines.append(f"{n}) {d['system_name']}: 상태={d['status']}, CPU {d['cpu_percent']}%, "
                                 f"메모리 {d['memory_percent']}% (알림 {len(d['alerts'])}건)")
                    n += 1
            for c in collected:
                if c["source"] == "runbook":
                    steps = [m.group(1) for line in c["data"].splitlines()
                             if (m := re.match(r"^\d+\.\s+(.*)", line.strip()))]
                    title = c["data"].strip().splitlines()[0].lstrip("# ")
                    lines.append(f"{n}) {c['system']}는 '{title}'에 따라 {' '.join(steps[1:3])}")
                    n += 1
            lines.append(f"{n}) 정상화 확인 후 원인 분석과 재발 방지 대책을 문서화하세요.")
            draft = "\n".join(lines)
        if on_token:
            on_token(draft)
        return draft, _usage(self.name, self.usd_per_1k, query + str(collected), draft)


class FakeJudgeLLM:
    name = "fake-judge"

    async def judge(self, query, answer, gold_text):
        return ({"grounding": 3, "hallucination": False, "helpfulness": 3, "reason": "fake"},
                {"model": self.name, "tokens": 0, "usd": 0.0})
