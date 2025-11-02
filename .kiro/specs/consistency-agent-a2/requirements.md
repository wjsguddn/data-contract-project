# 요구사항 문서

## 소개

A2 노드(체크리스트 검증)는 A1 노드에서 생성된 매칭 결과를 기반으로 활용안내서의 체크리스트 항목을 검증합니다. 사용자 계약서의 각 조항이 매칭된 표준 조항의 체크리스트 요구사항을 충족하는지 LLM을 사용하여 평가하고, 결과를 구조화된 형태로 저장합니다.

## 용어 정의

- **체크리스트 검증 (Checklist Validation)**: 사용자 계약서 조항이 표준 조항의 체크리스트 항목을 충족하는지 확인하는 프로세스
- **체크리스트 항목 (Checklist Item)**: 활용안내서에 정의된 검증 질문 (예: "개인의 경우 이름, 법인의 경우 상호 등이 기재되어 있는가?")
- **매칭 맵 (Matching Map)**: A1 노드에서 생성된 사용자 조항과 표준 조항 간의 매칭 관계 (parsed_data["matching_map"])
- **Global ID**: 표준 조항을 고유하게 식별하는 URN 형식 ID (예: "urn:std:brokerage_provider:art:001")
- **ChecklistLoader**: 활용안내서 체크리스트 데이터를 로드하고 global_id로 필터링하는 컴포넌트
- **ChecklistVerifier**: LLM을 사용하여 사용자 조항이 체크리스트 항목을 충족하는지 검증하는 컴포넌트
- **ChecklistCheckNode**: A2 노드의 메인 클래스로, ChecklistLoader와 ChecklistVerifier를 조율하여 체크리스트 검증을 수행
- **검증 결과 (Verification Result)**: 각 체크리스트 항목에 대한 YES/NO 답변, 근거 텍스트, 신뢰도 점수

## 현재 시스템 구조

### A1 노드 출력 (A2 입력)

**ValidationResult.completeness_check (A1 출력)**
```json
{
    "matching_details": [
        {
            "user_article_no": 1,
            "user_article_id": "user_article_001",
            "user_article_title": "목적",
            "matched": true,
            "matched_articles": ["제1조"],
            "matched_articles_global_ids": ["urn:std:brokerage_provider:art:001"],
            "matched_articles_details": [
                {
                    "parent_id": "제1조",
                    "global_id": "urn:std:brokerage_provider:art:001",
                    "title": "목적",
                    "combined_score": 0.85
                }
            ]
        },
        {
            "user_article_no": 4,
            "user_article_id": "user_article_004",
            "user_article_title": "데이터 제공",
            "matched": true,
            "matched_articles": ["제9조", "제11조"],
            "matched_articles_global_ids": [
                "urn:std:brokerage_provider:art:009",
                "urn:std:brokerage_provider:art:011"
            ],
            "matched_articles_details": [
                {
                    "parent_id": "제9조",
                    "global_id": "urn:std:brokerage_provider:art:009",
                    "title": "데이터 제공 범위",
                    "combined_score": 0.82
                },
                {
                    "parent_id": "제11조",
                    "global_id": "urn:std:brokerage_provider:art:011",
                    "title": "제공 기간",
                    "combined_score": 0.78
                }
            ]
        }
    ],
    "missing_standard_articles": [
        {
            "parent_id": "제5조",
            "title": "데이터 보안"
        }
    ]
}
```

### 체크리스트 데이터 구조

**활용안내서 체크리스트 (JSON)**
```json
[
    {
        "check_text": "개인의 경우 이름, 법인의 경우 상호 등이 기재되어 있는가?",
        "reference": "제1조 (106쪽)",
        "global_id": "urn:std:brokerage_provider:art:001"
    },
    {
        "check_text": "당사자가 개인(개인사업자포함)인가, 법인인가?",
        "reference": "제1조 (106쪽)",
        "global_id": "urn:std:brokerage_provider:art:001"
    },
    {
        "check_text": "계약서 본문에서 사용되는 용어 중 해석상 논란이 될 만한 부분이 모두 정의되어 있는가?",
        "reference": "제2조 (106쪽)",
        "global_id": "urn:std:brokerage_provider:art:002"
    }
]
```

## 목표 데이터 구조

### ValidationResult.checklist_validation (A2 출력)

```json
{
    "total_checklist_items": 45,
    "verified_items": 42,
    "passed_items": 35,
    "failed_items": 7,
    "user_article_results": [
        {
            "user_article_no": 1,
            "user_article_id": "user_article_001",
            "user_article_title": "목적",
            "matched_std_global_ids": ["urn:std:brokerage_provider:art:001"],
            "checklist_results": [
                {
                    "check_text": "개인의 경우 이름, 법인의 경우 상호 등이 기재되어 있는가?",
                    "reference": "제1조 (106쪽)",
                    "std_global_id": "urn:std:brokerage_provider:art:001",
                    "result": "YES",
                    "evidence": "제1조에서 '갑: 주식회사 데이터허브(대표이사 홍길동)' 명시",
                    "confidence": 0.95
                }
            ]
        },
        {
            "user_article_no": 4,
            "user_article_id": "user_article_004",
            "user_article_title": "데이터 제공",
            "matched_std_global_ids": [
                "urn:std:brokerage_provider:art:009",
                "urn:std:brokerage_provider:art:011"
            ],
            "checklist_results": [
                {
                    "check_text": "데이터 제공 범위가 명시되어 있는가?",
                    "reference": "제9조 (108쪽)",
                    "std_global_id": "urn:std:brokerage_provider:art:009",
                    "result": "YES",
                    "evidence": "제4조 2항에서 '개인정보를 제외한 모든 거래 데이터' 명시",
                    "confidence": 0.88
                },
                {
                    "check_text": "제공 기간이 명확한가?",
                    "reference": "제11조 (109쪽)",
                    "std_global_id": "urn:std:brokerage_provider:art:011",
                    "result": "NO",
                    "evidence": null,
                    "confidence": 0.82
                }
            ]
        }
    ],
    "processing_time": 12.5,
    "verification_date": "2025-01-01T00:00:00Z"
}
```

## 요구사항

### 요구사항 1: A1 매칭 결과 로드 및 파싱

**사용자 스토리:** A2 노드로서, A1 노드가 생성한 매칭 결과를 로드하여 검증 대상 조항을 식별해야 합니다. 이를 통해 어떤 사용자 조항에 대해 어떤 체크리스트를 검증할지 결정할 수 있습니다.

#### 인수 기준

1. A2 노드가 시작될 때, 시스템은 ValidationResult.completeness_check에서 "matching_details"를 조회해야 합니다
2. completeness_check가 존재하지 않을 때, 시스템은 에러를 발생시키고 A2 노드 실행을 중단해야 합니다
3. matching_details가 존재할 때, 시스템은 배열을 추출해야 합니다
4. matching_details 배열을 순회할 때, 시스템은 각 항목에서 user_article_no, user_article_id, matched_articles_global_ids를 추출해야 합니다
5. matched_articles_global_ids를 처리할 때, 시스템은 각 표준 조항의 global_id를 추출해야 합니다
6. matched가 false인 사용자 조항은 체크리스트 검증에서 제외해야 합니다

### 요구사항 2: Global ID 기반 체크리스트 필터링

**사용자 스토리:** A2 노드로서, 매칭된 표준 조항의 global_id를 사용하여 관련 체크리스트 항목만 필터링해야 합니다. 이를 통해 불필요한 체크리스트 검증을 피하고 효율성을 높일 수 있습니다.

#### 인수 기준

1. 체크리스트를 로드할 때, 시스템은 활용안내서 체크리스트 JSON 파일을 읽어야 합니다
2. 체크리스트 데이터를 파싱할 때, 시스템은 각 항목의 check_text, reference, global_id를 추출해야 합니다
3. 체크리스트를 필터링할 때, 시스템은 global_id를 키로 사용하여 그룹핑해야 합니다
4. 사용자 조항을 처리할 때, 시스템은 해당 조항의 matched_articles_global_ids 리스트를 사용하여 관련 체크리스트만 추출해야 합니다
5. 여러 표준 조항이 매칭된 경우, 시스템은 모든 매칭된 표준 조항의 체크리스트를 합쳐야 합니다
6. 중복된 체크리스트 항목이 있을 때, 시스템은 중복을 제거해야 합니다 (check_text 기준)

### 요구사항 3: LLM 기반 체크리스트 검증

**사용자 스토리:** A2 노드로서, 사용자 조항 내용과 체크리스트 질문을 LLM에 전달하여 각 항목의 충족 여부를 판단해야 합니다. 이를 통해 자동화된 계약서 검증을 수행할 수 있습니다.

#### 인수 기준

1. 체크리스트 검증을 수행할 때, 시스템은 사용자 조항의 전체 텍스트를 컨텍스트로 사용해야 합니다
2. 체크리스트 검증을 수행할 때, 시스템은 각 체크리스트 항목의 check_text를 질문으로 사용해야 합니다
3. LLM 프롬프트를 구성할 때, 시스템은 "다음 계약서 조항이 이 요구사항을 충족하는가?"라는 형식으로 질문해야 합니다
4. LLM 응답을 파싱할 때, 시스템은 "YES", "NO", 또는 "UNCLEAR" 결과를 추출해야 합니다
5. LLM 응답을 파싱할 때, 시스템은 판단 근거가 되는 텍스트를 evidence로 추출해야 합니다
6. LLM 응답을 파싱할 때, 시스템은 신뢰도 점수(0.0~1.0)를 추출해야 합니다
7. 신뢰도가 0.7 미만일 때, 시스템은 표준 조항 컨텍스트를 추가하여 재검증을 수행해야 합니다
8. 재검증 후에도 신뢰도가 0.7 미만일 때, 시스템은 결과를 "UNCLEAR"로 설정하고 requires_manual_review를 True로 표시해야 합니다
9. LLM 호출이 실패할 때, 시스템은 해당 체크리스트 항목을 건너뛰고 다음 항목을 처리해야 합니다

### 요구사항 4: 배치 처리를 통한 효율성 향상

**사용자 스토리:** 시스템 관리자로서, 한 조항의 여러 체크리스트 항목을 한 번의 LLM 호출로 처리하여 API 비용과 처리 시간을 줄여야 합니다.

#### 인수 기준

1. 체크리스트 검증을 수행할 때, 시스템은 동일한 사용자 조항에 대한 여러 체크리스트 항목을 그룹핑해야 합니다
2. 배치 프롬프트를 구성할 때, 시스템은 최대 10개의 체크리스트 항목을 한 번에 포함해야 합니다
3. 배치 프롬프트를 구성할 때, 시스템은 각 체크리스트 항목에 번호를 부여하여 구분해야 합니다
4. 배치 응답을 파싱할 때, 시스템은 각 체크리스트 항목에 대한 개별 결과를 추출해야 합니다
5. 체크리스트 항목이 10개를 초과할 때, 시스템은 여러 배치로 나누어 처리해야 합니다
6. 배치 처리가 실패할 때, 시스템은 개별 항목 처리로 폴백해야 합니다

### 요구사항 5: 검증 결과 저장

**사용자 스토리:** 개발자로서, 체크리스트 검증 결과를 ValidationResult에 저장하여 다른 노드와 보고서 생성에서 활용할 수 있어야 합니다.

#### 인수 기준

1. A2 노드가 완료될 때, 시스템은 ValidationResult.checklist_validation에 검증 결과를 저장해야 합니다
2. 검증 결과를 저장할 때, 시스템은 total_checklist_items, verified_items, passed_items, failed_items를 계산해야 합니다
3. 검증 결과를 저장할 때, 시스템은 user_article_results 배열에 각 사용자 조항의 결과를 포함해야 합니다
4. 각 사용자 조항 결과를 저장할 때, 시스템은 user_article_no, user_article_id, user_article_title, matched_std_global_ids, checklist_results를 포함해야 합니다
5. 각 체크리스트 결과를 저장할 때, 시스템은 check_text, reference, std_global_id, result, evidence, confidence를 포함해야 합니다
6. 검증 결과를 저장할 때, 시스템은 processing_time과 verification_date를 포함해야 합니다
7. ValidationResult를 저장할 때, 시스템은 DB에 변경사항을 커밋해야 합니다

### 요구사항 6: M:N 관계 처리

**사용자 스토리:** A2 노드로서, 하나의 사용자 조항이 여러 표준 조항과 매칭된 경우 모든 관련 체크리스트를 검증해야 합니다. 이를 통해 복잡한 매칭 시나리오를 정확하게 처리할 수 있습니다.

#### 인수 기준

1. 사용자 조항이 여러 표준 조항과 매칭된 경우, 시스템은 모든 매칭된 표준 조항의 체크리스트를 수집해야 합니다
2. 여러 표준 조항의 체크리스트를 수집할 때, 시스템은 각 체크리스트 항목에 출처 std_global_id를 유지해야 합니다
3. 중복된 체크리스트 항목이 있을 때, 시스템은 check_text가 동일한 항목을 하나로 통합해야 합니다
4. 중복 항목을 통합할 때, 시스템은 모든 관련 std_global_id를 기록해야 합니다
5. 검증 결과를 저장할 때, 시스템은 각 체크리스트 항목이 어떤 std_global_id에서 왔는지 명시해야 합니다

### 요구사항 7: 에러 처리 및 로깅

**사용자 스토리:** 시스템 관리자로서, 체크리스트 검증 중 발생하는 에러를 적절히 처리하고 로깅하여 문제를 추적할 수 있어야 합니다.

#### 인수 기준

1. 매칭 맵이 없을 때, 시스템은 명확한 에러 메시지와 함께 예외를 발생시켜야 합니다
2. 체크리스트 파일을 로드할 수 없을 때, 시스템은 에러를 로깅하고 예외를 발생시켜야 합니다
3. LLM 호출이 실패할 때, 시스템은 에러를 로깅하고 해당 항목을 건너뛰어야 합니다
4. 체크리스트 검증 시작 시, 시스템은 처리할 사용자 조항 수와 체크리스트 항목 수를 로깅해야 합니다
5. 각 사용자 조항 처리 완료 시, 시스템은 진행 상황을 로깅해야 합니다 (예: "3/15 조항 처리 완료")
6. A2 노드 완료 시, 시스템은 총 처리 시간, 통과/실패 항목 수를 로깅해야 합니다

### 요구사항 8: 체크리스트 데이터 캐싱

**사용자 스토리:** 개발자로서, 체크리스트 데이터를 메모리에 캐싱하여 반복적인 파일 읽기를 피하고 성능을 향상시켜야 합니다.

#### 인수 기준

1. ChecklistLoader가 초기화될 때, 시스템은 체크리스트 JSON 파일을 한 번만 읽어야 합니다
2. 체크리스트 데이터를 로드한 후, 시스템은 global_id를 키로 하는 딕셔너리로 인덱싱해야 합니다
3. 체크리스트를 조회할 때, 시스템은 파일을 다시 읽지 않고 메모리 캐시를 사용해야 합니다
4. 여러 사용자 조항이 동일한 표준 조항과 매칭된 경우, 시스템은 캐시된 체크리스트를 재사용해야 합니다
5. 계약 유형이 변경될 때, 시스템은 해당 계약 유형의 체크리스트를 새로 로드해야 합니다

### 요구사항 9: 검증 결과 통계

**사용자 스토리:** 분석가로서, 체크리스트 검증 결과의 통계를 확인하여 계약서의 전반적인 품질을 평가할 수 있어야 합니다.

#### 인수 기준

1. 검증 완료 시, 시스템은 전체 체크리스트 항목 수(total_checklist_items)를 계산해야 합니다
2. 검증 완료 시, 시스템은 실제로 검증된 항목 수(verified_items)를 계산해야 합니다
3. 검증 완료 시, 시스템은 통과한 항목 수(passed_items)를 계산해야 합니다 (result="YES")
4. 검증 완료 시, 시스템은 실패한 항목 수(failed_items)를 계산해야 합니다 (result="NO")
5. 통계를 계산할 때, 시스템은 중복 제거된 체크리스트 항목을 기준으로 해야 합니다
6. 통계를 저장할 때, 시스템은 ValidationResult.checklist_validation의 최상위 레벨에 포함해야 합니다

### 요구사항 10: 신뢰도 기반 재검증

**사용자 스토리:** A2 노드로서, 신뢰도가 낮은 검증 결과에 대해 표준 조항 컨텍스트를 추가하여 재검증함으로써 정확도를 향상시켜야 합니다. 이를 통해 불확실한 판단을 최소화할 수 있습니다.

#### 인수 기준

1. 1차 검증 완료 시, 시스템은 신뢰도 점수를 확인해야 합니다
2. 신뢰도가 0.7 미만일 때, 시스템은 재검증이 필요하다고 판단해야 합니다
3. 재검증을 수행할 때, 시스템은 지식베이스에서 표준 조항 텍스트를 로드해야 합니다
4. 표준 조항을 로드할 때, 시스템은 체크리스트 항목의 std_global_id를 사용하여 조회해야 합니다
5. 재검증 프롬프트를 구성할 때, 시스템은 사용자 조항, 표준 조항, 체크리스트 질문을 모두 포함해야 합니다
6. 재검증 프롬프트에서, 시스템은 "표준계약서를 참고하여 더 정확히 판단해주세요"라는 지시를 포함해야 합니다
7. 재검증 후에도 신뢰도가 0.7 미만일 때, 시스템은 결과를 "UNCLEAR"로 설정해야 합니다
8. UNCLEAR 결과를 저장할 때, 시스템은 requires_manual_review 필드를 True로 설정해야 합니다
9. 표준 조항 로드가 실패할 때, 시스템은 1차 검증 결과를 그대로 사용해야 합니다
10. 재검증 과정을 로깅할 때, 시스템은 1차 신뢰도, 재검증 신뢰도, 최종 결과를 기록해야 합니다

### 요구사항 11: 프론트엔드 결과 표시

**사용자 스토리:** 사용자로서, 체크리스트 검증 결과를 프론트엔드에서 확인할 수 있어야 합니다. 이를 통해 계약서가 표준 요구사항을 충족하는지 쉽게 파악할 수 있습니다.

#### 인수 기준

1. 검증 완료 후, 시스템은 "체크리스트 검증 결과 보기" 버튼을 표시해야 합니다
2. 버튼을 클릭할 때, 시스템은 체크리스트 검증 결과를 토글 방식으로 표시/숨김 처리해야 합니다
3. 체크리스트 결과를 표시할 때, 시스템은 전체 항목 수, 통과 항목 수, 미충족 항목 수를 상단에 표시해야 합니다
4. 체크리스트 결과를 표시할 때, 시스템은 사용자 조항별로 그룹핑하여 표시해야 합니다
5. 각 사용자 조항을 표시할 때, 시스템은 조항 번호와 제목을 헤더로 표시해야 합니다
6. 각 체크리스트 항목을 표시할 때, 시스템은 result가 "YES"이면 녹색 체크 아이콘과 함께 표시해야 합니다
7. 각 체크리스트 항목을 표시할 때, 시스템은 result가 "NO"이면 빨간색 X 아이콘과 함께 표시해야 합니다
8. 각 체크리스트 항목을 표시할 때, 시스템은 result가 "UNCLEAR"이면 노란색 물음표 아이콘과 함께 표시해야 합니다
9. 체크리스트 항목이 통과(YES)일 때, 시스템은 evidence를 작은 글씨로 표시해야 합니다
10. 체크리스트 항목이 미충족(NO)일 때, 시스템은 "해당 내용이 계약서에 명시되지 않았습니다" 메시지를 표시해야 합니다
11. 체크리스트 항목이 불명확(UNCLEAR)일 때, 시스템은 "판단이 불명확합니다. 수동 검토가 필요합니다" 메시지를 표시해야 합니다
12. UNCLEAR 항목을 표시할 때, 시스템은 신뢰도 점수를 함께 표시해야 합니다
13. 체크리스트 결과가 없을 때, 시스템은 "체크리스트 검증이 수행되지 않았습니다" 메시지를 표시해야 합니다
14. 체크리스트 결과 섹션은 A1 누락 조문 분석 결과 다음에 표시되어야 합니다

## 추가 고려사항

### 체크리스트 우선순위

**논의 필요 사항**:
- 모든 체크리스트 항목이 동일한 중요도를 가지는가?
- 필수 항목과 권장 항목을 구분할 필요가 있는가?
- 우선순위가 있다면 체크리스트 데이터에 priority 필드 추가 필요

### 신뢰도 임계값

**논의 필요 사항**:
- LLM 응답의 신뢰도가 낮을 때 (예: confidence < 0.7) 어떻게 처리할 것인가?
- 낮은 신뢰도 결과를 별도로 표시하거나 재검증할 필요가 있는가?

### 부분 매칭 처리

**논의 필요 사항**:
- 체크리스트 항목이 부분적으로만 충족된 경우 어떻게 표현할 것인가?
- YES/NO 외에 "PARTIAL" 또는 "UNCLEAR" 같은 상태가 필요한가?

### 사용자 피드백 통합

**논의 필요 사항**:
- 사용자가 A2 검증 결과에 동의하지 않을 경우 수정할 수 있는 메커니즘이 필요한가?
- 사용자 수정 사항을 어떻게 저장하고 추적할 것인가?
