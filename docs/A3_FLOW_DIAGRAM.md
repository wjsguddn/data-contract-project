# A3 노드 (Content Analysis) Flow Diagram

## 전체 프로세스 흐름

```mermaid
flowchart TD
    Start([A3 노드 시작]) --> LoadContract[계약서 데이터 로드]
    LoadContract --> CheckA1{A1 결과 존재?}
    
    CheckA1 -->|없음| Error1[에러: A1 먼저 실행 필요]
    CheckA1 -->|있음| LoadA1[A1 매칭 결과 로드]
    
    LoadA1 --> InitComponents[컴포넌트 초기화<br/>- KnowledgeBaseLoader<br/>- AzureOpenAI Client]
    
    InitComponents --> LoopStart{모든 조항<br/>처리 완료?}
    
    LoopStart -->|아니오| GetArticle[다음 사용자 조항 가져오기]
    GetArticle --> CheckMatched{A1에서<br/>매칭됨?}
    
    CheckMatched -->|아니오| SkipArticle[조항 건너뛰기<br/>분석 불필요]
    SkipArticle --> LoopStart
    
    CheckMatched -->|예| LoadStdArticle[표준 조항 전체 로드<br/>parent_id 기준]
    
    LoadStdArticle --> BuildContext[컨텍스트 구성<br/>- 사용자 조항 내용<br/>- 표준 조항 내용]
    
    BuildContext --> CallLLM[LLM 내용 비교<br/>GPT-4 API 호출]
    
    CallLLM --> ParseResponse{응답 파싱<br/>성공?}
    
    ParseResponse -->|실패| Retry{재시도<br/>가능?}
    Retry -->|예| CallLLM
    Retry -->|아니오| UseDefault[기본값 사용<br/>모든 점수 0.5]
    
    ParseResponse -->|성공| ExtractScores[점수 추출<br/>- completeness<br/>- clarity<br/>- practicality]
    
    ExtractScores --> ExtractIssues[이슈 추출<br/>- missing_elements<br/>- unclear_points<br/>- practical_issues]
    
    UseDefault --> SaveResult
    ExtractIssues --> SaveResult[조항 분석 결과 저장<br/>ArticleAnalysis]
    
    SaveResult --> LoopStart
    
    LoopStart -->|예| CalcOverall[전체 점수 계산<br/>평균값]
    
    CalcOverall --> BuildResult[ContentAnalysisResult 생성]
    
    BuildResult --> SaveDB[DB 저장<br/>ValidationResult.content_analysis]
    
    SaveDB --> End([A3 노드 완료])
    
    Error1 --> EndError([종료: 에러])
    
    style Start fill:#e1f5e1
    style End fill:#e1f5e1
    style EndError fill:#ffe1e1
    style CallLLM fill:#fff4e1
    style SaveDB fill:#e1e5ff
```

## LLM 내용 비교 상세 흐름

```mermaid
flowchart TD
    Start([LLM 비교 시작]) --> FormatUser[사용자 조항 포맷팅<br/>제목 + 내용 배열]
    
    FormatUser --> FormatStd[표준 조항 포맷팅<br/>모든 청크 내용 결합]
    
    FormatStd --> BuildPrompt[프롬프트 구성<br/>- 평가 원칙<br/>- 표준 조항 컨텍스트<br/>- 사용자 조항<br/>- 평가 항목]
    
    BuildPrompt --> SetParams[API 파라미터 설정<br/>- model: gpt-4<br/>- temperature: 0.3<br/>- response_format: json]
    
    SetParams --> CallAPI[Azure OpenAI API 호출]
    
    CallAPI --> CheckStatus{API 호출<br/>성공?}
    
    CheckStatus -->|실패| LogError[에러 로깅]
    LogError --> ReturnError[에러 반환]
    
    CheckStatus -->|성공| ParseJSON{JSON 파싱<br/>성공?}
    
    ParseJSON -->|실패| LogParseError[파싱 에러 로깅]
    LogParseError --> ReturnError
    
    ParseJSON -->|성공| ValidateFields{필수 필드<br/>존재?}
    
    ValidateFields -->|아니오| LogValidError[검증 에러 로깅]
    LogValidError --> ReturnError
    
    ValidateFields -->|예| ExtractData[데이터 추출<br/>- 점수 3개<br/>- 이슈 3개 배열<br/>- reasoning]
    
    ExtractData --> NormalizeScores[점수 정규화<br/>0.0 ~ 1.0 범위]
    
    NormalizeScores --> ReturnResult[결과 반환]
    
    ReturnResult --> End([비교 완료])
    ReturnError --> End
    
    style Start fill:#e1f5e1
    style End fill:#e1f5e1
    style CallAPI fill:#fff4e1
    style ReturnError fill:#ffe1e1
```

## 프롬프트 구조

```mermaid
graph TD
    Prompt[LLM 프롬프트] --> Section1[1. 역할 정의<br/>데이터 계약서 검증 전문가]
    
    Prompt --> Section2[2. 평가 원칙<br/>- 실질적 내용 평가<br/>- 의미 유사성 인정<br/>- 맥락 기반 유연성<br/>- 표준은 권장사항<br/>- 추가 내용 긍정 평가]
    
    Prompt --> Section3[3. 표준 조항 컨텍스트<br/>매칭된 표준 조항 전체 내용]
    
    Prompt --> Section4[4. 사용자 조항<br/>평가 대상 조항]
    
    Prompt --> Section5[5. 평가 항목<br/>- 완전성 0~1<br/>- 명확성 0~1<br/>- 실무성 0~1]
    
    Prompt --> Section6[6. 출력 형식<br/>JSON 스키마 정의]
    
    Section1 --> Output[LLM 응답]
    Section2 --> Output
    Section3 --> Output
    Section4 --> Output
    Section5 --> Output
    Section6 --> Output
    
    Output --> JSON{JSON 형식<br/>- completeness<br/>- clarity<br/>- practicality<br/>- missing_elements[]<br/>- unclear_points[]<br/>- practical_issues[]<br/>- reasoning}
    
    style Prompt fill:#e1f5ff
    style Output fill:#fff4e1
    style JSON fill:#e1ffe1
```

## 데이터 흐름

```mermaid
flowchart LR
    subgraph Input
        A1Result[A1 매칭 결과<br/>matched_articles]
        UserContract[사용자 계약서<br/>parsed_data]
        StdKB[표준계약서<br/>지식베이스]
    end
    
    subgraph Processing
        A1Result --> Filter[매칭된 조항만 필터링]
        Filter --> LoadStd[표준 조항 로드]
        UserContract --> LoadStd
        StdKB --> LoadStd
        
        LoadStd --> Compare[LLM 내용 비교]
        Compare --> Analyze[분석 결과 생성]
    end
    
    subgraph Output
        Analyze --> ArticleList[ArticleAnalysis 배열<br/>- 조항별 점수<br/>- 이슈 목록<br/>- reasoning]
        
        ArticleList --> Overall[전체 점수<br/>평균 계산]
        
        Overall --> Result[ContentAnalysisResult<br/>- article_analysis<br/>- overall_scores<br/>- 통계]
        
        Result --> DB[(ValidationResult DB<br/>content_analysis 필드)]
    end
    
    style Input fill:#e1f5ff
    style Processing fill:#fff4e1
    style Output fill:#e1ffe1
```

## 에러 처리 흐름

```mermaid
flowchart TD
    Start([에러 발생]) --> CheckType{에러 유형}
    
    CheckType -->|A1 결과 없음| E1[ValueError 발생<br/>A1 먼저 실행 필요]
    CheckType -->|계약서 없음| E2[ValueError 발생<br/>계약서 ID 확인]
    CheckType -->|LLM API 실패| E3[API 에러 처리]
    CheckType -->|JSON 파싱 실패| E4[파싱 에러 처리]
    CheckType -->|DB 저장 실패| E5[DB 에러 처리]
    
    E1 --> Log1[에러 로깅]
    E2 --> Log2[에러 로깅]
    
    E3 --> Retry{재시도<br/>횟수 < 3?}
    Retry -->|예| Wait[지수 백오프 대기]
    Wait --> RetryAPI[API 재호출]
    RetryAPI --> CheckRetry{성공?}
    CheckRetry -->|예| Continue[처리 계속]
    CheckRetry -->|아니오| Retry
    
    Retry -->|아니오| UseDefault[기본값 사용<br/>점수 0.5]
    UseDefault --> Log3[경고 로깅]
    
    E4 --> Log4[파싱 에러 로깅]
    Log4 --> UseDefault
    
    E5 --> Log5[DB 에러 로깅]
    Log5 --> Rollback[트랜잭션 롤백]
    
    Log1 --> Return[에러 반환<br/>status: failed]
    Log2 --> Return
    Log3 --> Continue
    Rollback --> Return
    
    Continue --> End([처리 계속])
    Return --> EndError([종료: 에러])
    
    style Start fill:#ffe1e1
    style End fill:#e1f5e1
    style EndError fill:#ffe1e1
    style UseDefault fill:#fff4e1
```

## 성능 최적화 포인트

```mermaid
graph TD
    Opt[성능 최적화] --> Cache1[지식베이스 캐싱<br/>인덱스 메모리 유지]
    
    Opt --> Cache2[표준 조항 캐싱<br/>중복 로드 방지]
    
    Opt --> Batch[배치 처리<br/>여러 조항 한번에 분석<br/>Phase 2]
    
    Opt --> Parallel[병렬 처리<br/>조항별 독립 분석<br/>Phase 2]
    
    Opt --> Timeout[타임아웃 설정<br/>LLM API 30초]
    
    Opt --> Limit[처리 제한<br/>조항당 최대 5분]
    
    Cache1 --> Perf[성능 향상<br/>- 검색 속도 ↑<br/>- 메모리 효율 ↑<br/>- API 호출 ↓]
    Cache2 --> Perf
    Batch --> Perf
    Parallel --> Perf
    Timeout --> Perf
    Limit --> Perf
    
    style Opt fill:#e1f5ff
    style Perf fill:#e1ffe1
```

## 주요 컴포넌트 관계

```mermaid
classDiagram
    class ContentAnalysisNode {
        +knowledge_base_loader
        +azure_client
        +analyze_contract()
        +analyze_article()
    }
    
    class KnowledgeBaseLoader {
        +load_standard_article()
        +search_chunks()
    }
    
    class AzureOpenAI {
        +chat.completions.create()
    }
    
    class ArticleAnalysis {
        +user_article_no
        +matched
        +completeness
        +clarity
        +practicality
        +missing_elements
        +unclear_points
        +practical_issues
    }
    
    class ContentAnalysisResult {
        +contract_id
        +article_analysis[]
        +overall_scores
        +total_articles
        +analyzed_articles
    }
    
    class ValidationResult {
        +contract_id
        +content_analysis
        +completeness_check
        +checklist_validation
    }
    
    ContentAnalysisNode --> KnowledgeBaseLoader : uses
    ContentAnalysisNode --> AzureOpenAI : uses
    ContentAnalysisNode --> ArticleAnalysis : creates
    ContentAnalysisNode --> ContentAnalysisResult : creates
    ContentAnalysisResult --> ValidationResult : saved to
    ArticleAnalysis --> ContentAnalysisResult : contains
```

## 실행 시퀀스

```mermaid
sequenceDiagram
    participant Celery as Celery Task
    participant A3 as ContentAnalysisNode
    participant DB as Database
    participant KB as KnowledgeBase
    participant LLM as Azure OpenAI
    
    Celery->>DB: 계약서 & A1 결과 로드
    DB-->>Celery: contract, A1 matching
    
    Celery->>A3: analyze_contract()
    
    loop 각 매칭된 조항
        A3->>KB: load_standard_article(parent_id)
        KB-->>A3: 표준 조항 전체 내용
        
        A3->>A3: build_context()
        A3->>LLM: compare_articles(user, std)
        
        alt API 성공
            LLM-->>A3: JSON 응답
            A3->>A3: parse & validate
        else API 실패
            LLM-->>A3: 에러
            A3->>A3: 재시도 또는 기본값
        end
        
        A3->>A3: create ArticleAnalysis
    end
    
    A3->>A3: calculate overall scores
    A3->>A3: create ContentAnalysisResult
    A3-->>Celery: result
    
    Celery->>DB: save to ValidationResult
    DB-->>Celery: 저장 완료
    
    Celery-->>Celery: return summary
```
