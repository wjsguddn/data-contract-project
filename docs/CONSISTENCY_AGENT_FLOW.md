# Consistency Agent Flow Diagram

## 전체 검증 프로세스

```mermaid
graph TB
    Start([사용자 계약서 업로드]) --> Upload[FastAPI: 파일 저장]
    Upload --> Parse[DOCX 파싱]
    Parse --> Classify[Classification Agent]
    Classify --> ValidateStart{검증 시작}
    
    ValidateStart --> A1[A1: 완전성 검증]
    A1 --> A1Success{A1 성공?}
    A1Success -->|실패| Error1[검증 실패 반환]
    A1Success -->|성공| A2[A2: 체크리스트 검증]
    
    A2 --> A2Success{A2 성공?}
    A2Success -->|실패| Partial1[부분 성공 반환]
    A2Success -->|성공| A3[A3: 내용 분석]
    
    A3 --> A3Success{A3 성공?}
    A3Success -->|실패| Partial2[부분 성공 반환]
    A3Success -->|성공| Complete[검증 완료]
    
    Complete --> SaveDB[(ValidationResult 저장)]
    SaveDB --> Return([결과 반환])
    
    Error1 --> Return
    Partial1 --> Return
    Partial2 --> Return
    
    style A1 fill:#e1f5ff
    style A2 fill:#fff4e1
    style A3 fill:#ffe1f5
    style Complete fill:#e1ffe1
```


## A1 노드: 완전성 검증 (Completeness Check)

```mermaid
graph TB
    A1Start([A1 노드 시작]) --> LoadContract[계약서 데이터 로드]
    LoadContract --> GetType[분류 결과 확인]
    GetType --> InitA1[A1 노드 초기화]
    
    InitA1 --> LoadKB[지식베이스 로드]
    LoadKB --> LoadStd[표준계약서 조항 로드]
    
    LoadStd --> MatchLoop{각 사용자 조항}
    
    MatchLoop --> BuildQuery[검색 쿼리 생성]
    BuildQuery --> HybridSearch[하이브리드 검색]
    
    HybridSearch --> FAISS[FAISS 시멘틱 검색<br/>가중치: 0.85]
    HybridSearch --> Whoosh[Whoosh 키워드 검색<br/>가중치: 0.15]
    
    FAISS --> Combine[점수 결합]
    Whoosh --> Combine
    
    Combine --> Aggregate[청크→조 단위 집계]
    Aggregate --> Normalize[정규화 점수 계산<br/>avg_score / sqrt total_chunks]
    
    Normalize --> Threshold{점수 ≥ 0.7?}
    Threshold -->|Yes| Matched[매칭 성공]
    Threshold -->|No| Unmatched[매칭 실패]
    
    Matched --> NextArticle{다음 조항?}
    Unmatched --> NextArticle
    NextArticle -->|있음| MatchLoop
    NextArticle -->|없음| FindMissing[누락 조항 식별]
    
    FindMissing --> CalcStats[통계 계산]
    CalcStats --> SaveA1[(A1 결과 저장)]
    SaveA1 --> A1End([A1 노드 완료])
    
    style HybridSearch fill:#e1f5ff
    style Matched fill:#e1ffe1
    style Unmatched fill:#ffe1e1
```


## A2 노드: 체크리스트 검증 (Checklist Validation)

```mermaid
graph TB
    A2Start([A2 노드 시작]) --> LoadA1[A1 결과 로드]
    LoadA1 --> GetMatches[매칭된 조항 목록 확인]
    
    GetMatches --> CheckLoop{각 매칭 조항}
    
    CheckLoop --> LoadChecklist[표준 조항 체크리스트 로드]
    LoadChecklist --> HasChecklist{체크리스트<br/>존재?}
    
    HasChecklist -->|No| SkipArticle[조항 건너뛰기]
    HasChecklist -->|Yes| ItemLoop{각 체크리스트 항목}
    
    ItemLoop --> BuildPrompt[LLM 프롬프트 생성]
    BuildPrompt --> CallLLM[Azure OpenAI 호출]
    
    CallLLM --> ParseResponse[응답 파싱]
    ParseResponse --> CheckResult{충족 여부}
    
    CheckResult -->|충족| PassItem[통과 항목 기록]
    CheckResult -->|미충족| FailItem[미충족 항목 기록]
    
    PassItem --> NextItem{다음 항목?}
    FailItem --> NextItem
    NextItem -->|있음| ItemLoop
    NextItem -->|없음| NextArticle2{다음 조항?}
    
    SkipArticle --> NextArticle2
    NextArticle2 -->|있음| CheckLoop
    NextArticle2 -->|없음| CalcA2Stats[통계 계산]
    
    CalcA2Stats --> SaveA2[(A2 결과 저장)]
    SaveA2 --> A2End([A2 노드 완료])
    
    style CallLLM fill:#fff4e1
    style PassItem fill:#e1ffe1
    style FailItem fill:#ffe1e1
```


## A3 노드: 내용 분석 (Content Analysis)

```mermaid
graph TB
    A3Start([A3 노드 시작]) --> LoadA1_A3[A1 결과 로드]
    LoadA1_A3 --> GetMatches_A3[매칭된 조항 목록 확인]
    
    GetMatches_A3 --> ArticleLoop{각 사용자 조항}
    
    ArticleLoop --> CheckMatch{매칭 여부}
    
    CheckMatch -->|매칭됨| LoadStdArticle[표준 조항 전체 로드]
    CheckMatch -->|미매칭| SpecialCheck{특수 조항?}
    
    LoadStdArticle --> BuildContext[컨텍스트 구성]
    BuildContext --> ComparePrompt[비교 프롬프트 생성]
    
    ComparePrompt --> LLMCompare[LLM 내용 비교]
    LLMCompare --> ParseScores[점수 파싱<br/>완전성/명확성/실무성]
    
    ParseScores --> ExtractIssues[문제점 추출<br/>누락/불명확/실무 문제]
    ExtractIssues --> GenSuggestions[개선 제안 생성]
    
    GenSuggestions --> SaveAnalysis[조항 분석 저장]
    
    SpecialCheck -->|Yes| AnalyzeSpecial[특수 조항 분석]
    SpecialCheck -->|No| SkipAnalysis[분석 건너뛰기]
    
    AnalyzeSpecial --> SpecialPrompt[특수 조항 프롬프트]
    SpecialPrompt --> LLMSpecial[LLM 특수 분석]
    LLMSpecial --> SaveSpecial[특수 분석 저장]
    
    SaveAnalysis --> NextArticle3{다음 조항?}
    SaveSpecial --> NextArticle3
    SkipAnalysis --> NextArticle3
    
    NextArticle3 -->|있음| ArticleLoop
    NextArticle3 -->|없음| CalcOverall[전체 점수 계산]
    
    CalcOverall --> SaveA3[(A3 결과 저장)]
    SaveA3 --> A3End([A3 노드 완료])
    
    style LLMCompare fill:#ffe1f5
    style LLMSpecial fill:#ffe1f5
    style SaveAnalysis fill:#e1ffe1
```


## 하이브리드 검색 상세 (A1 노드)

```mermaid
graph LR
    Query[검색 쿼리] --> Split{검색 방식}
    
    Split --> Dense[Dense 검색<br/>FAISS]
    Split --> Sparse[Sparse 검색<br/>Whoosh]
    
    Dense --> Embed[임베딩 생성<br/>Azure OpenAI]
    Embed --> FAISSSearch[벡터 유사도 검색]
    FAISSSearch --> DenseScore[시멘틱 점수]
    
    Sparse --> Tokenize[토큰화]
    Tokenize --> WhooshSearch[키워드 매칭]
    WhooshSearch --> SparseScore[키워드 점수]
    
    DenseScore --> Combine[가중 결합<br/>0.85 × dense + 0.15 × sparse]
    SparseScore --> Combine
    
    Combine --> FinalScore[최종 점수]
    
    style Dense fill:#e1f5ff
    style Sparse fill:#fff4e1
    style Combine fill:#e1ffe1
```

## 데이터 흐름

```mermaid
graph TB
    subgraph "입력"
        Input1[사용자 계약서<br/>parsed_data]
        Input2[분류 결과<br/>contract_type]
    end
    
    subgraph "A1: 완전성 검증"
        A1Process[조항 매칭<br/>하이브리드 검색]
        A1Output[매칭 결과<br/>누락 조항]
    end
    
    subgraph "A2: 체크리스트"
        A2Process[체크리스트 검증<br/>LLM 판단]
        A2Output[충족/미충족 항목]
    end
    
    subgraph "A3: 내용 분석"
        A3Process[내용 비교<br/>LLM 평가]
        A3Output[점수 + 제안]
    end
    
    subgraph "출력"
        Output[ValidationResult<br/>통합 결과]
    end
    
    Input1 --> A1Process
    Input2 --> A1Process
    A1Process --> A1Output
    
    A1Output --> A2Process
    Input1 --> A2Process
    A2Process --> A2Output
    
    A1Output --> A3Process
    Input1 --> A3Process
    A3Process --> A3Output
    
    A1Output --> Output
    A2Output --> Output
    A3Output --> Output
    
    style A1Process fill:#e1f5ff
    style A2Process fill:#fff4e1
    style A3Process fill:#ffe1f5
    style Output fill:#e1ffe1
```


## 에러 처리 흐름

```mermaid
graph TB
    Start([작업 시작]) --> Try{실행}
    
    Try -->|성공| Success[결과 반환]
    Try -->|실패| ErrorType{에러 유형}
    
    ErrorType -->|DB 오류| DBError[DB 연결 재시도]
    ErrorType -->|LLM 오류| LLMError[지수 백오프 재시도]
    ErrorType -->|검색 오류| SearchError[기본값 사용]
    ErrorType -->|기타| OtherError[에러 로그 기록]
    
    DBError --> Retry1{재시도<br/>성공?}
    LLMError --> Retry2{재시도<br/>성공?}
    
    Retry1 -->|Yes| Success
    Retry1 -->|No| Fail[실패 반환]
    
    Retry2 -->|Yes| Success
    Retry2 -->|No| DefaultValue[기본값 사용]
    
    SearchError --> DefaultValue
    DefaultValue --> PartialSuccess[부분 성공 반환]
    
    OtherError --> Fail
    
    Success --> End([작업 완료])
    PartialSuccess --> End
    Fail --> End
    
    style Success fill:#e1ffe1
    style PartialSuccess fill:#fff4e1
    style Fail fill:#ffe1e1
```

## Celery 작업 큐 구조

```mermaid
graph LR
    subgraph "FastAPI"
        API[POST /validate]
    end
    
    subgraph "Redis Queue"
        Queue[consistency_validation]
    end
    
    subgraph "Celery Worker"
        Worker1[Worker 1]
        Worker2[Worker 2]
        Worker3[Worker 3]
    end
    
    subgraph "작업"
        Task1[validate_contract_task]
        Task2[check_completeness_task]
        Task3[analyze_content_task]
    end
    
    API -->|작업 제출| Queue
    Queue -->|작업 분배| Worker1
    Queue -->|작업 분배| Worker2
    Queue -->|작업 분배| Worker3
    
    Worker1 --> Task1
    Worker2 --> Task2
    Worker3 --> Task3
    
    Task1 --> DB[(Database)]
    Task2 --> DB
    Task3 --> DB
    
    style Queue fill:#fff4e1
    style DB fill:#e1f5ff
```


## 성능 최적화 포인트

```mermaid
graph TB
    subgraph "캐싱 전략"
        Cache1[지식베이스 인덱스<br/>메모리 캐싱]
        Cache2[표준계약서 원본<br/>첫 로드 시 캐싱]
        Cache3[조별 청크 개수<br/>초기화 시 계산]
    end
    
    subgraph "배치 처리"
        Batch1[여러 조항 동시 처리<br/>LLM API 호출 최소화]
        Batch2[청크 검색 결과 집계<br/>조 단위 취합]
    end
    
    subgraph "병렬 처리 (Phase 2)"
        Parallel1[A2 + A3 병렬 실행<br/>A1 완료 후]
        Parallel2[조항별 독립 분석<br/>멀티스레딩]
    end
    
    Cache1 --> Performance[성능 향상]
    Cache2 --> Performance
    Cache3 --> Performance
    Batch1 --> Performance
    Batch2 --> Performance
    Parallel1 --> Performance
    Parallel2 --> Performance
    
    style Performance fill:#e1ffe1
```

## 주요 특징

### 1. 순차 실행 구조
- A1 → A2 → A3 순차 실행
- 각 노드는 이전 노드 결과 참조
- 실패 시 부분 성공 반환 가능

### 2. 하이브리드 검색 (A1)
- FAISS 시멘틱 검색 (85%) + Whoosh 키워드 검색 (15%)
- 멀티벡터 방식: 각 하위항목으로 개별 검색
- 정규화 점수로 조 단위 집계

### 3. LLM 기반 평가 (A2, A3)
- Azure OpenAI GPT-4 사용
- 맥락 기반 유연한 판단
- 구조화된 JSON 응답

### 4. 에러 복원력
- 지수 백오프 재시도
- 기본값 사용으로 부분 성공
- 상세한 에러 로깅

### 5. 확장 가능성
- Phase 2: A2 + A3 병렬 실행
- 활용안내서 통합
- 조항별 병렬 분석

## 관련 문서
- [A1 노드 상세 플로우](./A1_FLOW_DIAGRAMS.md)
- [A1 하이브리드 검색](./CONSISTENCY_A1_HYBRID_SEARCH.md)
- [시스템 아키텍처](./SYSTEM_ARCHITECTURE.md)
- [Consistency Agent 요약](./CONSISTENCY_A1_SUMMARY.md)
