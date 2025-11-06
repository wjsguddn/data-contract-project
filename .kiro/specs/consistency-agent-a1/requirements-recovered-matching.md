# 요구사항 문서 - 오탐지 복구 매칭 처리

## 소개

A1 노드의 누락 재검증 과정에서 발견된 오탐지(false positive) 조항들을 A2, A3 노드에서 처리할 수 있도록 데이터 구조를 변환하고 병렬 처리를 지원하는 기능을 구현합니다.

## 용어 정의

- **오탐지 (False Positive)**: 1차 매칭에서 누락된 것으로 판정되었으나, 역방향 재검증 결과 실제로는 사용자 계약서에 존재하는 것으로 확인된 표준 조항 (`is_truly_missing: false`)
- **역방향 재검증 (Reverse Verification)**: 누락된 표준 조항을 기준으로 사용자 계약서 전체를 검색하여 매칭을 재확인하는 프로세스
- **복구된 매칭 (Recovered Matching)**: 오탐지로 확인되어 매칭 관계가 복구된 조항 쌍 (표준 조항 ↔ 사용자 조항)
- **matching_details**: A1 노드가 생성하는 1차 매칭 결과 데이터 구조 (사용자 조항 → 표준 조항 방향, A2/A3가 사용)
- **recovered_matching_details**: 오탐지를 matching_details 형식으로 변환한 데이터 구조 (A2/A3가 동일하게 사용)
- **missing_article_analysis**: A1 노드의 누락 재검증 결과 데이터 구조 (표준 조항 → 사용자 조항 방향)
- **matching_types**: A2, A3 노드가 처리할 매칭 유형을 지정하는 파라미터 (["primary"], ["recovered"], ["primary", "recovered"])
- **Agent Orchestrator**: agent.py에서 A1, A2, A3 노드를 조율하는 통합 검증 태스크

## 핵심 개념

### 오탐지 복구의 필요성

1차 매칭(forward matching)은 **사용자 조항 → 표준 조항** 방향으로 검색합니다. 이 과정에서:
- 사용자 조항이 표준과 다른 제목/구조를 가진 경우 매칭 실패 가능
- 예: 표준 "제12조(손해배상)" ↔ 사용자 "제10조(책임의 범위)"

역방향 재검증(reverse verification)은 **표준 조항 → 사용자 조항** 방향으로 검색하여:
- 1차 매칭에서 놓친 매칭을 발견 (`is_truly_missing: false`)
- 이러한 오탐지는 **실제로는 매칭된 것**이므로 A2/A3에서 처리 필요
- 따라서 `matching_details`와 **동일한 JSON 구조**로 재구조화하여 A2/A3가 동일한 로직으로 처리

### 데이터 흐름

```
사용자 계약서 (15개 조문)
    ↓
[A1 Stage 1: 1차 매칭]
    ↓
matching_details (13개)
    ├─ matched: true (13개) ← A2/A3 batch1 처리
    └─ matched: false (2개) ← 사용자 특수 조항 (처리 안 함)
    
missing_standard_articles (7개 누락)
    ↓
[A1 Stage 2: 누락 재검증]
    ↓
missing_article_analysis (7개)
    ├─ is_truly_missing: true (5개) ← 실제 누락 (보고서에만 표시)
    └─ is_truly_missing: false (2개) ← 오탐지 (실제로는 매칭됨)
                                        ↓
                        [Agent Orchestrator: 재구조화]
                                        ↓
                        recovered_matching_details (2개)
                        - matching_details와 동일한 JSON 구조
                        - matched: true로 설정
                        - A2/A3 batch2 처리
```

### 왜 재구조화가 필요한가?

**문제:**
- `missing_article_analysis`는 표준 조항 중심 구조 (표준 → 사용자)
- A2/A3는 사용자 조항 중심 구조만 이해 (사용자 → 표준)

**해결:**
- `is_truly_missing: false` 데이터를 `matching_details` 형식으로 재구조화
- A2/A3는 코드 수정 없이 동일한 로직으로 처리 가능

## 요구사항

### 요구사항 1: 오탐지 조항 추출

**사용자 스토리:** Agent Orchestrator로서, A1 노드의 누락 재검증 결과에서 오탐지 조항만 필터링해야 합니다. 이를 통해 복구된 매칭만 별도로 처리할 수 있습니다.

#### 인수 기준

1. A1 노드가 완료될 때, 시스템은 ValidationResult.completeness_check에서 missing_article_analysis를 조회해야 합니다
2. missing_article_analysis를 조회할 때, 시스템은 is_truly_missing 필드를 확인해야 합니다
3. is_truly_missing이 false일 때, 시스템은 해당 항목을 오탐지로 식별해야 합니다
4. 오탐지 항목을 추출할 때, 시스템은 standard_article_id, matched_user_article, confidence를 포함해야 합니다
5. 오탐지가 없을 때, 시스템은 빈 리스트를 반환해야 합니다

### 요구사항 2: 오탐지 기반 recovered_matching_details 재구조화

**사용자 스토리:** Agent Orchestrator로서, 오탐지 조항(`is_truly_missing: false`)의 정보를 사용하여 A2, A3가 이해할 수 있는 `recovered_matching_details`를 새로 생성해야 합니다. 이를 통해 A2, A3 노드 코드 수정 없이 오탐지 조항을 처리할 수 있습니다.

**핵심 논리:** 
- `missing_article_analysis`는 **표준 조항 중심** 구조 (표준 → 사용자)
- A2/A3는 **사용자 조항 중심** 구조만 이해 (사용자 → 표준)
- `is_truly_missing: false`인 항목은 "실제로는 매칭됨"을 의미
- 이 정보를 **재구조화**하여 `matching_details`와 **동일한 JSON 구조** 생성
- 생성된 데이터는 `recovered_matching_details`라는 별도 필드에 저장
- A2/A3는 이 데이터를 `matching_details`와 동일하게 처리

**재구조화 매핑:**
```
missing_article_analysis (표준 중심)     →  recovered_matching_details (사용자 중심)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
standard_article_id                     →  matched_articles_global_ids
standard_article_title                  →  matched_articles_details[].title
matched_user_article.number             →  user_article_no
matched_user_article.article_id         →  user_article_id
matched_user_article.title              →  user_article_title
confidence                              →  matched_articles_details[].combined_score
candidates_analysis                     →  verification_details
(항상 true)                             →  matched
(항상 "reverse_verification")           →  matched_articles_details[].matched_via
```

#### 인수 기준

1. 오탐지 항목을 식별할 때, 시스템은 `missing_article_analysis`에서 `is_truly_missing: false`인 항목만 선택해야 합니다
2. 오탐지 항목을 처리할 때, 시스템은 `matched_user_article`에서 number, article_id, title을 추출해야 합니다
3. `matched_user_article`이 null일 때, 시스템은 해당 항목을 건너뛰고 경고를 로깅해야 합니다 (데이터 불일치)
4. 새 매칭 정보를 생성할 때, 시스템은 user_article_no, user_article_id, user_article_title, matched, matched_articles, matched_articles_global_ids를 포함해야 합니다
5. matched 필드를 설정할 때, 시스템은 항상 true로 설정해야 합니다 (오탐지는 실제로 매칭된 것이므로)
6. matched_articles를 생성할 때, 시스템은 standard_article_id에서 parent_id를 추출해야 합니다 (예: "urn:std:provide:art:012" → "제12조")
7. matched_articles_global_ids를 생성할 때, 시스템은 standard_article_id를 그대로 사용해야 합니다
8. matched_articles_details를 생성할 때, 시스템은 parent_id, global_id, title, combined_score, matched_via를 포함해야 합니다
9. matched_via 필드를 설정할 때, 시스템은 "reverse_verification"으로 설정해야 합니다 (1차 매칭과 구분)
10. combined_score를 설정할 때, 시스템은 오탐지 항목의 confidence 값을 사용해야 합니다
11. verification_details를 생성할 때, 시스템은 candidates_analysis를 기반으로 새로 생성해야 합니다
12. 생성된 매칭 정보는 기존 matching_details와 동일한 구조를 가져야 합니다 (A2/A3가 구분 없이 처리 가능)
13. sub_item_results를 생성할 때, 시스템은 빈 배열로 설정해야 합니다 (역방향 검증은 조 단위로만 수행)
14. 생성 과정에서 에러 발생 시, 시스템은 해당 항목을 건너뛰고 에러를 로깅해야 합니다
15. 생성된 recovered_matching_details는 missing_article_analysis와 별도로 저장되어야 합니다 (원본 데이터 보존)

### 요구사항 3: 복구된 매칭 정보 저장

**사용자 스토리:** Agent Orchestrator로서, 새로 생성한 recovered_matching_details를 DB에 저장해야 합니다. 이를 통해 A2, A3 노드가 해당 정보를 조회하여 처리할 수 있습니다.

**저장 위치:** `ValidationResult.completeness_check` JSON 필드 내부 (새 테이블 불필요)

#### 인수 기준

1. recovered_matching_details가 생성될 때, 시스템은 `ValidationResult.completeness_check`에 `recovered_matching_details` 필드를 추가해야 합니다
2. DB 저장 시, 시스템은 `update_completeness_check_partial_with_retry()` 헬퍼 함수를 사용해야 합니다
3. 부분 업데이트 시, 시스템은 기존 `completeness_check`의 다른 필드(`matching_details`, `missing_article_analysis` 등)를 유지해야 합니다
4. DB에 저장할 때, 시스템은 재시도 로직(최대 3회)을 통해 lock 에러를 처리해야 합니다
5. 오탐지가 없을 때, 시스템은 `recovered_matching_details`를 빈 리스트로 저장해야 합니다
6. `missing_article_analysis`는 원본 그대로 유지되어야 합니다 (수정하지 않음)
7. 저장 성공 시, 시스템은 True를 반환하고 로그를 남겨야 합니다
8. 저장 실패 시, 시스템은 False를 반환하고 에러를 로깅해야 합니다

#### 구현 예시

```python
from backend.shared.database import update_completeness_check_partial_with_retry

# recovered_matching_details 생성 후
success = update_completeness_check_partial_with_retry(
    contract_id=contract_id,
    partial_data={
        "recovered_matching_details": recovered_matching_details
    },
    max_retries=3
)

if success:
    logger.info(f"recovered_matching_details 저장 완료: {len(recovered_matching_details)}개")
else:
    logger.error(f"recovered_matching_details 저장 실패")
```

### 요구사항 4: A2 노드 matching_types 파라미터 지원

**사용자 스토리:** A2 노드로서, matching_types 파라미터를 통해 처리할 매칭 유형을 선택할 수 있어야 합니다. 이를 통해 1차 매칭과 오탐지 복구 매칭을 독립적으로 또는 통합하여 처리할 수 있습니다.

#### 인수 기준

1. A2 노드 태스크가 호출될 때, 시스템은 matching_types 파라미터를 받을 수 있어야 합니다
2. matching_types가 None일 때, 시스템은 기본값으로 ["primary"]를 사용해야 합니다
3. matching_types에 "primary"가 포함될 때, 시스템은 completeness_check["matching_details"]를 조회해야 합니다
4. matching_types에 "recovered"가 포함될 때, 시스템은 completeness_check["recovered_matching_details"]를 조회해야 합니다
5. 여러 matching_types가 지정될 때, 시스템은 모든 매칭 정보를 하나의 리스트로 통합해야 합니다
6. 통합된 매칭 정보로 A2 로직을 실행할 때, 시스템은 기존 체크리스트 검증 로직을 그대로 사용해야 합니다
7. recovered_matching_details가 존재하지 않을 때, 시스템은 빈 리스트로 처리해야 합니다
8. A2 결과를 저장할 때, 시스템은 matching_types에 따라 적절한 필드에 저장해야 합니다

### 요구사항 5: A3 노드 matching_types 파라미터 지원

**사용자 스토리:** A3 노드로서, matching_types 파라미터를 통해 처리할 매칭 유형을 선택할 수 있어야 합니다. 이를 통해 1차 매칭과 오탐지 복구 매칭을 독립적으로 또는 통합하여 처리할 수 있습니다.

#### 인수 기준

1. A3 노드 태스크가 호출될 때, 시스템은 matching_types 파라미터를 받을 수 있어야 합니다
2. matching_types가 None일 때, 시스템은 기본값으로 ["primary"]를 사용해야 합니다
3. matching_types에 "primary"가 포함될 때, 시스템은 completeness_check["matching_details"]를 조회해야 합니다
4. matching_types에 "recovered"가 포함될 때, 시스템은 completeness_check["recovered_matching_details"]를 조회해야 합니다
5. 여러 matching_types가 지정될 때, 시스템은 모든 매칭 정보를 하나의 리스트로 통합해야 합니다
6. 통합된 매칭 정보로 A3 로직을 실행할 때, 시스템은 기존 내용 분석 로직을 그대로 사용해야 합니다
7. recovered_matching_details가 존재하지 않을 때, 시스템은 빈 리스트로 처리해야 합니다
8. A3 결과를 저장할 때, 시스템은 matching_types에 따라 적절한 필드에 저장해야 합니다

### 요구사항 6: 병렬 처리 지원

**사용자 스토리:** Agent Orchestrator로서, 1차 매칭과 오탐지 복구 매칭을 병렬로 처리하여 전체 검증 시간을 단축해야 합니다. 이를 통해 사용자에게 더 빠른 검증 결과를 제공할 수 있습니다.

#### 인수 기준

1. A1 노드가 1차 매칭을 완료할 때, 시스템은 즉시 A2, A3 batch1을 시작해야 합니다 (matching_types=["primary"])
2. A2, A3 batch1이 실행되는 동안, 시스템은 A1 누락 재검증을 병렬로 수행해야 합니다
3. A1 누락 재검증이 완료되고 오탐지가 발견될 때, 시스템은 recovered_matching_details를 DB에 저장해야 합니다
4. recovered_matching_details가 저장될 때, 시스템은 A2, A3 batch2를 시작해야 합니다 (matching_types=["recovered"])
5. A2, A3 batch1과 batch2가 모두 완료될 때, 시스템은 두 결과를 별도로 저장해야 합니다
6. 오탐지가 없을 때, 시스템은 batch2를 실행하지 않아야 합니다
7. batch1 또는 batch2가 실패할 때, 시스템은 에러를 로깅하고 다른 배치는 계속 진행해야 합니다

### 요구사항 7: 결과 저장 구조

**사용자 스토리:** 시스템 관리자로서, 1차 매칭 결과와 오탐지 복구 결과를 구분하여 저장해야 합니다. 이를 통해 각 배치의 결과를 독립적으로 추적하고 리포트 에이전트에서 통합할 수 있습니다.

#### 인수 기준

1. A2 batch1 결과를 저장할 때, 시스템은 ValidationResult.checklist_validation에 저장해야 합니다
2. A2 batch2 결과를 저장할 때, 시스템은 ValidationResult.checklist_validation_recovered에 저장해야 합니다
3. A3 batch1 결과를 저장할 때, 시스템은 ValidationResult.content_analysis에 저장해야 합니다
4. A3 batch2 결과를 저장할 때, 시스템은 ValidationResult.content_analysis_recovered에 저장해야 합니다
5. batch2 결과가 없을 때, 시스템은 _recovered 필드를 null 또는 빈 객체로 유지해야 합니다
6. 결과를 조회할 때, 시스템은 기본 필드와 _recovered 필드를 모두 반환해야 합니다

### 요구사항 8: parent_id 추출 유틸리티

**사용자 스토리:** 개발자로서, global_id에서 parent_id를 추출하는 유틸리티 함수가 필요합니다. 이를 통해 오탐지 매칭 정보를 변환할 때 일관된 방식으로 parent_id를 생성할 수 있습니다.

#### 인수 기준

1. global_id를 입력받을 때, 시스템은 URN 형식을 파싱해야 합니다 (예: "urn:std:provide:art:012")
2. URN을 파싱할 때, 시스템은 정규표현식을 사용하여 조항 번호를 추출해야 합니다
3. 조항 번호를 추출할 때, 시스템은 ":art:(\d+)" 패턴을 사용해야 합니다
4. 조항 번호가 추출될 때, 시스템은 "제{번호}조" 형식으로 parent_id를 생성해야 합니다 (예: "제12조")
5. 조항 번호 추출에 실패할 때, 시스템은 원본 global_id를 반환해야 합니다
6. parent_id를 생성할 때, 시스템은 앞의 0을 제거해야 합니다 (예: "012" → "12")


### 요구사항 9: 로깅 및 모니터링

**사용자 스토리:** 시스템 관리자로서, 오탐지 복구 프로세스의 각 단계를 로깅하여 추적할 수 있어야 합니다. 이를 통해 문제 발생 시 디버깅하고 성능을 모니터링할 수 있습니다.

#### 인수 기준

1. 오탐지를 추출할 때, 시스템은 발견된 오탐지 개수를 로깅해야 합니다
2. 오탐지를 변환할 때, 시스템은 각 변환된 매칭 정보를 로깅해야 합니다
3. recovered_matching_details를 저장할 때, 시스템은 저장 성공 여부를 로깅해야 합니다
4. A2, A3 batch2를 시작할 때, 시스템은 처리할 조항 개수를 로깅해야 합니다
5. batch2가 완료될 때, 시스템은 처리 시간과 결과 요약을 로깅해야 합니다
6. 에러가 발생할 때, 시스템은 에러 메시지와 스택 트레이스를 로깅해야 합니다

### 요구사항 10: 하위 호환성 유지

**사용자 스토리:** 개발자로서, 기존 A2, A3 노드 호출 방식이 계속 작동해야 합니다. 이를 통해 점진적으로 새로운 기능을 도입하고 기존 코드를 보호할 수 있습니다.

#### 인수 기준

1. matching_types 파라미터가 제공되지 않을 때, 시스템은 기본값 ["primary"]를 사용해야 합니다
2. 기본값으로 실행될 때, 시스템은 기존 동작과 동일하게 작동해야 합니다 (matching_details만 처리)
3. recovered_matching_details가 없을 때, 시스템은 에러 없이 빈 리스트로 처리해야 합니다
4. 기존 ValidationResult 필드(checklist_validation, content_analysis)는 변경되지 않아야 합니다
5. 새로운 필드(_recovered)는 선택적으로 추가되어야 합니다

## 데이터 구조

### missing_article_analysis (A1 출력 - 전체)
```json
[
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
  },
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
        "user_article_no": 10,
        "user_article_id": "user_article_010",
        "user_article_title": "책임의 범위",
        "score": 0.78,
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
]
```

### recovered_matching_details (재구조화 후 - 오탐지만, matching_details와 동일한 구조)
```json
[
  {
    "user_article_no": 10,
    "user_article_id": "user_article_010",
    "user_article_title": "책임의 범위",
    "matched": true,
    "matched_articles": ["제12조"],
    "matched_articles_global_ids": ["urn:std:provide:art:012"],
    "matched_articles_details": [
      {
        "parent_id": "제12조",
        "global_id": "urn:std:provide:art:012",
        "title": "손해배상",
        "combined_score": 0.85,
        "matched_via": "reverse_verification",
        "num_sub_items": 0,
        "matched_sub_items": [],
        "avg_dense_score": 0.82,
        "avg_dense_score_raw": 0.80,
        "avg_sparse_score": 0.15,
        "avg_sparse_score_raw": 0.12,
        "sub_items_scores": []
      }
    ],
    "sub_item_results": [],
    "verification_details": [
      {
        "candidate_id": "user_article_010",
        "is_match": true,
        "confidence": 0.85,
        "reasoning": "손해배상 책임의 범위와 한도를 명시하고 있어 표준계약서의 '손해배상' 조항과 실질적으로 동일"
      }
    ]
  }
]
```

### ValidationResult.completeness_check (확장)
```json
{
  "contract_id": "contract_20240101_123456",
  "contract_type": "provide",
  "total_user_articles": 15,
  "matched_user_articles": 13,
  "total_standard_articles": 20,
  "matched_standard_articles": 18,
  "missing_standard_articles": [
    {
      "parent_id": "제5조",
      "title": "개인정보의 제3자 제공",
      "chunks": [...]
    }
  ],
  "missing_article_analysis": [
    {
      "standard_article_id": "urn:std:provide:art:005",
      "is_truly_missing": true,
      ...
    },
    {
      "standard_article_id": "urn:std:provide:art:012",
      "is_truly_missing": false,
      ...
    }
  ],
  "matching_details": [
    {
      "user_article_no": 1,
      "user_article_id": "user_article_001",
      "matched": true,
      ...
    }
  ],
  "recovered_matching_details": [
    {
      "user_article_no": 10,
      "user_article_id": "user_article_010",
      "matched": true,
      "matched_via": "reverse_verification",
      ...
    }
  ],
  "processing_time": 45.23,
  "verification_date": "2024-01-01T12:34:56.789Z"
}
```

### ValidationResult 전체 구조 (확장)
```json
{
  "id": 1,
  "contract_id": "contract_20240101_123456",
  "contract_type": "provide",
  
  "completeness_check": {
    "matching_details": [...],
    "recovered_matching_details": [...],
    "missing_article_analysis": [...]
  },
  
  "checklist_validation": {
    "total_checklist_items": 45,
    "verified_items": 40,
    "passed_items": 35,
    "failed_items": 5,
    "articles": [...]
  },
  
  "checklist_validation_recovered": {
    "total_checklist_items": 5,
    "verified_items": 5,
    "passed_items": 4,
    "failed_items": 1,
    "articles": [...]
  },
  
  "content_analysis": {
    "total_articles": 13,
    "analyzed_articles": 13,
    "special_articles": 2,
    "articles": [...]
  },
  
  "content_analysis_recovered": {
    "total_articles": 1,
    "analyzed_articles": 1,
    "special_articles": 0,
    "articles": [...]
  },
  
  "overall_score": 0.0,
  "recommendations": [],
  "created_at": "2024-01-01T12:34:56.789Z",
  "updated_at": "2024-01-01T12:35:30.123Z"
}
```

## 처리 플로우 (병렬 최적화)

### 용어 정의
- **batch1**: 1차 배치 - `matching_details` 처리 (1차 매칭 성공 조문)
- **batch2**: 2차 배치 - `recovered_matching_details` 처리 (오탐지 복구 조문)

### Phase 1: A1-Stage1 (순차)
```
A1-Stage1 실행
├─ 사용자 15개 조문 → 표준 조문 매칭
├─ LLM 검증
├─ 결과:
│   ├─ matching_details: 13개 매칭 성공
│   ├─ 2개 매칭 실패 (사용자 특수 조항)
│   └─ missing_standard_articles: 7개 누락 후보
└─ DB 저장 완료
```

### Phase 2: 병렬 실행 (최대 5개 스레드)

#### 즉시 시작 (3개 스레드)

**Thread 1: A1-Stage2 (누락 재검증)**
```
├─ 7개 누락 조문 역방향 검색 (시간 걸림)
├─ LLM 재검증
├─ missing_article_analysis 생성:
│   ├─ is_truly_missing: true (5개) → 실제 누락
│   └─ is_truly_missing: false (2개) → 오탐지!
├─ 오탐지 재구조화 (빠름):
│   └─ recovered_matching_details 생성 (2개)
├─ DB 저장 (recovered_matching_details) ← 여기까지만 batch2가 기다림
├─ batch2 트리거 (비동기) ← 즉시 시작!
└─ 나머지 작업 계속... (batch2는 독립 실행)
```

**Thread 2: A2 batch1**
```
├─ matching_details 로드 (13개)
├─ 체크리스트 검증 수행
└─ checklist_validation 저장
```

**Thread 3: A3 batch1**
```
├─ matching_details 로드 (13개)
├─ 내용 분석 수행
└─ content_analysis 저장
```

#### A1-Stage2가 recovered_matching_details 저장 후 시작 (2개 스레드 추가)

**Thread 4: A2 batch2**
```
├─ recovered_matching_details 로드 (2개)
├─ 체크리스트 검증 수행
└─ checklist_validation_recovered 저장
```

**Thread 5: A3 batch2**
```
├─ recovered_matching_details 로드 (2개)
├─ 내용 분석 수행
└─ content_analysis_recovered 저장
```

### 타이밍 다이어그램

```
시간 →

A1-Stage1 ████ (완료)
            ↓
            ├─ A1-Stage2 ████████████████████ (계속 실행)
            │          ↓ (recovered 저장)
            │          ├─ A2 batch2 ████████ (2개 조문)
            │          └─ A3 batch2 ████████ (2개 조문)
            │
            ├─ A2 batch1 ████████████████ (13개 조문)
            └─ A3 batch1 ████████████████ (13개 조문)

최대 5개 스레드 동시 실행!
```

### 재구조화 과정 (A1-Stage2 내부)

```
입력: missing_article_analysis (표준 중심)
{
  "standard_article_id": "urn:std:provide:art:012",
  "is_truly_missing": false,  ← 오탐지
  "matched_user_article": {
    "number": 10,
    "article_id": "user_article_010",
    "title": "책임의 범위"
  }
}
        ↓ 재구조화
출력: recovered_matching_details (사용자 중심)
{
  "user_article_no": 10,
  "user_article_id": "user_article_010",
  "user_article_title": "책임의 범위",
  "matched": true,
  "matched_articles": ["제12조"],
  "matched_articles_global_ids": ["urn:std:provide:art:012"]
}
```

### 핵심 포인트

1. **병렬 실행 가능한 이유**
   - batch1: 13개 조문 처리
   - batch2: 2개 조문 처리 (완전히 다른 조문)
   - 충돌 없음: 서로 다른 데이터, 다른 DB 필드

2. **batch2가 기다리는 것**
   - ❌ A1-Stage2 전체 완료
   - ✅ `recovered_matching_details` DB 저장만

3. **시간 절약**
   ```
   기존 순차: A1-S1 + A1-S2 + A2-b1 + A2-b2 + A3-b1 + A3-b2
   새로운 병렬: A1-S1 + max(A1-S2, batch1)
   ```

4. **독립성**
   - A1-Stage2는 batch2 트리거 후 계속 실행
   - batch2는 A1-Stage2 완료를 기다리지 않음
   - 각 배치는 독립적으로 실패 가능

### 최종 결과

```
총 처리 조문: 15개
├─ batch1: 13개 (1차 매칭)
└─ batch2: 2개 (오탐지 복구)

실제 누락: 5개 (보고서에 표시)

처리 시간: 최소화 (최대 병렬화)
```

## 데이터 재구조화 예시

### 입력: missing_article_analysis의 오탐지 항목 (A1 Stage 2 출력)

**구조:** 표준 조항 중심 (표준 → 사용자)

```json
{
  "standard_article_id": "urn:std:provide:art:012",
  "standard_article_title": "손해배상",
  "is_truly_missing": false,  // ← 핵심: 실제로는 매칭됨!
  "confidence": 0.85,
  "matched_user_article": {    // ← 매칭된 사용자 조항 정보
    "number": 10,
    "article_id": "user_article_010",
    "title": "책임의 범위"
  },
  "reasoning": "제10조(책임의 범위)에 손해배상 관련 내용이 포함되어 있음",
  "evidence": "제10조 본문에서 손해배상 책임 범위를 명시",
  "recommendation": "제10조에 손해배상 내용이 포함되어 있으나, 표준계약서와 구조가 다름",
  "risk_assessment": "낮음 - 내용은 포함되어 있으나 구조 차이",
  "top_candidates": [...],
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

### 출력: recovered_matching_details (새로 생성, matching_details와 동일한 구조)

**구조:** 사용자 조항 중심 (사용자 → 표준) - A2/A3가 이해하는 형식

```json
{
  // 사용자 조항 정보 (matched_user_article에서 추출)
  "user_article_no": 10,
  "user_article_id": "user_article_010",
  "user_article_title": "책임의 범위",
  
  // 매칭 상태 (항상 true)
  "matched": true,
  
  // 매칭된 표준 조항 (standard_article_id에서 변환)
  "matched_articles": ["제12조"],
  "matched_articles_global_ids": ["urn:std:provide:art:012"],
  
  // 매칭 상세 정보
  "matched_articles_details": [
    {
      "parent_id": "제12조",
      "global_id": "urn:std:provide:art:012",
      "title": "손해배상",
      "combined_score": 0.85,
      "matched_via": "reverse_verification",  // ← 1차 매칭과 구분
      
      // 하위항목 정보 (역방향 검증은 조 단위만)
      "num_sub_items": 0,
      "matched_sub_items": [],
      
      // 점수 정보 (역방향 검증은 상세 점수 없음)
      "avg_dense_score": 0.0,
      "avg_dense_score_raw": 0.0,
      "avg_sparse_score": 0.0,
      "avg_sparse_score_raw": 0.0,
      "sub_items_scores": []
    }
  ],
  
  // 하위항목별 매칭 (역방향 검증은 조 단위만)
  "sub_item_results": [],
  
  // LLM 검증 결과 (candidates_analysis에서 변환)
  "verification_details": [
    {
      "candidate_article": "제12조",
      "is_match": true,
      "confidence": 0.85,
      "reasoning": "손해배상 책임의 범위와 한도를 명시하고 있어 표준계약서의 '손해배상' 조항과 실질적으로 동일"
    }
  ]
}
```

### 재구조화 핵심 포인트

1. **방향 전환**: 표준 중심 → 사용자 중심
2. **구조 통일**: `matching_details`와 동일한 JSON 구조
3. **필수 필드**: A2/A3가 요구하는 모든 필드 포함
4. **출처 표시**: `matched_via: "reverse_verification"`으로 1차 매칭과 구분
5. **점수 제한**: 역방향 검증은 조 단위 점수만 있음 (하위항목 점수 없음)

## 프론트엔드 표시 (추후 구현)

**참고:** 프론트엔드는 기존 "누락 조문 재검증 결과" 섹션 아래에 `recovered_matching_details`를 간단히 표시하면 됩니다. 상세 UI는 백엔드 구현 완료 후 설계합니다.

## 제약사항

1. A1 노드 코드는 수정하지 않음 (missing_article_analysis 구조 유지)
2. A2, A3 노드의 핵심 로직은 수정하지 않음 (matching_types 파라미터만 추가)
3. 기존 ValidationResult 필드는 변경하지 않음 (새 필드만 추가)
4. 오탐지가 없는 경우에도 정상 동작해야 함
5. batch1과 batch2는 독립적으로 실패할 수 있음 (부분 실패 허용)
6. 프론트엔드는 기존 UI 구조를 유지하며 새 섹션만 추가
