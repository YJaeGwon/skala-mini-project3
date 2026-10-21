"""LLM 전송 계층 — OpenAI / Ollama HTTP 호출만 담당한다.

Base의 openai_llm.py/ollama_llm.py는 async 노드 안에서 동기 httpx.post를 호출해 이벤트
루프를 막았다(동시 요청이 서로를 기다림). 여기서는 httpx.AsyncClient로 비동기 호출하고,
OpenAI도 stream=True로 실제 토큰 단위 스트리밍을 한다.

두 클라이언트는 같은 인터페이스를 가진다:
    await complete(system, user, json_mode) -> (텍스트, 입력토큰, 출력토큰)
    await stream(system, user, on_token)    -> (텍스트, 입력토큰, 출력토큰)
"""
import json
import os

import httpx

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434") + "/api/chat"


class OpenAIClient:
    def __init__(self, model: str):
        self.model = model
        self.name = f"openai:{model}"

    def _headers(self) -> dict:
        key = os.environ.get("OPENAI_API_KEY", "")
        if not key or key.startswith("sk-proj-..."):
            raise RuntimeError("OPENAI_API_KEY가 없습니다 — .env에 본인 키를 넣으세요.")
        return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    def _payload(self, system: str, user: str) -> dict:
        return {"model": self.model, "temperature": 0,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}]}

    async def complete(self, system: str, user: str, json_mode: bool = False):
        payload = self._payload(system, user)
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(OPENAI_URL, json=payload, headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
        usage = data.get("usage", {})
        return (data["choices"][0]["message"]["content"],
                usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))

    async def stream(self, system: str, user: str, on_token=None):
        payload = {**self._payload(system, user), "stream": True,
                   "stream_options": {"include_usage": True}}
        chunks, tin, tout = [], 0, 0
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", OPENAI_URL, json=payload,
                                     headers=self._headers()) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: ") or line == "data: [DONE]":
                        continue
                    data = json.loads(line[6:])
                    if data.get("usage"):
                        tin = data["usage"].get("prompt_tokens", 0)
                        tout = data["usage"].get("completion_tokens", 0)
                    for choice in data.get("choices", []):
                        piece = choice.get("delta", {}).get("content")
                        if piece:
                            chunks.append(piece)
                            if on_token:
                                on_token(piece)
        return "".join(chunks), tin, tout


class OllamaClient:
    def __init__(self, model: str):
        self.model = model
        self.name = f"ollama:{model}"

    def _payload(self, system: str, user: str, stream: bool) -> dict:
        return {"model": self.model, "stream": stream, "options": {"temperature": 0.0},
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}]}

    async def complete(self, system: str, user: str, json_mode: bool = False):
        payload = self._payload(system, user, stream=False)
        if json_mode:
            payload["format"] = "json"
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(OLLAMA_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()
        return (data["message"]["content"],
                data.get("prompt_eval_count") or 0, data.get("eval_count") or 0)

    async def stream(self, system: str, user: str, on_token=None):
        chunks, tin, tout = [], 0, 0
        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream("POST", OLLAMA_URL,
                                     json=self._payload(system, user, stream=True)) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    data = json.loads(line)
                    piece = data.get("message", {}).get("content", "")
                    if piece:
                        chunks.append(piece)
                        if on_token:
                            on_token(piece)
                    if data.get("done"):
                        tin = data.get("prompt_eval_count") or 0
                        tout = data.get("eval_count") or 0
        return "".join(chunks), tin, tout
