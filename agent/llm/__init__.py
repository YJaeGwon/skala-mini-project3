"""LLM 백엔드 조립 — LLM_BACKEND 하나로 fake / ollama / openai가 바뀐다 (Base 구조 유지).

가상 단가(1k 토큰당 USD)는 Base server.py와 같은 값을 쓴다: fast 0.00015, quality 0.005.
"""
import os

from .fake_llm import FakeFastLLM, FakeJudgeLLM, FakeQualityLLM

FAST_USD_PER_1K = 0.00015
QUALITY_USD_PER_1K = 0.005


def build_llms(backend: str):
    """반환: (fast_llm, quality_llm, judge_llm)."""
    if backend == "fake":
        return FakeFastLLM(), FakeQualityLLM(), FakeJudgeLLM()
    from .clients import OllamaClient, OpenAIClient
    from .real_llm import RealFastLLM, RealJudgeLLM, RealQualityLLM
    if backend == "openai":
        make = OpenAIClient
        fast = os.environ.get("OPENAI_FAST_MODEL", "gpt-4o-mini")
        quality = os.environ.get("OPENAI_QUALITY_MODEL", "gpt-4o")
        judge = os.environ.get("OPENAI_JUDGE_MODEL", "gpt-4o")
    elif backend == "ollama":
        make = OllamaClient
        fast = os.environ.get("OLLAMA_FAST_MODEL", "qwen3:8b")
        quality = os.environ.get("OLLAMA_QUALITY_MODEL", "qwen3:8b")
        judge = os.environ.get("OLLAMA_JUDGE_MODEL", "qwen3:8b")
    else:
        raise ValueError(f"알 수 없는 LLM_BACKEND: {backend}")
    return (RealFastLLM(make(fast), FAST_USD_PER_1K),
            RealQualityLLM(make(quality), QUALITY_USD_PER_1K),
            RealJudgeLLM(make(judge), FAST_USD_PER_1K))
