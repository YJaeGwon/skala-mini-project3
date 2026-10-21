"""[개선1] runbook 선택 비교 (오프라인) — Base 키워드 규칙 vs bm25 vs vector vs hybrid.

이상 시스템 8개(시스템별 1건)와 복합 장애 4건에 대해, 각 방식이 정답 장애 유형을 고르는지 본다.
Base 방식: 수집된 알림 문구를 이어 붙여 키워드 규칙으로 '하나'만 고른다 (graph.py 그대로).
RAG 방식: 이상 시스템마다 '상태+알림+에러 로그'로 검색해 시스템별로 고른다 (runbook_agent와 같음).
  python -m eval.retrieval_eval --backend openai
"""
import argparse
import asyncio
import json
import time
from pathlib import Path

from dotenv import load_dotenv

from agent.config import DATA_DIR, systems
from agent.nodes.runbook_agent import build_queries
from agent.rag.embeddings import build_embedder
from agent.rag.index import ensure_index
from agent.rag.retriever import RunbookRetriever
from tests.test_keyword_baseline import base_classify

CASES = [(["auth-service"], {"high-latency"}), (["payments-service"], {"cpu-spike"}),
         (["cache-service"], {"memory-leak"}), (["gateway-service"], {"network-timeout"}),
         (["log-service"], {"disk-full"}), (["order-db"], {"db-down"}),
         (["notification-service"], {"queue-backlog"}), (["edge-proxy"], {"cert-expiry"}),
         (["gateway-service", "payments-service"], {"network-timeout", "cpu-spike"}),
         (["payments-service", "cache-service"], {"cpu-spike", "memory-leak"}),
         (["log-service", "gateway-service"], {"disk-full", "network-timeout"}),
         (["notification-service", "edge-proxy"], {"queue-backlog", "cert-expiry"})]


def evidence(names):
    logs = json.loads((DATA_DIR / "logs.json").read_text())
    ev = []
    for s in names:
        d = systems()[s]
        ev.append({"source": "monitoring", "data": {"system_name": s, "status": d["status"], "alerts": d["alerts"]}})
        ev.append({"source": "logs", "system": s,
                   "data": [l for l in logs[s] if any(x in l for x in ("ERROR", "WARN", "FATAL"))]})
    return ev


async def main(backend):
    load_dotenv()
    emb = build_embedder(backend)
    coll, chunks, titles, _ = await ensure_index(emb)
    r = RunbookRetriever(coll, emb, chunks, titles)
    lines = [f"runbook 선택 비교 (임베딩: {emb.name}, 단일 8건 + 복합 4건)", "",
             "| 방식 | 단일 장애 정답 | 복합 장애 Recall | 전체 Recall | 평균 지연(ms) |", "|---|---|---|---|---|"]
    single = [c for c in CASES if len(c[0]) == 1]
    multi = [c for c in CASES if len(c[0]) > 1]

    def recall(results):
        return sum(len(p & g) / len(g) for p, g in results) / len(results)

    base = [({base_classify(n)}, g) for n, g in CASES]
    lines.append(f"| Base 키워드 규칙 | {sum(p == g for p, g in base[:8])}/8 | "
                 f"{recall(base[8:]):.2f} | {recall(base):.2f} | 0.0 |")
    for mode in ("bm25", "vector", "hybrid"):
        res, lats = [], []
        for names, gold in CASES:
            state = {"query": "", "targets": names, "anomalies": names, "evidence": evidence(names)}
            picked = set()
            for _, text in build_queries(state):
                t0 = time.perf_counter()
                picked.add((await r.search(text, 1, mode))[0]["incident_type"])
                lats.append((time.perf_counter() - t0) * 1000)
            res.append((picked, gold))
        lines.append(f"| RAG {mode} | {sum(p == g for p, g in res[:8])}/8 | {recall(res[8:]):.2f} | "
                     f"{recall(res):.2f} | {sum(lats) / len(lats):.1f} |")
    md = "\n".join(lines) + "\n"
    print(md)
    (Path(__file__).parent / "results" / f"retrieval_{backend}.md").write_text(md)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="fake", choices=["fake", "openai"])
    asyncio.run(main(ap.parse_args().backend))
