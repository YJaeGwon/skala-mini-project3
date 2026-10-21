runbook 선택 비교 (임베딩: openai-text-embedding-3-small, 단일 8건 + 복합 4건)

| 방식 | 단일 장애 정답 | 복합 장애 Recall | 전체 Recall | 평균 지연(ms) |
|---|---|---|---|---|
| Base 키워드 규칙 | 6/8 | 0.38 | 0.62 | 0.0 |
| RAG bm25 | 3/8 | 0.38 | 0.38 | 0.2 |
| RAG vector | 8/8 | 1.00 | 1.00 | 275.4 |
| RAG hybrid | 5/8 | 0.38 | 0.54 | 205.7 |
