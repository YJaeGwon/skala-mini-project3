"""[추가2] Before/After 평가 — 서버를 띄우고 같은 질문을 HTTP(/chat)로 보내 비교한다.

  python -m eval.run_eval --target before --split test --runs 3 --judge openai --label final
  python -m eval.run_eval --target after  --split test --runs 3 --judge openai --label final

- before: 원본 Base 코드 스냅샷(eval/before_snapshot.py) + 같은 데이터
- after : 이 프로젝트 (과제1 개선판)
두 서버 모두 LLM_BACKEND=openai, fast/quality 모두 gpt-4o-mini(비용 절감·공정 비교).
After에서 운영자 승인이 걸리면 approval_requested=True로 기록하고 '승인'으로 이어 간다.
"""
import argparse
import asyncio
import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import dotenv_values

from agent.config import DATA_DIR, systems
from eval.metrics import extract, run_std, summarize, ticket_metrics

ROOT = Path(__file__).resolve().parent.parent
RESULTS = Path(__file__).parent / "results"
PORT = 8100
BASE_URL = f"http://127.0.0.1:{PORT}"


def load_dataset(split: str, name: str = "dataset.jsonl") -> list[dict]:
    rows = [json.loads(l) for l in (Path(__file__).parent / name).read_text().splitlines() if l.strip()]
    return rows if split == "all" else [r for r in rows if r["split"] == split]


def start_server(target: str) -> subprocess.Popen:
    if target == "before":
        from eval.before_snapshot import prepare
        workdir = prepare()
    else:
        workdir = ROOT
        for f in list(RESULTS.glob("_ck_after.db*")) + list(RESULTS.glob("_session_after.db*")):
            f.unlink()
    env = {**os.environ, **{k: v for k, v in dotenv_values(ROOT / ".env").items() if v},
           "LLM_BACKEND": "openai", "SUPERVISOR_VERSION": "v2", "LANGCHAIN_TRACING_V2": "false",
           "OPENAI_FAST_MODEL": "gpt-4o-mini", "OPENAI_QUALITY_MODEL": "gpt-4o-mini",
           "CHECKPOINT_DB": str(RESULTS / "_ck_after.db"), "PORT": str(PORT),
           "SESSION_DB": str(RESULTS / "_session_after.db")}
    subprocess.run(f"lsof -ti:{PORT} | xargs kill -9", shell=True, capture_output=True)
    proc = subprocess.Popen([sys.executable, "server.py"], cwd=workdir, env=env,
                            stdout=subprocess.DEVNULL, stderr=open(RESULTS / f"_{target}_server.log", "w"))
    for _ in range(240):
        try:
            if httpx.get(f"{BASE_URL}/health", timeout=2).status_code == 200:
                return proc
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    proc.kill()
    raise RuntimeError(f"{target} 서버가 뜨지 않았습니다 — eval/results/_{target}_server.log 확인")


async def send(client: httpx.AsyncClient, message: str, thread: str) -> tuple[dict, bool]:
    resp = (await client.post(f"{BASE_URL}/chat", json={"message": message, "thread_id": thread})).json()
    approval = resp.get("status") == "pending_approval"
    if approval:
        resp = (await client.post(f"{BASE_URL}/approve",
                                  json={"run_id": resp["run_id"], "approved": True, "note": "eval"})).json()
    return resp, approval


def judge_gold_text(row: dict) -> str:
    if row["gold_route"] == "clarify":
        return "정답: 대상 시스템이 불명확하거나 모니터링 대상이 아니다. 엉뚱한 시스템을 진단하지 말고 대상을 되묻는 것이 정답."
    lines = [f"정답 대상 시스템: {', '.join(row['gold_systems'])}",
             f"정답 장애 유형(runbook): {', '.join(row['gold_incident_types']) or '없음(정상)'}"]
    logs = json.loads((DATA_DIR / "logs.json").read_text())
    for s in row["gold_systems"]:
        d = systems()[s]
        lines.append(f"- {s}: 상태={d['status']}, CPU 기준 {d['cpu_base']}%, 메모리 기준 {d['memory_base']}%, "
                     f"알림 {d['alerts']}, 최근 로그 {logs.get(s, [])}")
    for t in row["gold_incident_types"]:
        lines.append(f"[정답 runbook {t}]\n{(DATA_DIR / 'runbooks' / f'{t}.md').read_text()}")
    return "\n".join(lines)


async def main(args):
    RESULTS.mkdir(exist_ok=True)
    os.environ.update({k: v for k, v in dotenv_values(ROOT / ".env").items() if v})
    judge = None
    if args.judge == "openai":
        os.environ.setdefault("OPENAI_JUDGE_MODEL", "gpt-4o")
        from agent.llm import build_llms
        judge = build_llms("openai")[2]
    rows = load_dataset(args.split, args.dataset)
    proc = start_server(args.target)
    records, per_run = [], []
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            for run in range(1, args.runs + 1):
                run_metrics = []
                for row in rows:
                    thread = f"eval-{args.label}-{args.target}-{row['id']}-r{run}-{datetime.now():%H%M%S}"
                    for msg in row["setup"]:
                        await send(client, msg, thread)
                    started = time.perf_counter()
                    resp, approval = await send(client, row["query"], thread)
                    pred = {**extract(resp), "reply": resp.get("reply", ""), "approval_requested": approval,
                            "latency_s": round(time.perf_counter() - started, 3)}
                    if judge and row["gold_route"] != "chat":
                        scores, _ = await judge.judge(row["query"], pred["reply"], judge_gold_text(row))
                        pred.update(judge_grounding=scores.get("grounding"),
                                    judge_hallucination=scores.get("hallucination"),
                                    judge_helpfulness=scores.get("helpfulness"),
                                    judge_reason=scores.get("reason"))
                    m = ticket_metrics(row, pred)
                    run_metrics.append(m)
                    records.append({"run": run, "id": row["id"], "query": row["query"],
                                    "gold_systems": " ".join(row["gold_systems"]),
                                    "investigated": " ".join(pred["investigated"]),
                                    "gold_types": " ".join(row["gold_incident_types"]),
                                    "runbooks": " ".join(pred["runbooks"]), "pred_route": pred["route"],
                                    "judge_reason": pred.get("judge_reason", ""), **m, "reply": pred["reply"]})
                    print(f"[{args.target} r{run}] {row['id']} route={pred['route']} inv={pred['investigated']} "
                          f"rb={pred['runbooks']} appr={approval} lat={pred['latency_s']}s", flush=True)
                per_run.append(summarize(run_metrics))
    finally:
        proc.terminate()
        proc.wait(timeout=10)

    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    base = RESULTS / f"{args.label}_{args.target}_{stamp}"
    with open(f"{base}.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(records[0].keys()))
        w.writeheader()
        w.writerows(records)
    summary = {"config": {"target": args.target, "split": args.split, "runs": args.runs, "dataset": args.dataset,
                          "judge": args.judge, "label": args.label, "models": "gpt-4o-mini (fast/quality)"},
               "summary": summarize(records), "std_across_runs": run_std(per_run) if len(per_run) > 1 else {}}
    Path(f"{base}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary["summary"], ensure_ascii=False, indent=2))
    print(f"저장: {base}.csv / .json")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True, choices=["before", "after"])
    ap.add_argument("--split", default="test", choices=["dev", "test", "all"])
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--judge", default="none", choices=["none", "openai"])
    ap.add_argument("--label", default="main")
    ap.add_argument("--dataset", default="dataset.jsonl",
                    help="질문지 파일 (eval/ 아래). 처음 보는 질문 평가: dataset_holdout.jsonl")
    asyncio.run(main(ap.parse_args()))
