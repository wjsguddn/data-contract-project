# A1, A2, A3 노드 최종 출력 JSON 스키마

이 문서는 Consistency Agent의 A1, A2, A3 노드가 생성하는 최종 출력 JSON 구조를 정의합니다.

## 목차
- [A1 노드: 완전성 검증 (Completeness Check)](#a1-노드-완전성-검증-completeness-check)
- [A2 노드: 체크리스트 검증 (Checklist Validation)](#a2-노드-체크리스트-검증-checklist-validation)
- [A3 노드: 내용 분석 (Content Analysis)](#a3-노드-내용-분석-content-analysis)

---

## A1 노드: 완전성 검증 (Completeness Check)

### 개요
사용자 계약서의 각 조항을 표준계약서 조항과 매칭하고, 누락된 표준 조항을 식별합니다.

### Stage 1 출력 (매칭 검증)

```json
{
  "contract_id": "string",
  "contract_type": "provide|process|transfer|brokerage_provider|brokerage_user",
  "total_user_articles": 15,
  "matched_user_articles": 12,
  "unmatched_user_articles_count": 3,
  "total_standard_articles": 20,
  "matched_standard_articles": 12,
  "missing_standard_articles": [
    {
      "parent_id": "제5조",
      "title": "데이터 보유 기간",
      "chunks": [
        {
          "id": "provide_std_contract_chunk_015",
          "global_id": "urn:std:provide:art:005:sub:001",
          "parent_id": "제5조",
          "title": "데이터 보유 기간",
          "text_raw": "...",
          "order_index": 0
        }
      ]
    }
  ],
  "unmatched_user_articles": [
    {
      "user_article_no": 14,
      "user_article_title": "데이터 품질 보증",
      "user_article_text": "...",
      "category": "additional|modified|irrelevant",
      "confidence": 0.85,
      "reasoning": "표준계약서에 없는 추가 조항으로 판단됨",
      "recommendation": "계약 이행에 도움이 되는 조항으로 유지 권장",
      "risk_level": "low|medium|high"
    }
  ],
  "matching_details": [
    {
      "user_article_no": 3,
      "user_article_id": "user_article_003",
      "user_article_title": "데이터 제공 목적",
      "matched": true,
      "matched_articles": ["제3조"],
      "matched_articles_global_ids": ["urn:std:provide:art:003"],
      "matched_articles_details": [
        {
          "parent_id": "제3조",
          "global_id": "urn:std:provide:art:003",
          "title": "데이터 제공 목적",
          "combined_score": 0.92,
          "num_sub_items": 3,
          "matched_sub_items": [0, 1, 2],
          "avg_dense_score": 0.89,
          "avg_dense_score_raw": 0.87,
          "avg_sparse_score": 0.95,
          "avg_sparse_score_raw": 12.5,
          "sub_items_scores": [
            {
              "chunk_id": "provide_std_contract_chunk_008",
              "global_id": "urn:std:provide:art:003:sub:001",
              "text": "...",
              "dense_score": 0.91,
              "dense_score_raw": 0.89,
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
          "sub_item_text": "1. 데이터 분석 및 통계 작성",
          "matched_articles": [
            {
              "parent_id": "제3조",
              "global_id": "urn:std:provide:art:003",
              "title": "데이터 제공 목적",
              "score": 0.93,
              "matched_chunks": [...]
            }
          ]
        }
      ],
      "verification_details": [
        {
          "candidate_id": "제3조",
          "is_match": true,
          "confidence": 0.95,
          "reasoning": "사용자 조항과 표준 조항의 목적이 일치함",
          "evidence": "...",
          "prompt_tokens": 1200,
          "completion_tokens": 150,
          "total_tokens": 1350
        }
      ]
    }
  ],
  "processing_time": 45.2,
  "verification_date": "2025-11-12T10:30:00"
}
```

### Stage 2 출력 (누락 조문 재검증)

```json
{
  "missing_article_analysis": [
    {
      "standard_article_id": "urn:std:provide:art:005",
      "standard_article_title": "데이터 보유 기간",
      "is_truly_missing": true,
      "confidence": 0.88,
      "matched_user_article": null,
      "reasoning": "사용자 계약서에 데이터 보유 기간 관련 조항이 없음",
      "recommendation": "'데이터 보유 기간' 조항 추가 필요",
      "evidence": "역방향 검색 결과 유사한 조항 없음",
      "risk_assessment": "필수 조항 누락으로 법적 리스크 존재",
      "top_candidates": [
        {
          "user_article_no": 7,
          "user_article_title": "데이터 관리",
          "score": 0.45,
          "reasoning": "일부 유사성 있으나 보유 기간 명시 없음"
        }
      ],
      "candidates_analysis": [
        {
          "candidate_no": 7,
          "is_match": false,
          "confidence": 0.85,
          "reasoning": "데이터 관리 조항이지만 보유 기간 명시 없음"
        }
      ]
    }
  ],
  "processing_time": 12.5
}
```

### 전체 출력 (Stage 1 + Stage 2 통합)

순차 실행 시 Stage 1 결과에 `missing_article_analysis` 필드가 추가됩니다.

---

## A2 노드: 체크리스트 검증 (Checklist Validation)

### 개요
A1 매칭 결과를 기반으로 표준 조항별 체크리스트 요구사항을 검증합니다.

### 출력 구조

```json
{
  "std_article_results": [
    {
      "std_article_id": "urn:std:provide:art:003",
      "std_article_title": "제3조",
      "std_article_number": "제3조",
      "matched_user_articles": [
        {
          "user_article_no": 3,
          "user_article_id": "user_article_003",
          "user_article_title": "데이터 제공 목적"
        }
      ],
      "checklist_results": [
        {
          "check_text": "데이터 제공 목적이 명확히 기재되어 있는가?",
          "reference": "제3조",
          "result": "YES|NO|UNCLEAR|MANUAL_CHECK_REQUIRED",
          "reasoning": "사용자 계약서 제3조에 데이터 제공 목적이 명확히 기재되어 있음",
          "evidence": "제3조 1항: 데이터 분석 및 통계 작성을 위해 제공한다.",
          "recommendation": "적합함",
          "prompt_tokens": 800,
          "completion_tokens": 120,
          "total_tokens": 920
        },
        {
          "check_text": "제공 목적이 법령에 부합하는가?",
          "reference": "제3조",
          "result": "YES",
          "reasoning": "개인정보보호법 제17조에 부합하는 목적",
          "evidence": "...",
          "recommendation": "적합함",
          "prompt_tokens": 850,
          "completion_tokens": 110,
          "total_tokens": 960
        }
      ],
      "statistics": {
        "total_items": 5,
        "passed_items": 4,
        "failed_items": 1,
        "unclear_items": 0,
        "manual_check_items": 0,
        "pass_rate": 0.8
      }
    }
  ],
  "statistics": {
    "matched_std_articles": 12,
    "total_checklist_items": 60,
    "passed_items": 48,
    "failed_items": 8,
    "unclear_items": 2,
    "manual_check_items": 2,
    "overall_pass_rate": 0.8
  },
  "processing_time": 35.7,
  "verification_date": "2025-11-12T10:31:00"
}
```

### 체크리스트 결과 값 설명

- **YES**: 요구사항 충족
- **NO**: 요구사항 미충족
- **UNCLEAR**: 판단 불가 (정보 부족)
- **MANUAL_CHECK_REQUIRED**: 수동 검토 필요 (복잡한 법률 해석 등)

---

## A3 노드: 내용 분석 (Content Analysis)

### 개요
A1 매칭 결과를 기반으로 사용자 조항과 표준 조항의 내용을 비교하고 개선 제안을 생성합니다.

### 출력 구조

```json
{
  "contract_id": "string",
  "contract_type": "provide|process|transfer|brokerage_provider|brokerage_user",
  "total_articles": 15,
  "analyzed_articles": 12,
  "special_articles": 0,
  "article_analysis": [
    {
      "user_article_no": 3,
      "user_article_title": "데이터 제공 목적",
      "matched": true,
      "similarity": 0.92,
      "std_article_id": "제3조",
      "std_article_title": "데이터 제공 목적",
      "is_special": false,
      "reasoning": "표준계약서 제3조와 매칭됨",
      "matched_articles": [
        {
          "parent_id": "제3조",
          "global_id": "urn:std:provide:art:003",
          "title": "데이터 제공 목적",
          "score": 0.92,
          "num_sub_items": 3,
          "matched_sub_items": [0, 1, 2],
          "matched_chunks": [
            {
              "id": "provide_std_contract_chunk_008",
              "global_id": "urn:std:provide:art:003:sub:001",
              "text_raw": "...",
              "order_index": 0
            }
          ]
        }
      ],
      "matched_articles_details": [
        {
          "parent_id": "제3조",
          "global_id": "urn:std:provide:art:003",
          "title": "데이터 제공 목적",
          "combined_score": 0.92,
          "num_sub_items": 3,
          "matched_sub_items": [0, 1, 2],
          "avg_dense_score": 0.89,
          "sub_items_scores": [...]
        }
      ],
      "suggestions": [
        {
          "selected_standard_articles": ["제3조"],
          "issue_type": "content",
          "missing_items": [
            "데이터 제공 기간 명시: 표준계약서에는 제공 기간이 명시되어 있으나 사용자 계약서에는 누락됨",
            "제공 목적 외 사용 금지 조항: 표준계약서 제3조 3항의 목적 외 사용 금지 규정이 사용자 계약서에 없음"
          ],
          "insufficient_items": [
            "제공 방식 상세화: 제공 방식이 간략하게 기재되어 있어 구체화 필요",
            "데이터 형식 명시: 표준계약서에서는 데이터 형식(CSV, JSON 등)을 명시하도록 권장하나 사용자 계약서에는 모호함"
          ],
          "analysis": "**문제 여부**: 있음\n\n**누락된 내용**:\n- 데이터 제공 기간 명시: 표준계약서에는 제공 기간이 명시되어 있으나 사용자 계약서에는 누락됨\n- 제공 목적 외 사용 금지 조항: 표준계약서 제3조 3항의 목적 외 사용 금지 규정이 사용자 계약서에 없음\n\n**불충분한 내용**:\n- 제공 방식 상세화: 제공 방식이 간략하게 기재되어 있어 구체화 필요\n- 데이터 형식 명시: 표준계약서에서는 데이터 형식(CSV, JSON 등)을 명시하도록 권장하나 사용자 계약서에는 모호함\n\n**종합 분석**:\n사용자 계약서는 데이터 제공 목적을 명시하고 있으나, 제공 기간과 방식에 대한 상세 내용이 부족합니다. 표준계약서 제3조 2항의 '제공 기간은 계약 체결일로부터 1년'과 같은 명확한 기간 명시가 필요합니다. 또한 활용안내서에 따르면 제공 목적 외 사용 금지는 필수적인 보호 조항이므로 반드시 포함되어야 합니다.",
          "severity": "high|medium|low|info"
        }
      ],
      "analysis_timestamp": "2025-11-12T10:32:00"
    }
  ],
  "processing_time": 52.3,
  "analysis_timestamp": "2025-11-12T10:32:00"
}
```

### 제안 심각도 (Severity) 설명

- **high**: 누락 항목 3개 이상 또는 (누락 + 불충분) 5개 이상
- **medium**: 누락 항목 2개 이상 또는 불충분 항목 2개 이상
- **low**: 경미한 문제
- **info**: 문제 없음 (긍정적 분석)

### 누락/불충분 항목 형식

**missing_items** (누락된 내용):
- 문자열 배열 형식
- 각 항목은 "항목명: 설명" 형식
- 예시:
  - "제14조 제2항: 표준계약서 제14조 제2항에서는 데이터 유출이 데이터이용자의 고의 또는 과실로 발생한 경우, 데이터이용자가 자신의 비용과 책임으로 유출 범위를 확인하고 원인 및 재발 방지 방안을 수립하여 데이터제공자에게 통지할 의무를 명시하고 있습니다. 사용자 계약서 제4조 제2항에서는 데이터 유출 시 피해 확산을 막기 위한 조치와 사고 경위, 영향을 받은 데이터의 내용과 범위, 취한 조치 등을 통지하도록 규정하고 있으나, 유출의 원인 파악 및 재발 방지 방안 수립에 대한 명시적인 의무가 포함되어 있지 않습니다."
  - "제20조 (비밀유지의무): 표준계약서 제20조에서는 비밀유지의무에 대해 상세히 규정하고 있으며, 특히 비밀정보의 정의, 비밀유지의 범위, 예외 상황, 비밀정보의 공개 대상 등을 구체적으로 명시하고 있습니다. 사용자 계약서 제4조 제1항(바)에서는 임직원의 기밀 유지 서약서 작성 및 퇴직 후 접근 제한 조치를 규정하고 있으나, 비밀정보의 정의, 비밀유지의 범위 및 예외 상황, 비밀정보의 공개 대상 등에 대한 구체적인 규정이 누락되어 있습니다."

**insufficient_items** (불충분한 내용):
- 문자열 배열 형식
- 각 항목은 "항목명: 설명" 형식
- 예시:
  - "제12조 제1항: 표준계약서 제12조 제1항에서는 데이터이용자가 선량한 관리자의 주의 의무를 가지고 데이터를 관리·보관해야 한다고 규정하고 있습니다. 사용자 계약서 제4조 제1항에서는 업계 최고 수준의 보안 조치를 취할 것을 요구하고 있으나, 선량한 관리자의 주의 의무라는 법적 기준에 대한 명시가 부족합니다. 이는 법적 해석 및 책임 소재를 명확히 하기 위해 중요한 요소입니다."
  - "제14조 제1항: 표준계약서 제14조 제1항에서는 데이터 유출 시 데이터이용자가 즉시 데이터제공자에게 통지하고 피해를 최소화하기 위한 조치를 신속히 취할 의무를 규정하고 있습니다. 사용자 계약서 제4조 제2항에서는 보안 사고 통지 및 피해 확산 방지 조치를 명시하고 있으나, 데이터 유출의 구체적인 정의(예: 유출, 분실, 도난, 훼손 등)에 대한 명확한 언급이 부족합니다. 이는 데이터 유출의 범위를 명확히 하기 위해 필요합니다."

**analysis** (종합 분석):
- LLM의 전체 응답 텍스트
- 다음 섹션을 포함:
  - **문제 여부**: [있음/없음]
  - **누락된 내용**: (리스트)
  - **불충분한 내용**: (리스트)
  - **종합 분석**: (상세 설명)
- 참고 자료 인용 포함:
  - "활용안내서에서는 ~" 또는 "활용안내서에 따르면 ~"
  - "별지에서는 ~" 또는 "별지○에서는 ~"
  - "제○조에서는 ~" 또는 "제○조에 따르면 ~"

---

## 공통 필드 설명

### 계약 유형 (contract_type)
- `provide`: 제공형
- `process`: 가공형
- `transfer`: 창출형
- `brokerage_provider`: 중개거래형 (제공자)
- `brokerage_user`: 중개거래형 (이용자)

### Global ID 형식
- 형식: `urn:std:{contract_type}:art:{article_no:03d}:sub:{sub_no:03d}`
- 예시: `urn:std:provide:art:003:sub:001`

### 토큰 사용량
각 LLM 호출마다 다음 필드가 포함됩니다:
- `prompt_tokens`: 입력 토큰 수
- `completion_tokens`: 출력 토큰 수
- `total_tokens`: 총 토큰 수

---

## DB 저장 위치

### ValidationResult 테이블
- **A1 Stage 1**: `completeness_check` 필드
- **A1 Stage 2**: `completeness_check.missing_article_analysis` 필드에 추가
- **A2 Primary**: `checklist_validation` 필드
- **A2 Recovered**: `checklist_validation_recovered` 필드
- **A3 Primary**: `content_analysis` 필드
- **A3 Recovered**: `content_analysis_recovered` 필드

---

## 버전 정보
- 문서 버전: 1.0
- 최종 업데이트: 2025-11-12
- 작성자: Kiro AI
