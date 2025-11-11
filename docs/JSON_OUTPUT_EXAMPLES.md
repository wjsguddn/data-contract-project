# A1, A2, A3 노드 최종 출력 JSON 형식

이 문서는 Consistency Agent의 각 노드(A1, A2, A3)가 생성하는 최종 JSON 출력 형식을 정의합니다.

## 목차
- [A1 Node: 완전성 검증 (Completeness Check)](#a1-node-완전성-검증-completeness-check)
- [A2 Node: 체크리스트 검증 (Checklist Validation)](#a2-node-체크리스트-검증-checklist-validation)
- [A3 Node: 내용 분석 (Content Analysis)](#a3-node-내용-분석-content-analysis)

---

## A1 Node: 완전성 검증 (Completeness Check)

### 개요
사용자 계약서의 각 조항을 표준계약서 조항과 매칭하고, 누락된 조항을 식별합니다.

### Stage 1 출력 (매칭 검증)

```json
{
  "contract_id": "contract_20241111_123456",
  "contract_type": "provide",
  "total_user_articles": 15,
  "matched_user_articles": 13,
  "total_standard_articles": 20,
  "matched_standard_articles": 18,
  "missing_standard_articles": [
    {
      "parent_id": "제5조",
      "title": "제5조(데이터 보유 기간)",
      "chunks": [
        {
          "id": "provide_std_contract_chunk_005_001",
          "global_id": "urn:std:provide:art:005:sub:001",
          "parent_id": "제5조",
          "title": "제5조(데이터 보유 기간)",
          "text_raw": "데이터제공자는 데이터수령자에게 제공한 데이터를 다음 각 호의 기간 동안 보유할 수 있다.",
          "order_index": 1
        }
      ]
    }
  ],
  "matching_details": [
    {
      "user_article_no": 3,
      "user_article_id": "user_article_003",
      "user_article_title": "제3조(데이터 제공 목적)",
      "matched": true,
      "matched_articles": ["제3조"],
      "matched_articles_global_ids": ["urn:std:provide:art:003"],
      "matched_articles_details": [
        {
          "parent_id": "제3조",
          "global_id": "urn:std:provide:art:003",
          "title": "제3조(데이터 제공 목적)",
          "combined_score": 0.92,
          "num_sub_items": 3,
          "matched_sub_items": [0, 1, 2],
          "avg_dense_score": 0.89,
          "avg_dense_score_raw": 0.85,
          "avg_sparse_score": 0.95,
          "avg_sparse_score_raw": 12.5,
          "sub_items_scores": [
            {
              "chunk_id": "provide_std_contract_chunk_003_001",
              "global_id": "urn:std:provide:art:003:sub:001",
              "text": "데이터제공자는 다음 각 호의 목적으로 데이터수령자에게 데이터를 제공한다.",
              "dense_score": 0.91,
              "dense_score_raw": 0.87,
              "sparse_score": 0.96,
              "sparse_score_raw": 13.2,
              "combined_score": 0.93
            }
          ]
        }
      ],
      "sub_item_results": [
        {
          "sub_item_index": 0,
          "sub_item_text": "데이터제공자는 다음 각 호의 목적으로 데이터수령자에게 데이터를 제공한다.",
          "matched_articles": [
            {
              "parent_id": "제3조",
              "base_global_id": "urn:std:provide:art:003",
              "title": "제3조(데이터 제공 목적)",
              "score": 0.93,
              "num_sub_items": 3,
              "matched_sub_items": [0],
              "matched_chunks": [
                {
                  "chunk": {
                    "id": "provide_std_contract_chunk_003_001",
                    "global_id": "urn:std:provide:art:003:sub:001",
                    "text_raw": "데이터제공자는 다음 각 호의 목적으로 데이터수령자에게 데이터를 제공한다."
                  },
                  "dense_score": 0.91,
                  "sparse_score": 0.96,
                  "score": 0.93
                }
              ]
            }
          ]
        }
      ],
      "verification_details": [
        {
          "candidate_id": "제3조",
          "is_match": true,
          "confidence": 0.95,
          "reasoning": "사용자 조항과 표준 조항의 목적이 일치하며, 핵심 내용이 포함되어 있습니다."
        }
      ]
    }
  ],
  "processing_time": 45.2,
  "verification_date": "2024-11-11T14:30:00"
}
```

### Stage 2 출력 (누락 조문 재검증)

```json
{
  "missing_article_analysis": [
    {
      "standard_article_id": "urn:std:provide:art:005",
      "standard_article_title": "제5조(데이터 보유 기간)",
      "is_truly_missing": true,
      "confidence": 0.85,
      "matched_user_article": null,
      "reasoning": "사용자 계약서에 데이터 보유 기간에 대한 명시적 조항이 없습니다.",
      "recommendation": "'제5조(데이터 보유 기간)' 조항을 추가하여 데이터 보유 기간을 명확히 규정해야 합니다.",
      "evidence": "역방향 검색 결과 유사한 조항을 찾을 수 없었으며, LLM 검증에서도 누락으로 확인되었습니다.",
      "risk_assessment": "데이터 보유 기간 미명시로 인한 법적 분쟁 가능성이 있습니다.",
      "top_candidates": [
        {
          "user_article_no": 7,
          "user_article_title": "제7조(데이터 관리)",
          "similarity": 0.45,
          "reasoning": "데이터 관리에 대한 내용은 있으나 보유 기간은 명시되지 않음"
        }
      ],
      "candidates_analysis": [
        {
          "candidate_no": 7,
          "is_match": false,
          "confidence": 0.75,
          "reasoning": "데이터 관리 조항이지만 보유 기간에 대한 구체적 내용이 없습니다."
        }
      ]
    }
  ],
  "processing_time": 12.5
}
```

### 전체 출력 (Stage 1 + Stage 2 통합)

순차 실행 시 Stage 1과 Stage 2 결과가 통합됩니다:

```json
{
  "contract_id": "contract_20241111_123456",
  "contract_type": "provide",
  "total_user_articles": 15,
  "matched_user_articles": 13,
  "total_standard_articles": 20,
  "matched_standard_articles": 18,
  "missing_standard_articles": [...],
  "matching_details": [...],
  "missing_article_analysis": [...],
  "processing_time": 57.7,
  "verification_date": "2024-11-11T14:30:00"
}
```

---

## A2 Node: 체크리스트 검증 (Checklist Validation)

### 개요
표준계약서의 각 조항에 대한 체크리스트를 기준으로 사용자 계약서를 검증합니다.

### 출력 형식

```json
{
  "std_article_results": [
    {
      "std_article_id": "urn:std:provide:art:003",
      "std_article_title": "제3조(데이터 제공 목적)",
      "std_article_number": "제3조",
      "matched_user_articles": [
        {
          "user_article_no": 3,
          "user_article_id": "user_article_003",
          "user_article_title": "제3조(데이터 제공 목적)"
        }
      ],
      "checklist_results": [
        {
          "check_text": "데이터 제공 목적이 명확하게 기재되어 있는가?",
          "reference": "제3조",
          "result": "YES",
          "reasoning": "사용자 계약서 제3조에 데이터 제공 목적이 명확히 기재되어 있습니다.",
          "evidence": "제3조 본문에 '다음 각 호의 목적으로 데이터를 제공한다'고 명시되어 있음",
          "relevant_articles": [
            {
              "user_article_no": 3,
              "user_article_id": "user_article_003",
              "user_article_title": "제3조(데이터 제공 목적)"
            }
          ]
        },
        {
          "check_text": "제공 목적이 구체적으로 열거되어 있는가?",
          "reference": "제3조",
          "result": "NO",
          "reasoning": "제공 목적이 추상적으로 기술되어 있으며, 구체적인 열거가 부족합니다.",
          "evidence": "제3조에 '데이터 분석 및 활용'이라는 포괄적 표현만 있음",
          "relevant_articles": [
            {
              "user_article_no": 3,
              "user_article_id": "user_article_003",
              "user_article_title": "제3조(데이터 제공 목적)"
            }
          ]
        },
        {
          "check_text": "목적 외 사용 금지 조항이 포함되어 있는가?",
          "reference": "제3조",
          "result": "UNCLEAR",
          "reasoning": "목적 외 사용 금지에 대한 명시적 문구가 없으나, 다른 조항에서 간접적으로 언급될 가능성이 있습니다.",
          "evidence": "제3조에는 명시되지 않았으나, 제8조(데이터 이용 제한)에서 관련 내용 확인 필요",
          "relevant_articles": [
            {
              "user_article_no": 3,
              "user_article_id": "user_article_003",
              "user_article_title": "제3조(데이터 제공 목적)"
            }
          ]
        }
      ],
      "statistics": {
        "total_items": 5,
        "passed_items": 3,
        "failed_items": 1,
        "unclear_items": 1,
        "manual_check_items": 0,
        "pass_rate": 0.6
      }
    }
  ],
  "statistics": {
    "matched_std_articles": 15,
    "total_checklist_items": 75,
    "passed_items": 52,
    "failed_items": 15,
    "unclear_items": 8,
    "manual_check_items": 0,
    "overall_pass_rate": 0.69
  },
  "processing_time": 38.5,
  "verification_date": "2024-11-11T14:31:00"
}
```

### 체크리스트 결과 필드 설명

- `result`: 검증 결과
  - `"YES"`: 체크리스트 항목 충족
  - `"NO"`: 체크리스트 항목 미충족
  - `"UNCLEAR"`: 판단 불가 (추가 확인 필요)
  - `"MANUAL_CHECK_REQUIRED"`: 수동 검토 필요

- `reasoning`: LLM이 판단한 근거
- `evidence`: 판단의 증거 (조항 내용 인용)
- `relevant_articles`: 관련된 사용자 조항 목록

---

## A3 Node: 내용 분석 (Content Analysis)

### 개요
사용자 계약서의 각 조항 내용을 표준계약서와 비교하여 충실도를 평가하고 개선 제안을 생성합니다.

### 출력 형식

```json
{
  "contract_id": "contract_20241111_123456",
  "contract_type": "provide",
  "article_analysis": [
    {
      "user_article_no": 3,
      "user_article_title": "제3조(데이터 제공 목적)",
      "matched": true,
      "similarity": 0.92,
      "std_article_id": "제3조",
      "std_article_title": "제3조(데이터 제공 목적)",
      "is_special": false,
      "matched_articles": [
        {
          "parent_id": "제3조",
          "global_id": "urn:std:provide:art:003",
          "title": "제3조(데이터 제공 목적)",
          "score": 0.92,
          "num_sub_items": 3,
          "matched_sub_items": [0, 1, 2],
          "matched_chunks": [
            {
              "id": "provide_std_contract_chunk_003_001",
              "global_id": "urn:std:provide:art:003:sub:001",
              "parent_id": "제3조",
              "title": "제3조(데이터 제공 목적)",
              "text_raw": "데이터제공자는 다음 각 호의 목적으로 데이터수령자에게 데이터를 제공한다.",
              "order_index": 1
            }
          ]
        }
      ],
      "matched_articles_details": [
        {
          "parent_id": "제3조",
          "global_id": "urn:std:provide:art:003",
          "title": "제3조(데이터 제공 목적)",
          "combined_score": 0.92,
          "num_sub_items": 3,
          "matched_sub_items": [0, 1, 2],
          "avg_dense_score": 0.89,
          "avg_sparse_score": 0.95,
          "sub_items_scores": [
            {
              "chunk_id": "provide_std_contract_chunk_003_001",
              "global_id": "urn:std:provide:art:003:sub:001",
              "text": "데이터제공자는 다음 각 호의 목적으로 데이터수령자에게 데이터를 제공한다.",
              "dense_score": 0.91,
              "sparse_score": 0.96,
              "combined_score": 0.93
            }
          ]
        }
      ],
      "sub_item_results": [
        {
          "sub_item_index": 0,
          "sub_item_text": "데이터제공자는 다음 각 호의 목적으로 데이터수령자에게 데이터를 제공한다.",
          "matched_articles": [...]
        }
      ],
      "suggestions": [
        {
          "selected_standard_articles": ["urn:std:provide:art:003"],
          "issue_type": "content",
          "missing_items": [
            {
              "item": "목적 외 사용 금지 명시",
              "description": "표준계약서에는 '목적 외 사용을 금지한다'는 명시적 문구가 있으나, 사용자 계약서에는 누락되어 있습니다."
            }
          ],
          "insufficient_items": [
            {
              "item": "제공 목적의 구체성",
              "description": "표준계약서는 제공 목적을 구체적으로 열거하고 있으나, 사용자 계약서는 '데이터 분석 및 활용'이라는 포괄적 표현만 사용하고 있습니다.",
              "current_content": "데이터 분석 및 활용",
              "expected_content": "1. 서비스 개선, 2. 통계 분석, 3. 연구 개발 등 구체적 목적 열거"
            }
          ],
          "analysis": "사용자 계약서 제3조는 데이터 제공 목적을 기술하고 있으나, 표준계약서 대비 다음과 같은 개선이 필요합니다:\n\n1. **목적 외 사용 금지 명시**: 표준계약서는 '데이터수령자는 제공받은 데이터를 제3조에 명시된 목적 외로 사용할 수 없다'고 명시하고 있으나, 사용자 계약서에는 이러한 금지 조항이 없습니다.\n\n2. **제공 목적의 구체화**: 표준계약서는 제공 목적을 '1. 서비스 개선, 2. 통계 분석, 3. 연구 개발'과 같이 구체적으로 열거하고 있으나, 사용자 계약서는 '데이터 분석 및 활용'이라는 포괄적 표현만 사용하고 있어 목적의 범위가 불명확합니다.\n\n**권장사항**: 제공 목적을 구체적으로 열거하고, 목적 외 사용 금지 조항을 추가하여 계약의 명확성과 법적 안정성을 높이시기 바랍니다.",
          "severity": "medium"
        }
      ],
      "reasoning": "표준계약서 제3조와 매칭됨",
      "analysis_timestamp": "2024-11-11T14:32:00"
    },
    {
      "user_article_no": 5,
      "user_article_title": "제5조(데이터 품질)",
      "matched": true,
      "similarity": 0.88,
      "std_article_id": "제4조",
      "std_article_title": "제4조(데이터 품질 보증)",
      "is_special": false,
      "matched_articles": [
        {
          "parent_id": "제4조",
          "global_id": "urn:std:provide:art:004",
          "title": "제4조(데이터 품질 보증)",
          "score": 0.88,
          "num_sub_items": 2,
          "matched_sub_items": [0, 1],
          "matched_chunks": [...]
        }
      ],
      "matched_articles_details": [...],
      "sub_item_results": [...],
      "suggestions": [
        {
          "selected_standard_articles": ["urn:std:provide:art:004"],
          "issue_type": "content",
          "missing_items": [],
          "insufficient_items": [],
          "analysis": "사용자 계약서 제5조는 표준계약서 제4조(데이터 품질 보증)의 핵심 내용을 충실히 반영하고 있습니다. 데이터 품질 기준, 검증 절차, 품질 미달 시 조치 등이 모두 포함되어 있으며, 표준계약서와 실질적으로 동등한 수준의 내용을 담고 있습니다.",
          "severity": "info"
        }
      ],
      "reasoning": "표준계약서 제4조와 매칭됨",
      "analysis_timestamp": "2024-11-11T14:32:05"
    }
  ],
  "total_articles": 15,
  "analyzed_articles": 13,
  "special_articles": 0,
  "analysis_timestamp": "2024-11-11T14:32:00",
  "processing_time": 52.3
}
```

### 제안(Suggestions) 필드 설명

- `selected_standard_articles`: LLM이 비교에 사용한 표준 조항 ID 목록
- `issue_type`: 문제 유형 (`"content"`: 내용 관련)
- `missing_items`: 누락된 항목 목록
  - `item`: 누락 항목명
  - `description`: 누락 내용 설명
- `insufficient_items`: 불충분한 항목 목록
  - `item`: 불충분 항목명
  - `description`: 불충분 내용 설명
  - `current_content`: 현재 내용
  - `expected_content`: 기대되는 내용
- `analysis`: LLM이 생성한 종합 분석 및 개선 제안
- `severity`: 심각도
  - `"high"`: 심각 (누락 3개 이상 또는 누락+불충분 5개 이상)
  - `"medium"`: 보통 (누락 2개 이상 또는 불충분 2개 이상)
  - `"low"`: 낮음 (그 외)
  - `"info"`: 정보성 (문제 없음, 긍정적 분석)

---

## 데이터베이스 저장 구조

각 노드의 결과는 `ValidationResult` 테이블에 저장됩니다:

```python
class ValidationResult(Base):
    __tablename__ = "validation_results"
    
    id = Column(Integer, primary_key=True, index=True)
    contract_id = Column(String, unique=True, index=True)
    
    # A1 결과
    completeness_check = Column(JSON)  # Stage 1 + Stage 2 통합
    
    # A2 결과
    checklist_validation = Column(JSON)  # primary 매칭 기준
    checklist_validation_recovered = Column(JSON)  # recovered 매칭 기준
    
    # A3 결과
    content_analysis = Column(JSON)  # primary 매칭 기준
    content_analysis_recovered = Column(JSON)  # recovered 매칭 기준
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

---

## 병렬 처리 아키텍처

```
A1-Stage1 (매칭 검증)
    ↓
    ├─→ A1-Stage2 (누락 재검증)
    ├─→ A2 (체크리스트 검증)
    └─→ A3 (내용 분석)
```

- **A1-Stage1**: 모든 사용자 조항 매칭 + LLM 검증
- **A1-Stage2, A2, A3**: 병렬 실행 (A1-Stage1 결과 참조)

---

## 참고사항

### Global ID 형식
- 표준계약서 조항: `urn:std:{contract_type}:art:{article_no:03d}`
  - 예: `urn:std:provide:art:003`
- 하위항목: `urn:std:{contract_type}:art:{article_no:03d}:sub:{sub_no:03d}`
  - 예: `urn:std:provide:art:003:sub:001`

### 계약 유형 (contract_type)
- `provide`: 데이터 제공형
- `create`: 데이터 창출형
- `process`: 데이터 가공형
- `brokerage_provider`: 데이터 중개 거래형 (제공자용)
- `brokerage_user`: 데이터 중개 거래형 (이용자용)

### 매칭 유형 (matching_types)
- `["primary"]`: A1-Stage1의 기본 매칭 결과 (기본값)
- `["recovered"]`: A1-Stage2의 누락 재검증에서 복구된 매칭
- `["primary", "recovered"]`: 두 가지 모두 포함

---

## 버전 정보
- 문서 버전: 1.0
- 최종 수정일: 2024-11-11
- 작성자: Kiro AI
