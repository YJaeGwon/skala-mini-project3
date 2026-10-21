"""실제 LLM(openai / ollama) 역할별 래퍼 — 전송(clients.py) + 프롬프트(prompts.py) 조합.

[개선6] Base는 async 노드 안에서 동기 httpx.post를 불러 이벤트 루프를 막았고, OpenAI는
토큰 스트리밍을 하지 않았다. 여기서는 모든 호출이 비동기이고 답변은 토큰 단위로 흘려보낸다.
비용(usd)은 Before와 비교할 수 있도록 Base와 같은 방식(토큰 × 역할별 1k당 가상 단가)으로 계산한다.
"""
from langsmith import traceable

from .prompts import (ANALYZE_SYSTEM, CHAT_SYSTEM, JUDGE_SYSTEM, RESOLVE_SYSTEM, ROUTE_SYSTEM,
                      SUMMARIZE_SYSTEM, WRITE_SYSTEM, parse_json, render_collected,
                      render_history)


class _RealLLM:
    def __init__(self, client, usd_per_1k_tokens: float):
        self.client = client
        self.name = client.name
        self.usd_per_1k = usd_per_1k_tokens

    def _usage(self, tin: int, tout: int, prompt: str | None = None) -> dict:
        tokens = tin + tout
        usage = {"model": self.name, "tokens": tokens,
                 "usd": round(tokens / 1000 * self.usd_per_1k, 6)}
        if prompt:
            usage["prompt"] = prompt
        return usage


class RealFastLLM(_RealLLM):
    @traceable(run_type="llm", name="fast.route")
    async def route(self, query: str, history: list[dict], summary: str = "") -> tuple[dict, dict]:
        user = f"## 이전 대화\n{render_history(history, summary, 4)}\n\n## 사용자 요청\n{query}"
        content, tin, tout = await self.client.complete(ROUTE_SYSTEM, user, json_mode=True)
        raw = parse_json(content)
        result = {"route": raw.get("route") if raw.get("route") in ("chat", "incident") else "chat",
                  "needs_analysis": bool(raw.get("needs_analysis", False))}
        return result, self._usage(tin, tout)

    @traceable(run_type="llm", name="fast.resolve_systems")
    async def resolve_systems(self, query: str, history: list[dict], summary: str,
                              catalog: str) -> tuple[list[str], dict]:
        user = (f"## 시스템 목록\n{catalog}\n\n## 이전 대화\n{render_history(history, summary, 6)}\n\n"
                f"## 사용자 요청\n{query}")
        content, tin, tout = await self.client.complete(RESOLVE_SYSTEM, user, json_mode=True)
        systems = parse_json(content).get("systems") or []
        return [s for s in systems if isinstance(s, str)], self._usage(tin, tout)

    @traceable(run_type="llm", name="fast.analyze")
    async def analyze(self, collected: list[dict]) -> tuple[str, dict]:
        content, tin, tout = await self.client.complete(ANALYZE_SYSTEM, render_collected(collected))
        return content, self._usage(tin, tout)

    @traceable(run_type="llm", name="fast.summarize")
    async def summarize(self, previous: str, messages: list[dict]) -> tuple[str, dict]:
        user = (f"## 기존 요약\n{previous or '(없음)'}\n\n## 새로 요약할 대화\n"
                + "\n".join(f"{m['role']}: {m['content']}" for m in messages))
        content, tin, tout = await self.client.complete(SUMMARIZE_SYSTEM, user)
        return content.strip(), self._usage(tin, tout)

    @traceable(run_type="llm", name="fast.chat")
    async def chat(self, query: str, history: list[dict], summary: str = "",
                   on_token=None) -> tuple[str, dict]:
        user = f"## 지금까지의 대화\n{render_history(history, summary)}\n\n## 사용자의 새 메시지\n{query}"
        content, tin, tout = await self.client.stream(CHAT_SYSTEM, user, on_token)
        return content, self._usage(tin, tout, f"[SYSTEM]\n{CHAT_SYSTEM}\n\n[USER]\n{user}")


class RealQualityLLM(_RealLLM):
    @traceable(run_type="llm", name="quality.write")
    async def write(self, query: str, collected: list[dict], procedure: str, attempt: int,
                    feedback: str | None, on_token=None) -> tuple[str, dict]:
        user = (f"## 표준 진단 절차\n{procedure}\n\n## 사용자 요청\n{query}\n\n"
                f"## 수집된 사실\n{render_collected(collected)}")
        if feedback:
            user += f"\n\n## 이전 초안이 반려된 이유 (반드시 고쳐서 다시 작성)\n{feedback}"
        content, tin, tout = await self.client.stream(WRITE_SYSTEM, user, on_token)
        return content.strip(), self._usage(tin, tout, f"[SYSTEM]\n{WRITE_SYSTEM}\n\n[USER]\n{user}")


class RealJudgeLLM(_RealLLM):
    @traceable(run_type="llm", name="judge.score")
    async def judge(self, query: str, answer: str, gold_text: str) -> tuple[dict, dict]:
        user = f"## 사용자 질문\n{query}\n\n## 에이전트 답변\n{answer}\n\n## 정답 정보\n{gold_text}"
        content, tin, tout = await self.client.complete(JUDGE_SYSTEM, user, json_mode=True)
        return parse_json(content), self._usage(tin, tout)
