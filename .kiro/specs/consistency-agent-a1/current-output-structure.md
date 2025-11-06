# A1 노드 현재 출력 구조 (매칭/비매칭)

## 전체 출력 구조

A1 노드는 `check_completeness_stage1()` 메서드를 통해 다음 구조를 반환합니다:

```json
{
  "contract_id": "contract_20240101_123456",
  "contract_type": "provide",
  "total_user_articles": 15,
  "matched_user_articles": 13,
  "total_standard_articles": 20,
  "matched_standard_articles": 18,
  "missing_standard_articles": [...],
  "matching_details": [...],
  "processing_time": 45.23,
  "verification_date": "2024-01-01T12:34:56.789Z"
}
```

## 1. 매칭 성공 케이스 (matching_details 배열의 항목)

### 예시: 사용자 제3조가 표준 제3조, 제4조에 매칭

```json
{
  "user_article_no": 3,
  "user_article_id": "user_article_003",
  "user_article_title": "데이터 제공 범위 및 방식",
  "matched": true,
  
  // 매칭된 표준 조문 (parent_id 리스트)
  "matched_articles": ["제3조", "제4조"],
  
  // 매칭된 표준 조문 (global_id 리스트)
  "matched_articles_global_ids": [
    "urn:std:provide:art:003",
    "urn:std:provide:art:004"
  ],
  
  // 매칭 상세 정보
  "matched_articles_details": [
    {
      "parent_id": "제3조",
      "global_id": "urn:std:provide:art:003",
      "title": "데이터 제공 범위",
      "combined_score": 0.85,
      "num_sub_items": 3,
      "matched_sub_items": [1, 2, 3],
      
      // 조 단위 평균 점수
      "avg_dense_score": 0.82,
      "avg_dense_score_raw": 0.78,
      "avg_sparse_score": 0.88,
      "avg_sparse_score_raw": 0.85,
      
      // 하위항목별 상세 점수
      "sub_items_scores": [
        {
          "chunk_id": "provide_chunk_003_001",
          "global_id": "urn:std:provide:art:003:sub:001",
          "text": "「갑」은 「을」에게 다음 각 호의 데이터를 제공한다.",
          "dense_score": 0.82,
          "dense_score_raw": 0.78,
          "sparse_score": 0.88,
          "sparse_score_raw": 0.85,
          "combined_score": 0.85
        },
        {
          "chunk_id": "provide_chunk_003_002",
          "global_id": "urn:std:provide:art:003:sub:002",
          "text": "개인정보를 포함하지 않는 통계 데이터",
          "dense_score": 0.80,
          "dense_score_raw": 0.76,
          "sparse_score": 0.90,
          "sparse_score_raw": 0.87,
          "combined_score": 0.84
        }
      ]
    },
    {
      "parent_id": "제4조",
      "global_id": "urn:std:provide:art:004",
      "title": "데이터 제공 방식",
      "combined_score": 0.78,
      "num_sub_items": 2,
      "matched_sub_items": [2, 3],
      "avg_dense_score": 0.75,
      "avg_dense_score_raw": 0.72,
      "avg_sparse_score": 0.82,
      "avg_sparse_score_raw": 0.79,
      "sub_items_scores": [...]
    }
  ],
  
  // 하위항목별 멀티매칭 결과
  "sub_item_results": [
    {
      "sub_item_index": 1,
      "sub_item_text": "「갑」은 「을」에게 다음 각 호의 데이터를 제공한다.",
      "normalized_text": "「갑」은 「을」에게 다음 각 호의 데이터를 제공한다.",
      "matched_articles": [
        {
          "parent_id": "제3조",
          "title": "데이터 제공 범위",
          "score": 0.85,
          "matched_sub_items": [1],
          "num_sub_items": 1,
          "matched_chunks": [...],
          "base_global_id": "urn:std:provide:art:003"
        }
      ]
    },
    {
      "sub_item_index": 2,
      "sub_item_text": "개인정보를 포함하지 않는 통계 데이터",
      "normalized_text": "개인정보를 포함하지 않는 통계 데이터",
      "matched_articles": [
        {
          "parent_id": "제3조",
          "title": "데이터 제공 범위",
          "score": 0.84,
          "matched_sub_items": [2],
          "num_sub_items": 1,
          "matched_chunks": [...],
          "base_global_id": "urn:std:provide:art:003"
        },
        {
          "parent_id": "제4조",
          "title": "데이터 제공 방식",
          "score": 0.78,
          "matched_sub_items": [2],
          "num_sub_items": 1,
          "matched_chunks": [...],
          "base_global_id": "urn:std:provide:art:004"
        }
      ]
    }
  ],
  
  // LLM 검증 결과
  "verification_details": [
    {
      "candidate_article": "제3조",
      "is_match": true,
      "confidence": 0.9,
      "reasoning": "사용자 계약서 제3조의 내용이 표준계약서 제3조(데이터 제공 범위)와 일치합니다."
    },
    {
      "candidate_article": "제4조",
      "is_match": true,
      "confidence": 0.85,
      "reasoning": "사용자 계약서 제3조의 하위항목 일부가 표준계약서 제4조(데이터 제공 방식)와 관련됩니다."
    }
  ]
}
```

## 2. 매칭 실패 케이스 (비매칭)

### 예시: 사용자 제15조가 어떤 표준 조문에도 매칭되지 않음

```json
{
  "user_article_no": 15,
  "user_article_id": "user_article_015",
  "user_article_title": "특수 조항",
  "matched": false,
  "matched_articles": [],
  "verification_details": []
}
```

### 비매칭 발생 원인

1. **검색 결과 없음**: ArticleMatcher가 후보 조문을 찾지 못함
2. **LLM 검증 실패**: 후보는 있지만 LLM이 매칭 부적합 판정
3. **특수 조항**: 표준계약서에 없는 사용자 고유 조항

## 3. 누락된 표준 조문 (missing_standard_articles)

### 1차 매칭에서 매칭되지 않은 표준 조문

```json
[
  {
    "parent_id": "제5조",
    "title": "개인정보의 제3자 제공",
    "chunks": [
      {
        "id": "provide_chunk_005_001",
        "global_id": "urn:std:provide:art:005:sub:001",
        "parent_id": "제5조",
        "title": "개인정보의 제3자 제공",
        "text_raw": "「갑」은 다음 각 호의 경우를 제외하고는...",
        "order_index": 1
      },
      {
        "id": "provide_chunk_005_002",
        "global_id": "urn:std:provide:art:005:sub:002",
        "parent_id": "제5조",
        "title": "개인정보의 제3자 제공",
        "text_raw": "정보주체의 동의를 받은 경우",
        "order_index": 2
      }
    ]
  },
  {
    "parent_id": "제12조",
    "title": "손해배상",
    "chunks": [...]
  }
]
```

## 4. 누락 재검증 결과 (missing_article_analysis) - Stage 2

### 실제 누락 (is_truly_missing: true)

```json
{
  "standard_article_id": "urn:std:provide:art:005",
  "standard_article_title": "개인정보의 제3자 제공",
  "is_truly_missing": true,
  "confidence": 0.92,
  "matched_user_article": null,
  "reasoning": "사용자 계약서에서 제3자 제공 관련 조항을 찾을 수 없음",
  "recommendation": "'개인정보의 제3자 제공' 조항 추가 필요",
  "evidence": "유사한 내용의 조항이 존재하지 않음",
  "risk_assessment": "높음 - 법적 필수 조항 누락",
  "top_candidates": [],
  "candidates_analysis": []
}
```

### 오탐지 (is_truly_missing: false) - 실제로는 매칭됨

```json
{
  "standard_article_id": "urn:std:provide:art:012",
  "standard_article_title": "손해배상",
  "is_truly_missing": false,
  "confidence": 0.85,
  "matched_user_article": {
    "number": 10,
    "article_id": "user_article_010",
    "title": "책임의 범위"
  },
  "reasoning": "제10조(책임의 범위)에 손해배상 관련 내용이 포함되어 있음",
  "recommendation": "제10조에 손해배상 내용이 포함되어 있으나, 표준계약서와 구조가 다름",
  "evidence": "제10조 본문에서 손해배상 책임 범위를 명시",
  "risk_assessment": "낮음 - 내용은 포함되어 있으나 구조 차이",
  "top_candidates": [
    {
      "user_article": {
        "number": 10,
        "article_id": "user_article_010",
        "title": "책임의 범위",
        "content": [...]
      },
      "similarity": 0.78,
      "avg_similarity": 0.75,
      "num_matches": 3,
      "matched_chunks": [...]
    }
  ],
  "candidates_analysis": [
    {
      "candidate_id": "user_article_010",
      "is_match": true,
      "confidence": 0.85,
      "reasoning": "손해배상 책임의 범위와 한도를 명시하고 있어 표준계약서의 '손해배상' 조항과 실질적으로 동일"
    }
  ]
}
```

## 5. 전체 통계 요약

```json
{
  "total_user_articles": 15,        // 사용자 계약서 총 조문 수
  "matched_user_articles": 13,      // 매칭 성공한 사용자 조문 수
  "total_standard_articles": 20,    // 표준계약서 총 조문 수
  "matched_standard_articles": 18,  // 매칭된 표준 조문 수
  
  // 1차 매칭에서 누락된 표준 조문 (7개)
  "missing_standard_articles": [
    {"parent_id": "제5조", ...},
    {"parent_id": "제12조", ...},
    // ... 5개 더
  ],
  
  // 재검증 결과 (7개 중)
  "missing_article_analysis": [
    {"is_truly_missing": true, ...},   // 5개 (실제 누락)
    {"is_truly_missing": false, ...},  // 2개 (오탐지)
  ]
}
```

## 6. 데이터 흐름 요약

```
사용자 계약서 (15개 조문)
    ↓
[A1 Stage 1: 1차 매칭]
    ↓
matching_details (13개 매칭 성공)
    ├─ matched: true (13개)
    └─ matched: false (2개) ← 사용자 특수 조항
    
missing_standard_articles (7개 누락)
    ↓
[A1 Stage 2: 누락 재검증]
    ↓
missing_article_analysis (7개)
    ├─ is_truly_missing: true (5개) ← 실제 누락
    └─ is_truly_missing: false (2개) ← 오탐지 (실제로는 매칭됨)
```

## 7. 주요 필드 설명

### matched_articles vs matched_articles_global_ids

- `matched_articles`: parent_id 리스트 (예: ["제3조", "제4조"])
  - A3 노드와 프론트엔드 호환성 유지
- `matched_articles_global_ids`: global_id 리스트 (예: ["urn:std:provide:art:003", "urn:std:provide:art:004"])
  - A2 노드에서 체크리스트 매핑에 사용

### 점수 종류

- `dense_score`: 정규화된 시멘틱 유사도 (0~1)
- `dense_score_raw`: 원본 시멘틱 유사도 (FAISS L2 거리 기반)
- `sparse_score`: 정규화된 키워드 유사도 (0~1)
- `sparse_score_raw`: 원본 키워드 유사도 (Whoosh BM25 점수)
- `combined_score`: 최종 종합 점수 (dense_weight * dense + (1-dense_weight) * sparse)

### sub_item_results의 의미

- 각 하위항목이 어떤 표준 조문에 매칭되었는지 추적
- 멀티매칭 지원: 하나의 하위항목이 여러 표준 조문에 매칭 가능
- A3 노드에서 내용 비교 시 사용

### verification_details의 역할

- LLM이 각 후보 조문에 대해 내린 판단
- 매칭 성공/실패 이유 제공
- 신뢰도(confidence) 포함
