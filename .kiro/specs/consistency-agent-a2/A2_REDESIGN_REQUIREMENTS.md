# A2 노드 재설계 요구사항

## 개요

A2 노드를 **표준 조항 기준**으로 재구성하여 체크리스트 검증 결과를 명확하고 리포트 작성에 용이하게 만듭니다.

---

## 핵심 변경사항

### 기존 방식 (사용자 조항 기준)
```
사용자 제7조 → 표준 제3조 체크리스트 검증 (일부만 충족)
사용자 제8조 → 표준 제3조 체크리스트 검증 (나머지 충족)
```
- 문제: 같은 체크리스트를 여러 번 검증, 결과가 분산됨

### 새로운 방식 (표준 조항 기준)
```
표준 제3조 체크리스트 → 사용자 제7조 + 제8조 텍스트로 한 번에 검증
```
- 장점: 중복 제거, 명확한 매핑, 리포트 작성 용이

---

## 요구사항

### 1. 입력 데이터

#### A1 매칭 결과
- `matching_details`: 사용자 조항별 매칭 정보
  - `user_article_no`, `user_article_id`, `user_article_title`
  - `matched_articles_global_ids`: 매칭된 표준 조항 global_id 리스트

#### 사용자 계약서
- `contract_id`: 계약서 ID
- `parsed_data.articles`: 사용자 조항 텍스트

#### 체크리스트
- 표준 조항별 체크리스트 항목
- `global_id`, `check_text`, `reference`

### 2. 처리 로직

#### 2.1 매핑 생성
A1 결과를 재조립하여 **표준 조항 → 사용자 조항** 매핑 생성

```python
std_to_user_map = {
    "urn:std:provide:art:003": [
        {
            "user_article_no": 7,
            "user_article_id": "user_article_007",
            "user_article_title": "제공 목적 및 범위"
        },
        {
            "user_article_no": 8,
            "user_article_id": "user_article_008",
            "user_article_title": "목적 외 사용 금지"
        }
    ]
}
```

#### 2.2 표준 조항별 검증
각 표준 조항에 대해:
1. 매칭된 사용자 조항들의 텍스트를 **합침**
2. 해당 표준 조항의 체크리스트 항목들을 **일괄 검증**
3. 각 체크리스트 항목이 **어느 사용자 조항에서 발견**되었는지 기록

#### 2.3 미매칭 표준 조항 처리
A1에서 매칭되지 않은 표준 조항:
1. 해당 조항의 체크리스트를 **검증하지 않음**
2. 별도 섹션에 **누락 조항**으로 표시
3. **위험도 평가** 포함

### 3. 출력 데이터

#### 3.1 표준 조항별 검증 결과

```json
{
  "std_article_results": [
    {
      "std_article_id": "urn:std:provide:art:001",
      "std_article_title": "목적",
      "std_article_number": "제1조",
      "matched_user_articles": [
        {
          "user_article_no": 1,
          "user_article_id": "user_article_001",
          "user_article_title": "목적"
        }
      ],
      "checklist_results": [
        {
          "check_text": "계약 당사자가 명확히 기재되어 있는가?",
          "reference": "제1조",
          "std_global_id": "urn:std:provide:art:001",
          "result": "YES",
          "evidence": "제1조에 '갑(제공자)과 을(수령자)'로 명확히 기재됨",
          "confidence": 0.95,
          "found_in_user_articles": [
            {
              "user_article_no": 1,
              "user_article_id": "user_article_001",
              "user_article_title": "목적"
            }
          ]
        },
        {
          "check_text": "등기부등본에 표시된 것 그대로 기재되어 있는가?",
          "reference": "제1조",
          "std_global_id": "urn:std:provide:art:001",
          "result": "MANUAL_CHECK_REQUIRED",
          "evidence": "제1조에 '주식회사 ABC, 서울시 강남구...' 기재됨",
          "confidence": 0.9,
          "found_in_user_articles": [
            {
              "user_article_no": 1,
              "user_article_id": "user_article_001",
              "user_article_title": "목적"
            }
          ],
          "manual_check_reason": "등기부등본과의 대조 필요",
          "user_action": "등기부등본을 확인하여 계약서의 회사명, 주소가 일치하는지 확인하세요"
        },
        {
          "check_text": "계약 당사자의 서명이 있는가?",
          "reference": "제1조",
          "std_global_id": "urn:std:provide:art:001",
          "result": "MANUAL_CHECK_REQUIRED",
          "evidence": null,
          "confidence": 0.9,
          "found_in_user_articles": [],
          "manual_check_reason": "서명은 문서 이미지에서만 확인 가능",
          "user_action": "계약서 원본에서 서명란을 확인하세요"
        }
      ],
      "statistics": {
        "total_items": 3,
        "passed_items": 1,
        "failed_items": 0,
        "unclear_items": 0,
        "manual_check_items": 2,
        "pass_rate": 0.33
      }
    },
    {
      "std_article_id": "urn:std:provide:art:003",
      "std_article_title": "개인정보의 제공 목적",
      "std_article_number": "제3조",
      "matched_user_articles": [
        {
          "user_article_no": 7,
          "user_article_id": "user_article_007",
          "user_article_title": "제공 목적 및 범위"
        },
        {
          "user_article_no": 8,
          "user_article_id": "user_article_008",
          "user_article_title": "목적 외 사용 금지"
        }
      ],
      "checklist_results": [
        {
          "check_text": "개인정보 제공 목적이 구체적으로 명시되어 있는가?",
          "reference": "제3조",
          "std_global_id": "urn:std:provide:art:003",
          "result": "YES",
          "evidence": "제7조에 '마케팅 활용'이라는 구체적 목적 명시",
          "confidence": 0.95,
          "found_in_user_articles": [
            {
              "user_article_no": 7,
              "user_article_id": "user_article_007",
              "user_article_title": "제공 목적 및 범위"
            }
          ]
        },
        {
          "check_text": "목적 외 사용 금지 조항이 포함되어 있는가?",
          "reference": "제3조",
          "std_global_id": "urn:std:provide:art:003",
          "result": "YES",
          "evidence": "제8조에 목적 외 사용 금지 명시",
          "confidence": 0.92,
          "found_in_user_articles": [
            {
              "user_article_no": 8,
              "user_article_id": "user_article_008",
              "user_article_title": "목적 외 사용 금지"
            }
          ]
        },
        {
          "check_text": "개인정보 보호법 준수 명시가 있는가?",
          "reference": "제3조",
          "std_global_id": "urn:std:provide:art:003",
          "result": "NO",
          "evidence": null,
          "confidence": 0.9,
          "found_in_user_articles": [],
          "missing_explanation": "개인정보 보호법 준수 관련 문구가 전혀 없음",
          "risk_level": "high",
          "risk_description": "개인정보 보호법 위반 시 과태료 부과 가능",
          "recommendation": "제3조에 '개인정보 보호법을 준수한다' 문구 추가"
        },
        {
          "check_text": "제3자 제공 시 동의 절차가 명시되어 있는가?",
          "reference": "제3조",
          "std_global_id": "urn:std:provide:art:003",
          "result": "UNCLEAR",
          "evidence": "제7조와 제8조에 간접적으로 언급",
          "confidence": 0.6,
          "found_in_user_articles": [
            {
              "user_article_no": 7,
              "user_article_id": "user_article_007",
              "user_article_title": "제공 목적 및 범위"
            },
            {
              "user_article_no": 8,
              "user_article_id": "user_article_008",
              "user_article_title": "목적 외 사용 금지"
            }
          ]
        }
      ],
      "statistics": {
        "total_items": 4,
        "passed_items": 2,
        "failed_items": 1,
        "unclear_items": 1,
        "manual_check_items": 0,
        "pass_rate": 0.50
      }
    }
  ]
}
```

**필드 설명**:

- `std_article_id`: 표준 조항 global_id (예: "urn:std:provide:art:003")
- `std_article_title`: 표준 조항 제목 (예: "개인정보의 제공 목적")
- `std_article_number`: 표준 조항 번호 (예: "제3조")
- `matched_user_articles`: 이 표준 조항과 매칭된 사용자 조항 리스트
  - `user_article_no`: 사용자 조항 번호 (정수)
  - `user_article_id`: 사용자 조항 ID (예: "user_article_007")
  - `user_article_title`: 사용자 조항 제목
- `checklist_results`: 체크리스트 검증 결과 리스트
  - `check_text`: 체크리스트 질문
  - `reference`: 참조 조항 (예: "제3조")
  - `std_global_id`: 표준 조항 global_id
  - `result`: 검증 결과 ("YES" | "NO" | "UNCLEAR" | "MANUAL_CHECK_REQUIRED")
  - `evidence`: 판단 근거 텍스트 (YES/UNCLEAR인 경우, NO/MANUAL_CHECK_REQUIRED는 null 가능)
  - `confidence`: LLM 신뢰도 (0.0 ~ 1.0)
  - `found_in_user_articles`: **이 항목이 발견된 사용자 조항 전체 정보 리스트**
    - 리포트 작성 시 `user_article_id`로 조회 가능
    - 빈 리스트 `[]`: 발견되지 않음 (result="NO" 또는 내용 없는 "MANUAL_CHECK_REQUIRED")
    - 여러 조항: 여러 조항에서 발견됨 (예: result="UNCLEAR", 간접적 언급)
  - **result="NO"인 경우 추가 필드** (현재 ChecklistVerifier 구현됨):
    - `missing_explanation`: 어떤 내용이 없는지 구체적 설명
    - `risk_level`: "high" | "medium" | "low"
    - `risk_description`: 누락 시 법적/실무적 위험
    - `recommendation`: 개선 권장사항
  - **result="MANUAL_CHECK_REQUIRED"인 경우 추가 필드** (현재 ChecklistVerifier 구현됨):
    - `manual_check_reason`: 수동 확인이 필요한 이유
    - `user_action`: 사용자가 취해야 할 구체적 조치
- `statistics`: 해당 표준 조항의 체크리스트 통계
  - `total_items`: 전체 체크리스트 항목 수
  - `passed_items`: 통과 항목 수 (YES)
  - `failed_items`: 실패 항목 수 (NO)
  - `unclear_items`: 불명확 항목 수 (UNCLEAR)
  - `manual_check_items`: 수동 확인 필요 항목 수 (MANUAL_CHECK_REQUIRED)
  - `pass_rate`: 통과율 (passed / total)

#### 3.2 미매칭 표준 조항 (누락 조항)

A1에서 매칭되지 않은 표준 조항의 체크리스트 정보

```json
{
  "unmatched_std_articles": [
    {
      "std_article_id": "urn:std:provide:art:005",
      "std_article_title": "개인정보의 보유 및 이용 기간",
      "std_article_number": "제5조",
      "checklist_items": [
        {
          "check_text": "개인정보 보유 기간이 명시되어 있는가?",
          "reference": "제5조"
        },
        {
          "check_text": "보유 기간 경과 후 파기 절차가 명시되어 있는가?",
          "reference": "제5조"
        }
      ],
      "risk_assessment": {
        "severity": "high",
        "description": "필수 조항 누락으로 개인정보 보호법 위반 가능성",
        "recommendation": "제5조 '개인정보의 보유 및 이용 기간' 조항 추가 필요",
        "legal_risk": "개인정보 보호법 제21조 위반 시 과태료 부과 가능"
      }
    }
  ]
}
```

#### 3.3 전체 통계

```json
{
  "statistics": {
    "total_std_articles": 10,
    "matched_std_articles": 8,
    "unmatched_std_articles": 2,
    "total_checklist_items": 45,
    "passed_items": 35,
    "failed_items": 10,
    "overall_pass_rate": 0.78,
    "high_risk_items": 3,
    "medium_risk_items": 5,
    "low_risk_items": 2
  }
}
```

---

## 상세 요구사항

### 4. 위험도 평가

#### 4.1 미매칭 표준 조항 위험도

**result 값 판단 기준** (현재 ChecklistVerifier 구현 기준):

- `"YES"`: 명확히 충족
  - 해당 내용이 명시적으로 기재되어 있음
  - 법적 요구사항을 충분히 만족함
  - `evidence`: 핵심 문구 인용
  - `found_in_user_articles`: 1개 이상

- `"NO"`: 명확히 미충족
  - **해당 내용 자체가 계약서에 없음**
  - 법적 요구사항을 충족하지 못함
  - `evidence`: null
  - `found_in_user_articles`: 빈 리스트 `[]`
  - **추가 정보** (현재 구현됨):
    - `missing_explanation`: 어떤 내용이 없는지 구체적 설명
    - `risk_level`: "high" | "medium" | "low"
    - `risk_description`: 누락 시 법적/실무적 위험
    - `recommendation`: 개선 권장사항

- `"MANUAL_CHECK_REQUIRED"`: 수동 확인 필요 (현재 구현됨)
  - **계약서에 내용은 있으나 외부 확인이 필요함**
  - AI가 판단할 수 없는 항목 (등기부등본 대조, 서명 확인 등)
  - `evidence`: null 또는 계약서의 해당 부분
  - `found_in_user_articles`: 내용이 있는 조항 (있는 경우)
  - **추가 정보** (현재 구현됨):
    - `manual_check_reason`: 수동 확인이 필요한 이유
    - `user_action`: 사용자가 취해야 할 구체적 조치

- `"UNCLEAR"`: 불명확 (신뢰도 낮음)
  - 간접적으로 언급되거나 애매함
  - 해석의 여지가 있음
  - `evidence`: 간접적 언급 부분 인용
  - `found_in_user_articles`: 1개 이상 (간접적 언급 조항)

**MANUAL_CHECK_REQUIRED 판단 기준** (ChecklistVerifier 프롬프트 기준):

다음 조건을 **모두** 만족해야 MANUAL_CHECK_REQUIRED:
1. **계약서에 해당 내용이 이미 기재되어 있어야 함**
2. **그 내용이 정확한지 외부 문서/정보와 대조가 필요함**

**구체적 예시**:

✅ **MANUAL_CHECK_REQUIRED** (내용 있음 + 외부 확인 필요):
- 계약서: "갑: 주식회사 ABC, 서울시 강남구..." 
  - 질문: "등기부등본과 일치하는가?" 
  - → MANUAL_CHECK_REQUIRED (내용은 있으나 등기부등본 대조 필요)

- 계약서: "대표이사 홍길동"
  - 질문: "적법한 권한을 가진 대표자인가?"
  - → MANUAL_CHECK_REQUIRED (내용은 있으나 법적 권한 확인 필요)

- 계약서: "날인란: [   ]"
  - 질문: "날인이 되어 있는가?"
  - → MANUAL_CHECK_REQUIRED (날인란은 있으나 실제 날인 여부는 물리적 확인 필요)

❌ **NO** (내용 자체가 없음):
- 계약서: 당사자 정보 없음
  - 질문: "당사자가 개인인가 법인인가?"
  - → NO (당사자 정보 자체가 없으므로 추가 필요)

- 계약서: 대표자 이름 없음
  - 질문: "대표자 성명이 기재되어 있는가?"
  - → NO (대표자 정보 자체가 없으므로 추가 필요)

**핵심 원칙**: 
- 내용이 **없으면** → NO (추가 필요)
- 내용이 **있는데 확인이 필요하면** → MANUAL_CHECK_REQUIRED (외부 확인 필요)

**found_in_user_articles 규칙**:

- 빈 리스트 `[]`: 발견되지 않음 (result="NO" 또는 "MANUAL_CHECK_REQUIRED"이지만 내용 없음)
- 1개 조항: 해당 조항에서만 발견
- 여러 조항: 여러 조항에 걸쳐 발견 (예: 제7조에 일부, 제8조에 일부)

**예시**:

```json
// 예시 1: 명확히 충족 (1개 조항)
{
  "check_text": "개인정보 제공 목적이 구체적으로 명시되어 있는가?",
  "reference": "제3조",
  "result": "YES",
  "evidence": "제7조에 '마케팅 활용 및 서비스 개선'이라는 구체적 목적 명시",
  "confidence": 0.95,
  "found_in_user_articles": [
    {"user_article_no": 7, "user_article_id": "user_article_007", ...}
  ]
}

// 예시 2: 명확히 미충족 (내용 없음)
{
  "check_text": "개인정보 보호법 준수 명시가 있는가?",
  "reference": "제3조",
  "result": "NO",
  "evidence": null,
  "confidence": 0.9,
  "found_in_user_articles": [],
  "missing_explanation": "개인정보 보호법 준수 관련 문구가 전혀 없음",
  "risk_level": "high",
  "risk_description": "개인정보 보호법 위반 시 과태료 부과 가능",
  "recommendation": "제3조에 '개인정보 보호법을 준수한다' 문구 추가"
}

// 예시 3: 수동 확인 필요 (내용 있음 + 외부 확인)
{
  "check_text": "등기부등본에 표시된 것 그대로 기재되어 있는가?",
  "reference": "제1조",
  "result": "MANUAL_CHECK_REQUIRED",
  "evidence": "제1조에 '주식회사 ABC, 서울시 강남구...' 기재됨",
  "confidence": 0.9,
  "found_in_user_articles": [
    {"user_article_no": 1, "user_article_id": "user_article_001", ...}
  ],
  "manual_check_reason": "등기부등본과의 대조 필요",
  "user_action": "등기부등본을 확인하여 계약서의 회사명, 주소가 일치하는지 확인하세요"
}

// 예시 4: 불명확 (여러 조항에 간접적 언급)
{
  "check_text": "제3자 제공 시 동의 절차가 명시되어 있는가?",
  "reference": "제3조",
  "result": "UNCLEAR",
  "evidence": "제7조에 '제3자 제공 가능'이라는 언급만 있고, 제8조에 '동의 필요'라는 간접적 언급",
  "confidence": 0.6,
  "found_in_user_articles": [
    {"user_article_no": 7, ...},
    {"user_article_no": 8, ...}
  ]
}
```

#### 4.2 체크리스트 항목 실패 위험도

표준 조항이 사용자 계약서에 없을 때의 위험도:

**평가 기준**:
1. **필수 조항 여부**: 법적 필수 조항인가?
2. **법적 리스크**: 위반 시 과태료/벌금 가능성
3. **계약 유효성**: 계약 무효 가능성

**위험도 등급**:
- `high`: 필수 조항 누락, 법적 리스크 높음
- `medium`: 권장 조항 누락, 법적 리스크 중간
- `low`: 선택 조항 누락, 법적 리스크 낮음

**위험도 판단 로직**:
```python
def assess_risk(std_article_id: str, checklist_items: List[Dict]) -> Dict:
    """
    표준 조항 누락 시 위험도 평가
    
    Args:
        std_article_id: 표준 조항 global_id
        checklist_items: 해당 조항의 체크리스트 항목들
    
    Returns:
        {
            "severity": "high" | "medium" | "low",
            "description": str,
            "recommendation": str,
            "legal_risk": str
        }
    """
    # 1. 필수 조항 판단 (하드코딩 또는 메타데이터)
    critical_articles = [
        "urn:std:provide:art:001",  # 목적
        "urn:std:provide:art:003",  # 제공 목적
        "urn:std:provide:art:005",  # 보유 기간
        # ...
    ]
    
    if std_article_id in critical_articles:
        severity = "high"
    elif len(checklist_items) >= 5:  # 체크리스트 많으면 중요
        severity = "medium"
    else:
        severity = "low"
    
    # 2. 설명 생성 (LLM 또는 템플릿)
    description = f"필수 조항 누락으로 개인정보 보호법 위반 가능성"
    recommendation = f"{std_article_id} 조항 추가 필요"
    legal_risk = "개인정보 보호법 제21조 위반 시 과태료 부과 가능"
    
    return {
        "severity": severity,
        "description": description,
        "recommendation": recommendation,
        "legal_risk": legal_risk
    }
```

---

## 구현 우선순위

### Phase 1: 기본 구조 (필수)
1. 표준 조항 → 사용자 조항 매핑 생성
2. 표준 조항별 체크리스트 검증
3. `std_article_results` 출력

### Phase 2: 상세 정보 (필수)
1. `found_in_user_articles` 추출
2. `reasoning` 생성
3. 통계 계산

### Phase 3: 위험도 평가 (중요)
1. 미매칭 표준 조항 식별
2. 위험도 평가 로직
3. `unmatched_std_articles` 출력

### Phase 4: 최적화 (선택)
1. LLM 프롬프트 최적화
2. 배치 처리 성능 개선
3. 캐싱 전략

---

## 예상 출력 전체 구조

```json
{
  "contract_id": "contract_20240101_001",
  "contract_type": "provide",
  "std_article_results": [
    {
      "std_article_id": "urn:std:provide:art:003",
      "std_article_title": "개인정보의 제공 목적",
      "std_article_number": "제3조",
      "matched_user_articles": [
        {
          "user_article_no": 7,
          "user_article_id": "user_article_007",
          "user_article_title": "제공 목적 및 범위"
        },
        {
          "user_article_no": 8,
          "user_article_id": "user_article_008",
          "user_article_title": "목적 외 사용 금지"
        }
      ],
      "checklist_results": [
        {
          "check_text": "개인정보 제공 목적이 구체적으로 명시되어 있는가?",
          "reference": "제3조",
          "result": "YES",
          "evidence": "제7조에 '마케팅 활용'이라는 구체적 목적 명시",
          "found_in_user_articles": [
            {
              "user_article_no": 7,
              "user_article_id": "user_article_007",
              "user_article_title": "제공 목적 및 범위"
            }
          ],
          "reasoning": "사용자 제7조에서 명확히 확인됨"
        },
        {
          "check_text": "목적 외 사용 금지 조항이 포함되어 있는가?",
          "reference": "제3조",
          "result": "YES",
          "evidence": "제8조에 목적 외 사용 금지 명시",
          "found_in_user_articles": [
            {
              "user_article_no": 8,
              "user_article_id": "user_article_008",
              "user_article_title": "목적 외 사용 금지"
            }
          ],
          "reasoning": "사용자 제8조에서 명확히 확인됨"
        },
        {
          "check_text": "개인정보 보호법 준수 명시가 있는가?",
          "reference": "제3조",
          "result": "NO",
          "evidence": null,
          "found_in_user_articles": [],
          "reasoning": "제7조, 제8조 모두에서 관련 내용 없음"
        }
      ],
      "statistics": {
        "total_items": 3,
        "passed_items": 2,
        "failed_items": 1,
        "unclear_items": 0,
        "pass_rate": 0.67
      }
    }
  ],
  "unmatched_std_articles": [
    {
      "std_article_id": "urn:std:provide:art:005",
      "std_article_title": "개인정보의 보유 및 이용 기간",
      "std_article_number": "제5조",
      "checklist_items": [
        {
          "check_text": "개인정보 보유 기간이 명시되어 있는가?",
          "reference": "제5조"
        },
        {
          "check_text": "보유 기간 경과 후 파기 절차가 명시되어 있는가?",
          "reference": "제5조"
        }
      ],
      "risk_assessment": {
        "severity": "high",
        "description": "필수 조항 누락으로 개인정보 보호법 위반 가능성",
        "recommendation": "제5조 '개인정보의 보유 및 이용 기간' 조항 추가 필요",
        "legal_risk": "개인정보 보호법 제21조 위반 시 과태료 부과 가능"
      }
    }
  ],
  "statistics": {
    "total_std_articles": 10,
    "matched_std_articles": 8,
    "unmatched_std_articles": 2,
    "total_checklist_items": 45,
    "passed_items": 35,
    "failed_items": 8,
    "unclear_items": 2,
    "manual_check_items": 5,
    "overall_pass_rate": 0.78,
    "high_risk_unmatched": 1,
    "medium_risk_unmatched": 1,
    "low_risk_unmatched": 0
  },
  "processing_time": 45.2,
  "verification_date": "2024-01-01T12:00:00"
}
```

**전체 구조 설명**:

1. **std_article_results**: 매칭된 표준 조항별 검증 결과
   - 각 표준 조항마다 매칭된 사용자 조항들과 체크리스트 결과 포함
   - `found_in_user_articles`에 전체 조항 정보 포함 (리포트 작성용)

2. **unmatched_std_articles**: A1에서 매칭되지 않은 표준 조항
   - 체크리스트 항목 리스트 (검증은 하지 않음)
   - 위험도 평가 포함

3. **statistics**: 전체 통계
   - 표준 조항 매칭 통계
   - 체크리스트 통과율
   - 수동 확인 필요 항목 수 (`manual_check_items`)
   - 위험도별 미매칭 조항 수

---

## 고려사항

### 1. Preamble 제외
- **현재 설계에서는 preamble 체크리스트 검증 제외**
- 이유:
  - Preamble은 계약서마다 형식이 천차만별
  - 핵심 내용은 제1조에 다시 나오는 경우가 많음
  - 표준 조항 기준 구조에서 preamble 처리가 복잡함
- 나중에 필요하면 별도 섹션으로 추가 가능

### 2. 멀티매칭 처리
- **하나의 사용자 조항이 여러 표준 조항과 매칭 가능**
- 예: 사용자 제7조 → 표준 제3조, 제4조 모두와 매칭
- 각 표준 조항별로 독립적으로 검증
- 중복 검증 가능하지만 문제없음 (다른 체크리스트)
- 리포트에서 "사용자 제7조가 여러 표준 조항을 충족"으로 표현 가능

### 3. 하위항목별 매칭
- A1의 `sub_item_results` 활용 가능
- 하위항목별로 다른 표준 조항과 매칭된 경우
- **현재는 조 단위로만 처리**, 나중에 확장 가능
- 확장 시: 체크리스트 항목별로 어느 하위항목에서 발견되었는지 추적

### 4. LLM 토큰 사용량
- **여러 사용자 조항을 합치면 토큰 증가**
- 권장: 최대 3~4개 조항까지만 합치기
- 대응 방안:
  - 조항 수가 많으면 배치 처리 (여러 번 LLM 호출)
  - 또는 조항 텍스트 요약 후 검증
- 토큰 사용량 모니터링 및 로깅 필수

### 5. 프론트엔드 호환성
- **기존 프론트는 사용자 조항 기준**으로 표시 중
- 새로운 출력 구조는 **표준 조항 기준**
- 대응 방안:
  - 프론트엔드를 표준 조항 기준으로 수정 (권장)
  - 또는 백엔드에서 변환 레이어 추가 (사용자 조항 기준으로 재조립)
- `found_in_user_articles`에 전체 정보가 있어 역매핑 가능

### 6. found_in_user_articles의 중요성
- **리포트 작성의 핵심 데이터**
- 활용:
  - "이 체크리스트 항목은 사용자 계약서 어디에 있는가?"
  - "사용자 제7조가 어떤 체크리스트를 충족했는가?" (역매핑)
  - 하이퍼링크: `user_article_id`로 해당 조항으로 이동
- 반드시 전체 정보 포함 (no, id, title)

---

## 다음 단계

1. **요구사항 검토**: 이 문서 리뷰 및 피드백
2. **LLM 프롬프트 설계**: `found_in_user_articles` 추출 프롬프트
3. **위험도 평가 로직**: 필수 조항 리스트 정의
4. **구현 시작**: Phase 1부터 순차적으로
