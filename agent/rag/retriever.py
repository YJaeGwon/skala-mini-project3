"""[개선1] runbook RAG — 증상 텍스트로 가장 가까운 장애 유형(incident_type)을 찾는다.

검색 방식: vector(임베딩 코사인) / bm25(키워드) / hybrid(두 순위를 RRF로 합침, 기본값).
조각(제목·단계) 단위로 검색한 뒤 incident_type 단위로 최고 점수를 모은다.
"""
import re

from rank_bm25 import BM25Okapi

RRF_K = 60


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[0-9A-Za-z가-힣]+", text.lower())
    bigrams = [w[i:i + 2] for w in words if re.search(r"[가-힣]", w) for i in range(len(w) - 1)]
    return words + bigrams


class RunbookRetriever:
    def __init__(self, collection, embedder, chunks: list[dict], titles: dict[str, str]):
        self.collection = collection
        self.embedder = embedder
        self.chunks = chunks
        self.titles = titles
        self._bm25 = BM25Okapi([tokenize(c["text"]) for c in chunks])

    async def search(self, text: str, k: int = 3, mode: str = "hybrid") -> list[dict]:
        """반환: [{incident_type, title, score}] — score는 임계값 판단용 vector 유사도(bm25면 정규화 점수)."""
        if mode == "bm25":
            ranked = self._bm25_rank(text)
        else:
            vec = await self._vector_rank(text)
            if mode == "vector":
                ranked = vec
            else:
                kw = self._bm25_rank(text)
                rrf: dict[str, float] = {}
                for ranking in (vec, kw):
                    for rank, (t, _) in enumerate(ranking, 1):
                        rrf[t] = rrf.get(t, 0.0) + 1.0 / (RRF_K + rank)
                vec_score = dict(vec)
                ranked = [(t, vec_score.get(t, 0.0)) for t in sorted(rrf, key=rrf.get, reverse=True)]
        return [{"incident_type": t, "title": self.titles[t], "score": round(float(s), 4)}
                for t, s in ranked[:k]]

    async def _vector_rank(self, text: str) -> list[tuple[str, float]]:
        qvec = (await self.embedder.embed([text]))[0]
        res = self.collection.query(query_embeddings=[qvec], n_results=min(len(self.chunks), 20),
                                    include=["metadatas", "distances"])
        best: dict[str, float] = {}
        for meta, dist in zip(res["metadatas"][0], res["distances"][0]):
            t = meta["incident_type"]
            best[t] = max(best.get(t, -1.0), 1.0 - dist)
        return sorted(best.items(), key=lambda x: x[1], reverse=True)

    def _bm25_rank(self, text: str) -> list[tuple[str, float]]:
        scores = self._bm25.get_scores(tokenize(text))
        best: dict[str, float] = {}
        for chunk, score in zip(self.chunks, scores):
            t = chunk["incident_type"]
            best[t] = max(best.get(t, 0.0), float(score))
        top = max(best.values(), default=0.0) or 1.0
        return sorted(((t, s / top) for t, s in best.items()), key=lambda x: x[1], reverse=True)
