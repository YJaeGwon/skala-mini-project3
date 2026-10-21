"""[개선1] runbook RAG — 임베딩 백엔드 3종 (같은 인터페이스: await embed(texts) -> list[vector]).

- fake   : 글자 bigram 해시(512차원) — 외부 호출 없이 결정론적. 테스트용이라 의미 검색 품질은 낮다.
- ollama : bge-m3 (다국어·한국어 지원) — `ollama pull bge-m3` 필요
- openai : text-embedding-3-small
"""
import hashlib
import math
import os
import re

import httpx


# fake 모드 전용: 알림·로그(영어)와 runbook(한국어)의 단어가 겹치도록 운영 용어를 한국어로 덧붙인다.
# (실제 임베딩 모델은 다국어 의미를 알아서 맞추므로 필요 없다 — 외부 호출 없는 데모를 위한 보정)
FAKE_SYNONYMS = {
    "latency": "응답 지연", "slow": "응답 지연", "pool": "커넥션 풀", "cpu": "CPU 급증",
    "memory": "메모리 누수", "heap": "메모리 누수", "maxmemory": "메모리 누수", "timeout": "네트워크 타임아웃",
    "timed out": "네트워크 타임아웃", "packet loss": "네트워크 타임아웃", "disk": "디스크 용량 부족",
    "no space": "디스크 용량 부족", "refused": "DB Down 커넥션 리플리케이션 failover",
    "replication": "DB Down 리플리케이션", "consumer": "메시지 큐 적체 컨슈머", "lag": "적체",
    "certificate": "TLS 인증서 만료", "tls": "TLS 인증서 만료",
    "handshake": "TLS 인증서", "expires": "인증서 만료", "duplicate": "배치 작업 중복 실행",
}


class FakeEmbedder:
    name = "fake-hash512-v4"
    dim = 512

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            low = text.lower()
            terms = [v for k, v in FAKE_SYNONYMS.items() if k in low]
            if terms:   # 영어 운영 용어가 있으면 그 한국어 용어만으로 임베딩 (긴 로그 원문이 벡터를 흐리지 않게)
                text = " ".join(terms)
            s = re.sub(r"\s+", "", text.lower())
            vec = [0.0] * self.dim
            for i in range(len(s) - 1):
                h = int(hashlib.md5(s[i:i + 2].encode()).hexdigest()[:8], 16)
                vec[h % self.dim] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            vectors.append([v / norm for v in vec])
        return vectors


class OllamaEmbedder:
    def __init__(self, model: str = "bge-m3"):
        self.model = model
        self.name = f"ollama-{model}"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        url = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434") + "/api/embed"
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(url, json={"model": self.model, "input": texts})
            resp.raise_for_status()
            return resp.json()["embeddings"]


class OpenAIEmbedder:
    def __init__(self, model: str = "text-embedding-3-small"):
        self.model = model
        self.name = f"openai-{model}"
        self.tokens_used = 0

    async def embed(self, texts: list[str]) -> list[list[float]]:
        headers = {"Authorization": f"Bearer {os.environ.get('OPENAI_API_KEY', '')}"}
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post("https://api.openai.com/v1/embeddings", headers=headers,
                                     json={"model": self.model, "input": texts})
            resp.raise_for_status()
            data = resp.json()
        self.tokens_used += data.get("usage", {}).get("total_tokens", 0)
        return [d["embedding"] for d in sorted(data["data"], key=lambda d: d["index"])]


def build_embedder(backend: str):
    if backend == "openai":
        return OpenAIEmbedder(os.environ.get("OPENAI_EMBED_MODEL", "text-embedding-3-small"))
    if backend == "ollama":
        return OllamaEmbedder(os.environ.get("OLLAMA_EMBED_MODEL", "bge-m3"))
    return FakeEmbedder()
