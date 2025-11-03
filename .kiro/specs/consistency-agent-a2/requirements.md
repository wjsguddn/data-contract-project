# 요구사항 문서

## 소개

A2 노드(사용자 수동 확인 가이드)는 AI가 자동으로 검증할 수 없는 항목들을 식별하고, 사용자에게 직접 확인하도록 안내하는 역할을 합니다. 등기부등본 대조, 법적 권한 확인, 날인/서명 확인 등 외부 문서나 물리적 확인이 필요한 항목들을 체계적으로 제시하여, 사용자가 계약서 검증을 완료할 수 있도록 돕습니다.

**핵심 철학**: AI의 한계를 솔직하게 인정하고, 사람과 AI가 협력하여 계약서를 검증하는 구조를 만듭니다.

## 용어 정의

- **수동 확인 항목 (Manual Check Item)**: AI가 자동으로 검증할 수 없어 사용자가 직접 확인해야 하는 항목
- **확인 카테고리 (Check Category)**: 수동 확인 항목의 분류 (예: 당사자 정보, 법적 권한, 물리적 확인)
- **우선순위 (Priority)**: 확인 항목의 중요도 (high, medium, low)
- **사용자 액션 (User Action)**: 사용자가 수행해야 할 구체적인 확인 방법
- **ManualCheckLoader**: 수동 확인 항목 데이터를 로드하고 계약 유형별로 필터링하는 컴포넌트
- **ManualCheckNode**: A2 노드의 메인 클래스로, 수동 확인 항목을 생성하고 구조화하는 역할
- **확인 상태 (Check Status)**: manual_check_required (⚠️) - 사용자 확인 필요

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

### ValidationResult.manual_checks (A2 출력)

```json
{
    "total_manual_items": 12,
    "high_priority_items": 5,
    "medium_priority_items": 4,
    "low_priority_items": 3,
    "categories": [
        {
            "category": "당사자 정보",
            "description": "계약 당사자의 신원 및 권한 확인",
            "items": [
                {
                    "check_text": "당사자 정보가 등기부등본과 일치하는가?",
                    "user_action": "등기부등본과 대조하여 회사명, 주소, 대표자명 확인",
                    "priority": "high",
                    "reference": "제1조 또는 서문",
                    "why_manual": "등기부등본 등 외부 공적 문서 대조 필요"
                },
                {
                    "check_text": "대표자가 실제 계약 체결 권한을 보유하는가?",
                    "user_action": "대표이사 여부 확인, 필요시 위임장 또는 이사회 결의서 검토",
                    "priority": "high",
                    "reference": "제1조 또는 서문",
                    "why_manual": "법적 권한은 AI가 판단할 수 없음"
                }
            ]
        },
        {
            "category": "물리적 확인",
            "description": "문서의 물리적 요소 확인",
            "items": [
                {
                    "check_text": "날인 또는 서명이 되어 있는가?",
                    "user_action": "계약서 원본에 양 당사자의 날인 또는 서명 확인",
                    "priority": "high",
                    "reference": "계약서 말미",
                    "why_manual": "물리적 문서 확인 필요"
                }
            ]
        },
        {
            "category": "첨부 문서",
            "description": "계약서에 명시된 첨부 문서 확인",
            "items": [
                {
                    "check_text": "별지 및 첨부 문서가 모두 포함되어 있는가?",
                    "user_action": "계약서 본문에서 언급된 별지, 첨부 문서 목록 확인 및 실제 첨부 여부 대조",
                    "priority": "medium",
                    "reference": "계약서 전체",
                    "why_manual": "첨부 문서는 별도 파일로 제공되어 AI가 확인 불가"
                }
            ]
        }
    ],
    "processing_time": 0.5,
    "generation_date": "2025-01-01T00:00:00Z"
}
```

## 요구사항

### 요구사항 1: 계약 유형 기반 수동 확인 항목 로드

**사용자 스토리:** A2 노드로서, 계약 유형에 맞는 수동 확인 항목 템플릿을 로드하여 사용자에게 제공해야 합니다. 이를 통해 계약 유형별로 필요한 확인 사항을 체계적으로 안내할 수 있습니다.

#### 인수 기준

1. A2 노드가 시작될 때, 시스템은 ClassificationResult에서 confirmed_type을 조회해야 합니다
2. confirmed_type이 존재하지 않을 때, 시스템은 에러를 발생시키고 A2 노드 실행을 중단해야 합니다
3. 계약 유형을 확인할 때, 시스템은 유효한 유형인지 검증해야 합니다 (provide, create, process, brokerage_provider, brokerage_user)
4. 수동 확인 항목을 로드할 때, 시스템은 해당 계약 유형의 템플릿 JSON 파일을 읽어야 합니다
5. 템플릿 파일이 없을 때, 시스템은 기본 공통 항목을 사용해야 합니다
6. 로드된 항목을 처리할 때, 시스템은 카테고리별로 그룹핑해야 합니다

### 요구사항 2: 우선순위 기반 항목 분류

**사용자 스토리:** 사용자로서, 수동 확인 항목의 중요도를 파악하여 우선순위에 따라 확인할 수 있어야 합니다. 이를 통해 핵심 항목을 먼저 확인하고 효율적으로 검증을 진행할 수 있습니다.

#### 인수 기준

1. 수동 확인 항목을 로드할 때, 시스템은 각 항목의 priority 필드를 확인해야 합니다
2. priority 값을 검증할 때, 시스템은 "high", "medium", "low" 중 하나인지 확인해야 합니다
3. 항목을 분류할 때, 시스템은 우선순위별로 카운트해야 합니다
4. 결과를 저장할 때, 시스템은 high_priority_items, medium_priority_items, low_priority_items 통계를 포함해야 합니다
5. 프론트엔드 표시를 위해, 시스템은 high 항목을 먼저 정렬해야 합니다
6. priority 필드가 없는 항목은 기본값 "medium"으로 처리해야 합니다

### 요구사항 3: 카테고리별 항목 구조화

**사용자 스토리:** 사용자로서, 수동 확인 항목이 카테고리별로 정리되어 있어야 체계적으로 확인할 수 있습니다. 이를 통해 관련된 항목들을 함께 확인하고 누락을 방지할 수 있습니다.

#### 인수 기준

1. 수동 확인 항목을 구조화할 때, 시스템은 category 필드를 기준으로 그룹핑해야 합니다
2. 각 카테고리를 저장할 때, 시스템은 category, description, items를 포함해야 합니다
3. 카테고리 순서를 정할 때, 시스템은 다음 순서를 따라야 합니다: 당사자 정보 → 물리적 확인 → 첨부 문서 → 기타
4. 각 항목을 저장할 때, 시스템은 check_text, user_action, priority, reference, why_manual을 포함해야 합니다
5. why_manual 필드는 왜 AI가 자동 검증할 수 없는지 명확히 설명해야 합니다
6. user_action 필드는 사용자가 구체적으로 무엇을 확인해야 하는지 명시해야 합니다

### 요구사항 4: Preamble 통합 처리

**사용자 스토리:** A2 노드로서, 사용자 계약서의 preamble(서문)에 있는 당사자 정보를 인식하고 관련 수동 확인 항목을 생성해야 합니다. 이를 통해 제1조 이전에 명시된 당사자 정보도 검증 대상에 포함할 수 있습니다.

#### 인수 기준

1. 사용자 계약서를 로드할 때, 시스템은 parsed_data에서 preamble 필드를 확인해야 합니다
2. preamble이 존재하고 비어있지 않을 때, 시스템은 당사자 정보가 포함되어 있다고 판단해야 합니다
3. 당사자 정보 확인 항목을 생성할 때, 시스템은 reference 필드에 "서문 또는 제1조"로 명시해야 합니다
4. preamble이 비어있을 때, 시스템은 제1조만 참조하도록 reference를 설정해야 합니다
5. 사용자에게 안내할 때, 시스템은 "당사자 정보는 서문 또는 제1조에서 확인하세요"라고 명시해야 합니다
6. preamble 존재 여부와 관계없이 동일한 확인 항목을 제공해야 합니다

### 요구사항 5: 수동 확인 결과 저장

**사용자 스토리:** 개발자로서, 수동 확인 항목을 ValidationResult에 저장하여 프론트엔드와 보고서 생성에서 활용할 수 있어야 합니다.

#### 인수 기준

1. A2 노드가 완료될 때, 시스템은 ValidationResult.manual_checks에 수동 확인 항목을 저장해야 합니다
2. 저장할 때, 시스템은 total_manual_items, high_priority_items, medium_priority_items, low_priority_items 통계를 포함해야 합니다
3. 저장할 때, 시스템은 categories 배열에 카테고리별 항목을 포함해야 합니다
4. 각 카테고리를 저장할 때, 시스템은 category, description, items를 포함해야 합니다
5. 각 항목을 저장할 때, 시스템은 check_text, user_action, priority, reference, why_manual을 포함해야 합니다
6. 저장할 때, 시스템은 processing_time과 generation_date를 포함해야 합니다
7. ValidationResult를 저장할 때, 시스템은 DB에 변경사항을 커밋해야 합니다

### 요구사항 6: 에러 처리 및 로깅

**사용자 스토리:** 시스템 관리자로서, 수동 확인 항목 생성 중 발생하는 에러를 적절히 처리하고 로깅하여 문제를 추적할 수 있어야 합니다.

#### 인수 기준

1. 계약 유형이 확정되지 않았을 때, 시스템은 명확한 에러 메시지와 함께 예외를 발생시켜야 합니다
2. 템플릿 파일을 로드할 수 없을 때, 시스템은 경고를 로깅하고 기본 공통 항목을 사용해야 합니다
3. A2 노드 시작 시, 시스템은 계약 유형과 로드할 템플릿을 로깅해야 합니다
4. 항목 생성 완료 시, 시스템은 총 항목 수와 우선순위별 분포를 로깅해야 합니다
5. A2 노드 완료 시, 시스템은 총 처리 시간을 로깅해야 합니다
6. DB 저장 실패 시, 시스템은 에러를 로깅하고 예외를 발생시켜야 합니다

### 요구사항 7: 프론트엔드 결과 표시

**사용자 스토리:** 사용자로서, 수동 확인 항목을 프론트엔드에서 확인하고 체크할 수 있어야 합니다. 이를 통해 AI가 검증할 수 없는 항목들을 체계적으로 확인할 수 있습니다.

#### 인수 기준

1. 검증 완료 후, 시스템은 "⚠️ 사용자 확인 필요 항목" 섹션을 표시해야 합니다
2. 섹션 상단에, 시스템은 전체 항목 수와 우선순위별 분포를 표시해야 합니다
3. 항목을 표시할 때, 시스템은 카테고리별로 그룹핑하여 표시해야 합니다
4. 각 카테고리를 표시할 때, 시스템은 카테고리명과 설명을 헤더로 표시해야 합니다
5. 각 항목을 표시할 때, 시스템은 ⚠️ 아이콘과 함께 check_text를 표시해야 합니다
6. 각 항목을 표시할 때, 시스템은 체크박스를 제공하여 사용자가 확인 완료를 표시할 수 있어야 합니다
7. 각 항목 아래에, 시스템은 user_action을 작은 글씨로 표시해야 합니다
8. 각 항목 아래에, 시스템은 reference를 표시하여 어디를 확인해야 하는지 안내해야 합니다
9. high priority 항목은 빨간색 테두리로 강조 표시해야 합니다
10. 모든 항목을 확인(체크)했을 때, 시스템은 "모든 항목 확인 완료" 메시지를 표시해야 합니다
11. 수동 확인 섹션은 A1 누락 조문 분석 결과 다음에 표시되어야 합니다
12. 각 항목에 마우스를 올리면, 시스템은 why_manual 내용을 툴팁으로 표시해야 합니다

## 추가 고려사항

### 템플릿 확장성

**논의 필요 사항**:
- 새로운 계약 유형이 추가될 때 템플릿을 쉽게 추가할 수 있는가?
- 공통 항목과 계약 유형별 특화 항목을 어떻게 관리할 것인가?
- 템플릿 버전 관리가 필요한가?

### 사용자 확인 상태 저장

**논의 필요 사항**:
- 사용자가 체크박스를 클릭한 상태를 DB에 저장할 것인가?
- 저장한다면 어떤 테이블/필드에 저장할 것인가?
- 사용자가 나중에 다시 확인할 수 있도록 상태를 유지할 것인가?

### 항목 커스터마이징

**논의 필요 사항**:
- 사용자가 수동 확인 항목을 추가/삭제/수정할 수 있어야 하는가?
- 조직별로 커스텀 체크리스트를 만들 수 있어야 하는가?

### 외부 시스템 연동 (Phase 3)

**미래 고려사항**:
- 등기부등본 API 연동으로 자동 대조 가능
- 전자서명 시스템 연동으로 서명 확인 자동화
- 이 경우 수동 확인 항목이 자동 검증 항목으로 전환 가능
