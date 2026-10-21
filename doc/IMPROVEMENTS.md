# 과제1 — Base AI Agent 개선·추가 기능 정리

원본: `all_total_vue_student/` (수정하지 않음, Before) → 개선판: `task1_improved/` (After)

## 0. 한눈에 보기 (엑셀 등록용)

```
개선사항: RAG 매뉴얼검색, 사실검증, 멀티에이전트, 모듈화, 하드코딩제거, 비동기스트리밍
기능추가: 승인(HITL), 자동평가, 대화메모리, 로그분석, 단위테스트
```

### Google Spread 등록용 표 (PDF 10쪽 형식)

| 순번 | 영역 | 무엇을 바꾸나 | 추가설명 |
|---|---|---|---|
| 1 | RAG | 키워드 기반 장애유형 매핑 → runbook 벡터 검색 | 이상 시스템마다 "상태+알림+에러로그"로 runbook을 의미 검색, 시스템별 다중 runbook. 새 runbook은 파일만 추가하면 검색됨 |
| 2 | 검증 | 형식 검사 → 사실 검증 | 답변 속 수치가 실제 측정값·알림·로그·runbook에 있는지, 조사한 시스템만 언급했는지 코드로 대조. 3회 실패 시 측정값 기반 안전 답변 |
| 3 | 그래프 개선 | research 노드 → 서브에이전트 3개 | 메트릭·로그 에이전트 병렬 → runbook 에이전트, 각각 compiled subgraph |
| 4 | 모듈화 | graph.py 단일 파일 → 노드별 모듈 | 노드 1개 = 파일 1개, graph.py는 조립만 |
| 5 | 하드코딩 | 폴백·고정값 → 설정 + 대상 자동 판별 | auth-service·db-down 폴백, 고정 지연 0.35초 제거, 설정 파일화, 대상이 불분명하면 진단 대신 확인 질문 |
| 6 | 성능 | 동기 LLM 호출 → 비동기 + 스트리밍 | 동시 요청 처리, OpenAI 토큰 단위 스트리밍 |
| 7 | HITL | 위험 조치 승인 노드 추가 | 재시작·롤백·failover 문장이 있으면 interrupt() → 운영자 승인/거절, SQLite에 대기 상태 저장 |
| 8 | 평가 | Before/After 평가 + LLM-as-judge | 정답 라벨 28건 + 처음 보는 질문 20건, 원본 코드와 개선판을 같은 HTTP 하네스로 비교, gpt-4o 채점 |
| 9 | 메모리 | 대화 요약 메모리 + 후속 질문 | 10개 넘는 대화는 누적 요약 저장, "그 서비스"는 이전 대화에서 시스템 해석 |
| 10 | 데이터·도구 | 로그 Tool·로그 에이전트 + 데이터 보강 | get_recent_logs MCP Tool, 시스템 3개·runbook 2종·로그 데이터 추가 |
| 11 | 품질 | 단위 테스트 28개 | fake LLM·FakeMCP로 외부 호출 없이 그래프 전체 검증 |

---

## 1. 개선사항 (원래 있던 기능을 더 좋게)

### 개선1. runbook 선택: 키워드 규칙 → RAG
| | 내용 |
|---|---|
| Base의 문제 | `graph.py:192` `_INCIDENT_TYPE_RULES` — 알림 문구에서 "latency·cpu·memory…"를 위에서부터 찾아 **처음 걸린 하나만** 선택. 복합 장애("gateway 타임아웃 + payments CPU")는 cpu-spike 하나만, 목록에 없는 장애(인증서 만료·큐 적체)는 무조건 db-down |
| 바꾼 것 | runbook을 제목·단계별 조각으로 나눠 Chroma에 임베딩(조각마다 incident_type 메타데이터). 이상 시스템마다 `상태=… 알림: … 로그: …` 질의로 검색 → 시스템별 runbook 선택(중복 제거, 최대 3개) → MCP Resource로 원문 조회 |
| 설계 근거(실측) | 질의 형식: 알림+로그만 7/8, 시스템 설명 포함 7/8, **상태값 포함 8/8**. 검색 방식: vector 8/8, hybrid 5/8, bm25 3/8 (알림·로그는 영어, runbook은 한국어라 키워드 검색이 방해) → vector 채택 |
| 파일 | `agent/rag/*`, `agent/nodes/runbook_agent.py` |

### 개선2. 답변 검증: 형식 → 사실
| | 내용 |
|---|---|
| Base의 문제 | `graph.py:279` — "30자 이상 + '1)' 포함"이면 합격. 지어낸 수치도 통과(Base 주석에 실측 환각 사례: 조사 안 한 cache-service의 "CPU 53.5%"). 3회째는 불합격이어도 통과 처리 |
| 바꾼 것 | 형식 검사 유지 + ① 답변 속 %·초·ms가 측정값/알림/로그/runbook에 있는지(반올림 인용 허용) ② 언급한 시스템이 조사했거나 근거에 등장한 시스템인지. 불합격 사유를 그대로 재작성 지시로 전달, 3회 실패 시 측정값만 옮긴 안전 답변으로 대체 |
| 파일 | `agent/validators.py`, `agent/nodes/validate.py`, `agent/templates.py` |

### 개선3. 멀티 에이전트: research 노드 → 서브에이전트 3개
| | 내용 |
|---|---|
| Base의 문제 | research 노드 하나가 모니터링 조회와 runbook 조회를 모두 처리 |
| 바꾼 것 | `research_supervisor` → **metric_agent**(collect→detect) ∥ **log_agent**(fetch→filter) 병렬 → **runbook_agent**(select→fetch). 각자 compiled subgraph, wrapper 노드에서 새 입력으로 호출(부모 events 중복 방지). 병렬 쓰기를 위해 상태에 reducer(operator.add) 적용 |
| 파일 | `agent/nodes/research_supervisor.py`, `metric_agent.py`, `log_agent.py`, `runbook_agent.py`, `agent/state.py` |

### 개선4. 모듈화
| | 내용 |
|---|---|
| Base의 문제 | 노드 9개·규칙·라우팅 함수가 `graph.py` 한 파일(338줄) |
| 바꾼 것 | `agent/nodes/` 아래 노드 1개 = 파일 1개(15개), `graph.py`는 연결만. 런타임 조립은 `bootstrap.py` 하나로(server·tests 공용) |

### 개선5. 하드코딩 제거 + 대상 시스템 자동 판별
| | 내용 |
|---|---|
| Base의 문제 | 시스템을 못 찾으면 auth-service(`graph.py:47`), 유형을 못 찾으면 db-down(`graph.py:213`), 고정 지연 `sleep(0.35)`(`graph.py:161`), KNOWN_SYSTEMS 로딩 코드가 3개 파일에 복사 |
| 바꾼 것 | 대상 시스템을 **이름 → 별칭("로그인"→auth-service) → 이전 대화 → LLM(시스템 설명 목록)** 순서로 찾고, 끝까지 없으면 진단하지 않고 **확인 질문(clarify)**. 시스템·설명·별칭은 `data/monitoring.json`, 동작 값은 `data/agent_config.json`, 위험 패턴은 `data/risk_policy.json`, 읽는 곳은 `agent/config.py` 하나 |
| 파일 | `agent/config.py`, `agent/nodes/plan.py` |

### 개선6. 비동기 LLM 호출 + 토큰 스트리밍
| | 내용 |
|---|---|
| Base의 문제 | `openai_llm.py:98`·`ollama_llm.py:104` — async 노드 안에서 동기 `httpx.post` → 이벤트 루프가 막혀 동시 요청이 줄을 섬. OpenAI는 토큰 스트리밍 없음. 같은 프롬프트가 두 파일에 복사 |
| 바꾼 것 | `httpx.AsyncClient`로 전송 계층 분리(`clients.py`), OpenAI `stream=True`로 토큰 단위 전송, 프롬프트는 `prompts.py` 한곳 |
| 파일 | `agent/llm/*` |

---

## 2. 기능추가 (원래 없던 기능)

### 추가1. Human-in-the-loop — 위험 조치 운영자 승인
- **흐름**: write → validate(합격) → **risk_gate**(재시작·롤백·failover를 *실행하라*는 문장 탐지, "재시작 반복 여부 확인" 같은 점검 문장은 제외) → **human_approval**(`interrupt()`로 멈춤) → 승인: 그대로 응답 / 거절: 위험 조치를 뺀 안전한 대안으로 재작성(그래도 남으면 해당 줄 삭제)
- **저장**: `AsyncSqliteSaver`(checkpoints.db) — 서버를 재시작해도 `/approve` 가능(직접 테스트)
- **API·UI**: `POST /approve {run_id, approved, note}`, 채팅 화면 승인 카드
- **설계 선택**: PDF 예시는 write와 validate 사이지만 validate **뒤**에 둠 — 재작성마다 승인을 다시 받지 않고, 운영자가 검증된 최종본을 승인하도록
- 파일: `agent/nodes/risk_gate.py`, `agent/validators.py`(find_risky/strip_risky), `server.py`, `web_chat.html`

### 추가2. Before/After 평가 파이프라인 + LLM-as-judge
- **데이터셋**: `eval/dataset.jsonl` 28건(dev 10 / test 18) — Base 회귀 쿼리 10개 포함, 복합 장애·신규 장애·증상만·대상 불명·후속 질문·긴 대화·위험 조치
- **방법**: Before = 원본 코드를 바이트 그대로 복사 + 같은 데이터(`eval/before_snapshot.py`가 코드 동일성 검사). 두 서버를 같은 HTTP 하네스(`eval/run_eval.py`)로 돌리고, 응답 이벤트에서 조사 시스템·runbook을 뽑아 채점. gpt-4o가 진단 근거·환각·유용성 채점
- **오프라인 실험**: `eval/retrieval_eval.py` — Base 키워드 규칙 vs bm25 vs vector vs hybrid

### 추가3. 대화 요약 메모리 + 후속 질문
- 메시지가 10개를 넘으면 최근 6개만 원문으로 두고 그 앞은 fast LLM으로 **누적 요약**해 SQLite(`summaries` 테이블)에 저장. 이미 요약한 부분은 다시 요약하지 않음
- "그 서비스", "아까" 같은 후속 질문은 이전 대화에서 가장 최근 시스템을 찾음
- 평가 중 발견한 버그: 두 번째 요약부터 이전 요약을 덮어써 첫 사실(휴가 요일)이 사라짐 → 기존 사실 유지를 프롬프트로 강제 + 테스트 추가
- 파일: `agent/nodes/memory.py`, `agent/session_store.py`, `agent/nodes/plan.py`

### 추가4. 로그 분석 + 데이터 보강
- MCP Tool `get_recent_logs` + 로그 에이전트(ERROR/WARN/FATAL만 추림) — 진단에 로그 근거가 붙고, runbook 검색 질의에도 쓰임
- 데이터: 시스템 3개(order-db, notification-service, edge-proxy), runbook 2종(queue-backlog, cert-expiry), 시스템별 설명·별칭, 로그(`data/logs.json`)

### 추가5. 단위 테스트 28개
- 그래프 흐름 10, 검증·위험 조치 6, RAG 4, 설정 4, Base 한계 기록 2, 재시도 2 — `bash sh/run_tests.sh` (1초, 비용 없음)

---

## 3. 실측 결과 (Before vs After)

같은 데이터·같은 모델(gpt-4o-mini), 개발용 질문 18건(3회 평균) + 처음 보는 질문 20건 = 38건, gpt-4o 채점. 자세한 내용은 [REPORT.md](REPORT.md).

| 지표 | 문항 수 | Before | After | 관련 항목 |
|---|---|---|---|---|
| 정답 runbook 선택률 | 29 | 20% | 95% | 개선1 |
| 조사 대상 시스템 재현율 | 30 | 60% | 96% | 개선5, 추가3 |
| 엉뚱한 시스템을 조사한 비율 | 34 | 57% | 0% | 개선5 |
| LLM-judge 환각 비율 | 34 | 36% | 3% | 개선1·2 |
| LLM-judge 근거·진단 점수 (5점) | 34 | 2.67 | 4.82 | 개선1·2·3 |
| 위험 조치가 승인 없이 나간 문항 | 30 | 3개 | 0개 | 추가1 (설계상 결과) |
| 운영자 승인 요청 비율 | 30 | 0% | 33% | 추가1 (부담) |
| 모호한 요청 확인 질문 / 긴 대화 기억 | 4 / 2 | 0개 / 0개 | 4개 / 2개 | 개선5, 추가3 (참고용) |
| 지연시간 p50 | 전체 | 4.87초 | 4.43초 | 개선5·6 |
| 요청당 평균 가상 비용 | 전체 | $0.0022 | $0.0038 (×1.7) | 트레이드오프 |

엑셀에 한 줄 더 쓸 수 있다면:
```
효과(실측 38문항): 정답 runbook 선택률 20%→95%, 엉뚱한 시스템 조사 57%→0%, 환각 36%→3%, 위험조치 무승인 3개→0개 (승인 요청 33%, 비용 ×1.7)
```

---

## 4. 코드 읽는 순서 (발표 준비)
1. `agent/graph.py` — 전체 흐름 그림(docstring)
2. `agent/nodes/plan.py` — 대상 찾기 4단계와 확인 질문
3. `agent/nodes/runbook_agent.py` + `agent/rag/retriever.py` — RAG
4. `agent/validators.py` — 사실 검증과 위험 조치 탐지
5. `agent/nodes/risk_gate.py` + `server.py`의 `/approve` — HITL
6. `agent/nodes/memory.py` — 요약 메모리
7. `eval/run_eval.py` + `eval/metrics.py` — 평가 방법
