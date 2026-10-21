"""LLM 프롬프트 모음 — openai/ollama가 같은 프롬프트를 공유한다.

Base는 같은 프롬프트가 ollama_llm.py와 openai_llm.py에 각각 복사돼 있었다.
"""
import json
import re

ROUTE_SYSTEM = (
    "당신은 ICT 운영 지원 라우터다. 사용자 요청을 분류해 JSON 객체로만 답하라. "
    '스키마: {"route": "chat" 또는 "incident", "needs_analysis": true 또는 false}. '
    "장애·성능 저하·지연·에러·모니터링·로그·서비스 상태 확인 등 운영 이슈면 incident, "
    "인사·잡담·이름·일반 질문이면 chat. 이전 대화에서 이어지는 장애 질문('그 서비스는?')도 incident. "
    "needs_analysis는 여러 시스템을 비교해 공통 원인을 찾아야 할 때만 true.")

RESOLVE_SYSTEM = (
    "당신은 운영 장애 접수 담당이다. 아래 시스템 목록(이름: 설명)에서 사용자가 문제를 말하는 "
    "대상 시스템을 골라 JSON 객체로만 답하라. 스키마: {\"systems\": [시스템 이름, ...]}. "
    "이전 대화에서 이어지는 질문('그 서비스', '아까 그거')이면 이전 대화의 시스템을 고른다. "
    "목록에 없는 시스템이거나 어떤 시스템인지 확실하지 않으면 빈 리스트를 돌려준다(추측 금지).")

CHAT_SYSTEM = ("당신은 간결한 한국어 운영 지원 비서다. 한두 문장으로 답하라. "
               "대화 요약과 대화 이력에서 사용자가 밝힌 이름이 있으면 정확히 기억해 답하라.")

SUMMARIZE_SYSTEM = ("너는 대화 메모를 관리한다. '기존 요약'에 '새 대화'의 내용을 덧붙여 하나의 갱신된 요약을 "
                    "한국어로 써라. 기존 요약에 있던 사실(사용자 이름·사번·일정·언급한 시스템·진행 중인 장애와 조치)은 "
                    "하나도 빼지 말고 그대로 유지하라 — 새 대화가 잡담뿐이어도 기존 사실을 지우면 안 된다. "
                    "잡담은 한 줄로 줄이고, 전체 8문장 이내로 써라.")

ANALYZE_SYSTEM = ("당신은 ICT 운영 패턴 분석가다. 여러 시스템의 모니터링 결과와 로그를 비교해 "
                  "공통 원인이 의심되는 패턴이 있는지 한두 문장으로 짧게 답하라. "
                  "패턴이 없으면 '특이 패턴 없음'이라고만 답하라.")

WRITE_SYSTEM = """당신은 ICT 운영 보고 작성자다. 아래 '수집된 사실'만 사용해 한국어로 간결한 대응 보고를 작성하라.
규칙:
1) 반드시 '1) ... 2) ... 3) ...' 형식의 번호 절차로 답하라.
2) 수치(CPU %, 메모리 %, 지연시간 등)는 수집된 값을 그대로 인용하고, 수집되지 않은 수치는 쓰지 마라.
3) 시스템별로 어떤 runbook(대응 절차)을 따르는지 runbook 제목을 밝히고, 로그에서 확인된 근거를 함께 적어라.
4) 조사하지 않은 시스템에 대해서는 원인을 단정하지 마라.
5) 마크다운 제목 없이 평문으로 5~8줄 이내로 써라."""

JUDGE_SYSTEM = """당신은 ICT 운영 장애 대응 답변의 품질 평가자다. 사용자 질문, 에이전트 답변, 정답 정보(대상 시스템·장애 유형·모니터링 데이터·로그·정답 runbook)가 주어진다. JSON 객체로만 답하라.
- grounding (1~5): 5=정답 시스템을 조사하고 정답 장애 유형의 runbook 절차에 맞는 원인·조치를 제시함, 3=일부 시스템이나 장애 유형을 놓치거나 조치가 부분적으로 맞음, 1=엉뚱한 시스템·장애 유형을 진단함. 정답이 '되묻기'인 경우 대상 확인을 요청하면 5, 엉뚱한 시스템을 진단하면 1.
- hallucination (true/false): 정답 정보에 없는 수치·장애 사실·로그 내용을 지어냈으면 true. CPU/메모리 수치는 측정할 때마다 몇 % 달라질 수 있으니 기준값 근처면 정상이다. 로그를 언급하지 않은 것은 감점 사유가 아니다.
- helpfulness (1~5): 운영자가 바로 따라 할 수 있는 구체적인 단계인지
- reason: 판단 이유 한 문장"""


def parse_json(content: str) -> dict:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", content, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return {}


def render_history(history: list[dict], summary: str = "", limit: int = 10) -> str:
    lines = [f"(이전 대화 요약) {summary}"] if summary else []
    lines += [f"{m['role']}: {m['content']}" for m in history[-limit:]]
    return "\n".join(lines) or "(없음)"


def render_collected(collected: list[dict]) -> str:
    """write·analyze·검증이 같은 모양으로 보는 '수집된 사실'."""
    facts = []
    for c in collected:
        if c["source"] == "monitoring":
            d = c["data"]
            facts.append(f"- 모니터링 {d['system_name']}: 상태={d['status']}, CPU {d['cpu_percent']}%, "
                         f"메모리 {d['memory_percent']}%, 알림 {len(d['alerts'])}건 {d['alerts']}")
        elif c["source"] == "logs":
            lines = "\n".join(f"    {line}" for line in c["data"])
            facts.append(f"- 최근 로그 {c['system']}:\n{lines}")
        elif c["source"] == "runbook":
            facts.append(f"- runbook ({c['system']} → {c['incident_type']}):\n{c['data'].strip()}")
        elif c["source"] == "analysis":
            facts.append(f"- 패턴 분석: {c['data'].strip()}")
    return "\n".join(facts) or "(수집된 사실 없음)"
