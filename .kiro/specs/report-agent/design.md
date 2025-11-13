# Design Document: Report Agent

## Overview

Report Agent는 A1, A2, A3 노드의 검증 결과를 통합하고 정합성을 보정하여 최종 분석 보고서를 생성하는 시스템입니다. 표준 항목 단위로 여러 사용자 조항에서 발생한 상충된 평가를 우선순위 규칙과 LLM 재검증으로 통합하여, 실제 문제(누락, 불충분)만 포함하는 깔끔한 보고서를 생성합니다.

## Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Report Agent                            │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐    │
│  │   Step 1     │   │   Step 2     │   │   Step 3     │    │
│  │ Normalizer   │──▶│ Aggregator   │──▶│  Resolver    │    │
│  │ (사용자 조항) │   │ (표준 항목)   │   │ (충돌 해소)   │    │
│  └──────────────┘   └──────────────┘   └──────────────┘    │
│         │                                      │             │
│         ▼                                      ▼             │
│  ┌──────────────┐                      ┌──────────────┐    │
│  │  A1 Parser   │                      │ LLM Verifier │    │
│  │  A3 Parser   │                      │              │    │
│  └──────────────┘                      └──────────────┘    │
│                                                │             │
│                                                ▼             │
│                                         ┌──────────────┐    │
│                                         │   Step 4     │    │
│                                         │   Reporter   │    │
│                                         │ (최종 보고서) │    │
│                                         └──────────────┘    │
│                                                              │
└─────────────────────────────────────────────────────────────┘
         │                                         │
         ▼                                         ▼
┌─────────────────┐                       ┌─────────────────┐
│  ValidationResult│                       │   Frontend      │
│  (DB 저장)       │                       │  (리포트 페이지) │
└─────────────────┘                       └─────────────────┘
```

### Component Diagram

```
┌────────────────────────────────────────────────────────────┐
│                    ReportAgent (Main)                       │
├────────────────────────────────────────────────────────────┤
│  + generate_report(contract_id)                            │
│  - _load_input_data()                                      │
│  - _save_to_db()                                           │
└────────────────────────────────────────────────────────────┘
                            │
                            │ uses
                            ▼
┌────────────────────────────────────────────────────────────┐
│                   Step1Normalizer                           │
├────────────────────────────────────────────────────────────┤
│  + normalize(a1_result, a3_result)                         │
│  - _parse_a1_missing()                                     │
│  - _parse_a3_suggestions()                                 │
│  - _extract_clause_references()                            │
│  - _expand_article_to_clauses()                            │
└────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────────┐
│                   Step2Aggregator                           │
├────────────────────────────────────────────────────────────┤
│  + aggregate(step1_result)                                 │
│  - _group_by_std_clause()                                  │
│  - _detect_conflicts()                                     │
└────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────────┐
│                   Step3Resolver                             │
├────────────────────────────────────────────────────────────┤
│  + resolve(step2_result, a3_result)                        │
│  - _apply_priority_rules()                                 │
│  - _llm_verify_conflicts()                                 │
│  - _attach_analysis_text()                                 │
└────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────────┐
│                   Step4Reporter                             │
├────────────────────────────────────────────────────────────┤
│  + generate_final_report(step3_result)                     │
│  - _calculate_statistics()                                 │
│  - _format_overall_missing()                               │
│  - _format_user_articles()                                 │
└────────────────────────────────────────────────────────────┘
```

## Data Flow

### Step 1: 1차 정규화 (사용자 조항 기준)

**입력:**
- A1 Stage 2 결과 (`missing_article_analysis`)
- A3 결과 (`article_analysis`)

**처리:**
1. A1 파싱: 
   - `is_truly_missing: true` → 임시 overall_missing_clauses
   - `matching_details` → 사용자 조항별 matched 목록
2. A3 파싱: 
   - `missing_items`, `insufficient_items` → 정규식 추출
   - `matched_articles` → 사용자 조항별 matched 목록 (A1 오탐지 복구)
3. 조 단위 확장: "제23조" → 모든 하위 항목 ID
4. 사용자 조항별 그룹화 (matched, insufficient, missing)
5. **중복 제거**: A3에서 언급된 항목을 overall_missing_clauses에서 제거

**출력 (Step 1):**
```json
{
  "overall_missing_clauses": [
    "urn:std:provide:art:020",
    "urn:std:provide:art:020:sub:001",
    "urn:std:provide:art:020:sub:002"
  ],
  "user_articles": {
    "user_article_3": {
      "matched": [
        "urn:std:provide:art:003"
      ],
      "insufficient": [],
      "missing": []
    },
    "user_article_4": {
      "matched": [
        "urn:std:provide:art:012"
      ],
      "insufficient": [
        "urn:std:provide:art:012:cla:001"
      ],
      "missing": []
    },
    "user_article_14": {
      "matched": [
        "urn:std:provide:art:023",
        "urn:std:provide:art:025"
      ],
      "insufficient": [
        "urn:std:provide:art:025",
        "urn:std:provide:art:025:sub:001"
      ],
      "missing": [
        "urn:std:provide:art:023",
        "urn:std:provide:art:023:sub:001"
      ]
    }
  }
}
```

**핵심:**
- **overall_missing_clauses**: A1에서 `is_truly_missing: true`이고 A3에서도 전혀 언급되지 않은 진짜 전역 누락
- **user_articles.matched**: A1 매칭 결과 + A3 matched_articles (최종 보고서에서 "잘 작성됨" 표시용)
- **user_articles.insufficient/missing**: A3에서 언급된 문제 항목 (A1 오탐지 복구 포함)
- 제14조의 제23조, 제25조는 A1 오탐지였지만 A3에서 matched로 복구되고 동시에 insufficient/missing 문제 발견

### Step 2: 2차 정규화 (표준 항목 기준)

**입력:** Step 1 결과

**처리:**
1. 표준 항목 ID를 키로 재구조화
2. 각 표준 항목에 대한 모든 평가 수집
3. 충돌 감지 (insufficient + missing)

**출력 (Step 2):**
```json
{
  "urn:std:provide:art:012:cla:001": {
    "evaluations": [
      {"user_article": 4, "status": "insufficient"},
      {"user_article": 10, "status": "missing"}
    ],
    "has_conflict": true
  },
  "urn:std:provide:art:023": {
    "evaluations": [
      {"user_article": 14, "status": "missing"}
    ],
    "has_conflict": false
  }
}
```

### Step 3: 충돌 해소 (규칙 + LLM)

**입력:**
- Step 2 결과
- A3 원본 결과 (분석 텍스트 추출용)

**처리:**
1. 우선순위 규칙 적용: `sufficient > insufficient > missing`
2. 충돌 시 LLM 재검증
3. A3 원본 분석 텍스트 첨부
4. Step 1 구조로 재변환 (보정 적용)

**출력 (Step 3):**
```json
{
  "overall_missing_clauses": [
    {
      "std_clause_id": "urn:std:provide:art:020",
      "analysis": "LLM 생성 분석 텍스트..."
    }
  ],
  "user_articles": {
    "user_article_4": {
      "insufficient": [
        {
          "std_clause_id": "urn:std:provide:art:012:cla:001",
          "analysis": "A3 원본 분석..."
        }
      ],
      "missing": []
    },
    "user_article_10": {
      "insufficient": [],
      "missing": []
    }
  }
}
```

### Step 4: 최종 보고서 생성

**입력:** Step 3 결과

**처리:**
1. 요약 통계 계산
2. overall_missing_clauses 포맷팅
3. user_articles 포맷팅
4. 메타데이터 추가

**출력 (Final Report):**
```json
{
  "contract_id": "contract_123",
  "contract_type": "provide",
  "generated_at": "2025-11-12T10:35:00",
  "summary": {
    "total": 50,
    "sufficient": 45,
    "insufficient": 3,
    "missing": 2
  },
  "overall_missing_clauses": [
    {
      "std_clause_id": "urn:std:provide:art:020",
      "std_clause_title": "제20조 (비밀유지의무)",
      "analysis": "..."
    }
  ],
  "user_articles": [
    {
      "user_article_no": 4,
      "user_article_title": "데이터 보안",
      "insufficient": [
        {
          "std_clause_id": "urn:std:provide:art:012:cla:001",
          "std_clause_title": "제12조 제1항",
          "analysis": "..."
        }
      ],
      "missing": []
    }
  ]
}
```

## Components and Interfaces

### 1. Step1Normalizer

**책임:**
- A1, A3 결과 파싱
- 표준 조항 참조 추출 및 ID 매핑
- 조 단위 → 하위 항목 확장
- 사용자 조항 기준 그룹화

**주요 메서드:**
```python
class Step1Normalizer:
    def __init__(self, kb_loader: KnowledgeBaseLoader):
        self.kb_loader = kb_loader
        self.std_chunks = None
    
    def normalize(self, a1_result: dict, a3_result: dict, contract_type: str) -> dict:
        """A1, A3 결과를 사용자 조항 기준으로 정규화"""
        # 표준계약서 청크 로드
        self.std_chunks = self.kb_loader.load_standard_chunks(contract_type)
        
        # A1 파싱
        overall_missing = self._parse_a1_missing(a1_result)
        user_articles = self._parse_a1_matching(a1_result)  # 매칭 결과 추가
        
        # A3 파싱 (기존 user_articles에 추가)
        self._parse_a3_results(a3_result, user_articles)
        
        # A1 전역 누락과 A3 사용자 조항 중복 제거
        # A3에서 언급된 항목은 overall_missing에서 제거
        overall_missing = self._remove_duplicates(overall_missing, user_articles)
        
        return {
            "overall_missing_clauses": overall_missing,
            "user_articles": user_articles
        }
    
    def _parse_a1_missing(self, a1_result: dict) -> list:
        """A1 Stage 2에서 is_truly_missing: true 추출 및 하위 항목 확장"""
        overall_missing = []
        for item in a1_result.get("missing_article_analysis", []):
            if item.get("is_truly_missing"):
                std_article_id = item["standard_article_id"]
                # 조 단위 ID와 모든 하위 항목 ID 추가
                clause_ids = self._expand_article_to_clauses(std_article_id)
                overall_missing.extend(clause_ids)
        return overall_missing
    
    def _parse_a1_matching(self, a1_result: dict) -> dict:
        """A1 matching_details에서 매칭된 표준 조항 추출"""
        user_articles = {}
        for detail in a1_result.get("matching_details", []):
            if detail.get("matched"):
                user_article_no = f"user_article_{detail['user_article_no']}"
                matched_ids = detail.get("matched_articles_global_ids", [])
                user_articles[user_article_no] = {
                    "matched": matched_ids,
                    "insufficient": [],
                    "missing": []
                }
        return user_articles
    
    def _parse_a3_results(self, a3_result: dict, user_articles: dict):
        """A3 결과를 user_articles에 추가 (matched, insufficient, missing)"""
        for article in a3_result.get("article_analysis", []):
            user_article_no = f"user_article_{article['user_article_no']}"
            
            # user_articles에 없으면 초기화
            if user_article_no not in user_articles:
                user_articles[user_article_no] = {
                    "matched": [],
                    "insufficient": [],
                    "missing": []
                }
            
            # A3 matched_articles 추가 (A1 오탐지 복구)
            if article.get("matched_articles"):
                for matched in article["matched_articles"]:
                    global_id = matched.get("global_id")
                    if global_id and global_id not in user_articles[user_article_no]["matched"]:
                        user_articles[user_article_no]["matched"].append(global_id)
            
            # insufficient/missing 파싱
            suggestions = article.get("suggestions", [])
            for suggestion in suggestions:
                # missing_items 파싱
                for item in suggestion.get("missing_items", []):
                    clause_ids = self._extract_clause_references(item)
                    user_articles[user_article_no]["missing"].extend(clause_ids)
                
                # insufficient_items 파싱
                for item in suggestion.get("insufficient_items", []):
                    clause_ids = self._extract_clause_references(item)
                    user_articles[user_article_no]["insufficient"].extend(clause_ids)
    
    def _remove_duplicates(self, overall_missing: list, user_articles: dict) -> list:
        """A3에서 언급된 항목을 overall_missing에서 제거
        
        A1 오탐지 복구된 항목은 이미 A3에 포함되어 있으므로,
        A3에서 언급된 모든 ID를 overall_missing에서 제거한다.
        
        예시:
        - A1: 제23조 누락 → Stage 2: is_truly_missing: false (오탐지, 제14조에서 발견)
        - A3: 제14조 분석 시 제23조 missing 언급
        - 결과: overall_missing에서 제23조 제거, user_article_14에만 포함
        """
        # user_articles의 모든 insufficient/missing ID 수집
        mentioned_ids = set()
        for article_data in user_articles.values():
            mentioned_ids.update(article_data.get("insufficient", []))
            mentioned_ids.update(article_data.get("missing", []))
        
        # overall_missing에서 제거 (A3에서 언급된 것은 전역 누락 아님)
        return [id for id in overall_missing if id not in mentioned_ids]
    
    def _extract_clause_references(self, text: str) -> list:
        """정규식으로 "제N조", "제N조 제M항" 추출"""
        pass
    
    def _expand_article_to_clauses(self, article_ref: str) -> list:
        """조 단위 참조를 모든 하위 항목 ID로 확장"""
        pass
```

### 2. Step2Aggregator

**책임:**
- 표준 항목 기준 재집계
- 충돌 감지

**주요 메서드:**
```python
class Step2Aggregator:
    def aggregate(self, step1_result: dict) -> dict:
        """표준 항목 기준으로 재집계"""
        aggregated = {}
        
        # user_articles 순회
        for user_article_no, data in step1_result["user_articles"].items():
            for status in ["insufficient", "missing"]:
                for std_clause_id in data.get(status, []):
                    if std_clause_id not in aggregated:
                        aggregated[std_clause_id] = {"evaluations": []}
                    
                    aggregated[std_clause_id]["evaluations"].append({
                        "user_article": user_article_no,
                        "status": status
                    })
        
        # 충돌 감지
        for std_clause_id, data in aggregated.items():
            statuses = {e["status"] for e in data["evaluations"]}
            data["has_conflict"] = len(statuses) > 1
        
        return aggregated
```

### 3. Step3Resolver

**책임:**
- 우선순위 규칙 적용
- LLM 재검증
- A3 원본 분석 텍스트 첨부

**주요 메서드:**
```python
class Step3Resolver:
    def __init__(self, llm_client):
        self.llm = llm_client
    
    def resolve(self, step2_result: dict, a3_result: dict, step1_result: dict) -> dict:
        """충돌 해소 및 분석 텍스트 첨부"""
        resolved = {"user_articles": {}}
        
        # 충돌 해소
        for std_clause_id, data in step2_result.items():
            if data["has_conflict"]:
                final_status = self._llm_verify_conflict(std_clause_id, data, a3_result)
            else:
                final_status = data["evaluations"][0]["status"]
            
            # 보정 적용
            self._apply_resolution(resolved, data, final_status)
        
        # A3 원본 분석 텍스트 첨부
        self._attach_analysis_text(resolved, a3_result)
        
        return resolved
    
    def _llm_verify_conflict(self, std_clause_id: str, conflict_data: dict, a3_result: dict) -> str:
        """LLM으로 충돌 재검증"""
        pass
    
    def _attach_analysis_text(self, resolved: dict, a3_result: dict):
        """A3 원본 분석 텍스트 첨부"""
        pass
```

### 4. Step4Reporter

**책임:**
- 최종 보고서 생성
- 요약 통계 계산
- 메타데이터 추가

**주요 메서드:**
```python
class Step4Reporter:
    def generate_final_report(self, step3_result: dict, contract_id: str, contract_type: str) -> dict:
        """최종 보고서 생성"""
        report = {
            "contract_id": contract_id,
            "contract_type": contract_type,
            "generated_at": datetime.now().isoformat(),
            "summary": self._calculate_statistics(step3_result),
            "overall_missing_clauses": self._format_overall_missing(step3_result),
            "user_articles": self._format_user_articles(step3_result)
        }
        
        return report
    
    def _calculate_statistics(self, step3_result: dict) -> dict:
        """요약 통계 계산"""
        pass
```

## Data Models

### Step 1 Schema
```python
Step1Result = {
    "overall_missing_clauses": List[str],  # global_id 목록
    "user_articles": Dict[str, {
        "matched": List[str],       # global_id 목록 (A1 매칭 + A3 matched_articles)
        "insufficient": List[str],  # global_id 목록
        "missing": List[str]        # global_id 목록
    }]
}
```

### Step 2 Schema
```python
Step2Result = Dict[str, {  # key: std_clause_id
    "evaluations": List[{
        "user_article": str,  # "user_article_4"
        "status": str         # "insufficient" | "missing"
    }],
    "has_conflict": bool
}]
```

### Step 3 Schema
```python
Step3Result = {
    "overall_missing_clauses": List[{
        "std_clause_id": str,
        "analysis": str
    }],
    "user_articles": Dict[str, {
        "matched": List[str],  # global_id 목록 (Step 1에서 그대로 유지)
        "insufficient": List[{
            "std_clause_id": str,
            "analysis": str
        }],
        "missing": List[{
            "std_clause_id": str,
            "analysis": str
        }]
    }]
}
```

### Final Report Schema
```python
FinalReport = {
    "contract_id": str,
    "contract_type": str,
    "generated_at": str,  # ISO 8601
    "summary": {
        "total": int,
        "sufficient": int,
        "insufficient": int,
        "missing": int
    },
    "overall_missing_clauses": List[{
        "std_clause_id": str,
        "std_clause_title": str,
        "analysis": str
    }],
    "user_articles": List[{
        "user_article_no": int,
        "user_article_title": str,
        "matched": List[{  # 잘 작성된 항목 (최종 보고서에 표시)
            "std_clause_id": str,
            "std_clause_title": str
        }],
        "insufficient": List[{
            "std_clause_id": str,
            "std_clause_title": str,
            "analysis": str
        }],
        "missing": List[{
            "std_clause_id": str,
            "std_clause_title": str,
            "analysis": str
        }]
    }]
}
```

## LLM Prompts

### Conflict Resolution Prompt

```python
CONFLICT_RESOLUTION_PROMPT = """
당신은 데이터 표준계약서 검증 전문가입니다.

동일한 표준 조항에 대해 여러 사용자 조항에서 상충되는 평가가 있습니다.
최종 상태를 판단해주세요.

**표준 조항:**
{std_clause_text}

**평가 내역:**
{evaluations}

**질문:**
이 표준 조항의 최종 상태를 판단하고 그 이유를 설명해주세요.

**응답 형식:**
```json
{{
  "final_status": "sufficient" | "insufficient" | "missing",
  "reasoning": "판단 근거..."
}}
```

**판단 기준:**
- sufficient: 표준 조항의 요구사항이 충족됨
- insufficient: 일부 내용이 있으나 불충분함
- missing: 완전히 누락됨
"""
```

### Overall Missing Analysis Prompt

```python
OVERALL_MISSING_PROMPT = """
당신은 데이터 표준계약서 검증 전문가입니다.

사용자 계약서 전체에서 다음 표준 조항이 누락되었습니다.
누락된 조항에 대한 분석을 작성해주세요.

**표준 조항:**
{std_clause_text}

**분석 요청:**
1. 이 조항의 핵심 내용
2. 누락으로 인한 법적 리스크
3. 추가 권장사항

**응답 형식:**
간결하고 명확한 한국어로 작성해주세요.
"""
```

## Error Handling

### Exception Hierarchy

```python
class ReportAgentError(Exception):
    """Base exception for Report Agent"""
    pass

class ParsingError(ReportAgentError):
    """A1/A3 결과 파싱 실패"""
    pass

class ClauseReferenceError(ReportAgentError):
    """표준 조항 참조 추출 실패"""
    pass

class LLMVerificationError(ReportAgentError):
    """LLM 재검증 실패"""
    pass

class DatabaseSaveError(ReportAgentError):
    """DB 저장 실패"""
    pass
```

### Error Recovery Strategy

1. **파싱 실패**: 원본 텍스트 보존, 경고 로그
2. **LLM 실패**: 기본 우선순위 규칙 적용, 재시도 (최대 3회)
3. **DB 저장 실패**: 재시도 (최대 3회), 실패 시 에러 로그
4. **부분 실패**: 완료된 단계까지 저장, 에러 정보 기록

## Testing Strategy

### Unit Tests
- Step1Normalizer: A1/A3 파싱, 정규식 추출, 조 단위 확장
- Step2Aggregator: 재집계, 충돌 감지
- Step3Resolver: 우선순위 규칙, LLM 재검증
- Step4Reporter: 통계 계산, 포맷팅

### Integration Tests
- 전체 파이프라인: Step 1 → 2 → 3 → 4
- DB 저장 및 조회
- LLM 통합

### Test Data
- A1 결과 샘플 (is_truly_missing: true/false)
- A3 결과 샘플 (조 단위 언급, 항 단위 언급)
- 충돌 시나리오 (insufficient + missing)

## Performance Considerations

### Optimization Targets
- Step 1: 50개 조항 < 2초
- Step 2: 50개 조항 < 1초
- Step 3 (LLM 포함): 충돌 5개 < 10초
- Step 4: < 1초

### Caching Strategy
- 표준계약서 청크: 메모리 캐싱
- LLM 결과: 동일 입력 캐싱 (선택적)

### Batch Processing
- LLM 호출: 가능한 경우 배치 처리
- DB 저장: 트랜잭션 단위 최적화

## Deployment

### Celery Task
```python
@celery_app.task(name="report_agent.generate_report")
def generate_report_task(contract_id: str):
    """Report Agent Celery 태스크"""
    try:
        agent = ReportAgent()
        report = agent.generate_report(contract_id)
        return {"status": "success", "report": report}
    except Exception as e:
        logger.error(f"Report generation failed: {e}")
        return {"status": "failed", "error": str(e)}
```

### API Endpoint
```python
@app.get("/api/report/{contract_id}")
async def get_report(contract_id: str):
    """최종 보고서 조회"""
    result = db.query(ValidationResult).filter_by(contract_id=contract_id).first()
    if not result or not result.final_report:
        raise HTTPException(404, "Report not found")
    
    return result.final_report
```

## Future Enhancements

1. **A2 통합**: 체크리스트 검증 결과 통합
2. **PDF 출력**: 보고서 PDF 다운로드
3. **다국어 지원**: 영어 보고서 생성
4. **커스터마이징**: 사용자 정의 보고서 템플릿
5. **비교 분석**: 여러 계약서 비교 보고서

