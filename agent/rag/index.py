"""[개선1] runbook RAG — Chroma 벡터 DB 인덱싱.

- 임베딩은 직접 계산해 넣는다(embedding_function=None): Chroma 기본 모델(ONNX) 다운로드 회피
- runbook 파일 내용 + 임베딩 모델의 해시를 manifest.json에 저장해 바뀌었을 때만 재인덱싱
- 임베딩 백엔드마다 벡터 차원이 달라 인덱스 폴더를 백엔드별로 나눈다

CLI: python -m agent.rag.index --backend openai
"""
import argparse
import asyncio
import hashlib
import json
import re
from pathlib import Path

import chromadb
from chromadb.config import Settings

from ..config import DATA_DIR
from .chunker import load_chunks
from .embeddings import build_embedder

RUNBOOK_DIR = DATA_DIR / "runbooks"
INDEX_ROOT = DATA_DIR / "vectordb"
COLLECTION = "runbooks"


def _digest(runbook_dir: Path, embedder_name: str) -> str:
    h = hashlib.sha256(embedder_name.encode())
    for path in sorted(runbook_dir.glob("*.md")):
        h.update(path.name.encode() + path.read_bytes())
    return h.hexdigest()


async def ensure_index(embedder, runbook_dir: Path = RUNBOOK_DIR, index_root: Path = INDEX_ROOT):
    """반환: (collection, chunks, titles, rebuilt)."""
    chunks, titles = load_chunks(runbook_dir)
    path = index_root / re.sub(r"[^A-Za-z0-9_-]", "_", embedder.name)
    path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(path), settings=Settings(anonymized_telemetry=False))
    manifest = path / "manifest.json"
    digest = _digest(runbook_dir, embedder.name)
    coll = client.get_or_create_collection(COLLECTION, embedding_function=None,
                                           metadata={"hnsw:space": "cosine"})
    old = json.loads(manifest.read_text()).get("digest") if manifest.exists() else None
    if old == digest and coll.count() == len(chunks):
        return coll, chunks, titles, False
    client.delete_collection(COLLECTION)
    coll = client.create_collection(COLLECTION, embedding_function=None,
                                    metadata={"hnsw:space": "cosine"})
    vectors = await embedder.embed([c["text"] for c in chunks])
    coll.add(ids=[c["chunk_id"] for c in chunks], embeddings=vectors,
             documents=[c["text"] for c in chunks],
             metadatas=[{"incident_type": c["incident_type"], "title": c["title"]} for c in chunks])
    manifest.write_text(json.dumps({"digest": digest, "embedder": embedder.name,
                                    "chunks": len(chunks)}, ensure_ascii=False))
    return coll, chunks, titles, True


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="fake", choices=["fake", "ollama", "openai"])
    coll, chunks, titles, rebuilt = asyncio.run(ensure_index(build_embedder(ap.parse_args().backend)))
    print(f"runbook {len(titles)}종, chunk {len(chunks)}개, {'새로 인덱싱' if rebuilt else '기존 인덱스 재사용'}")
