# 시스템 아키텍처 다이어그램

## 전체 시스템 아키텍처

```mermaid
graph LR
    subgraph 입력
        USER_DOC[사용자 계약서<br/>DOCX]
    end
    
    subgraph 처리
        PARSE[파싱]
        EMBED[embedding]
    end
    
    subgraph 지식베이스_사전구축
        STD_DOC[표준계약서<br/>DOCX]
        GUIDE_DOC[활용안내서<br/>PDF]
        INGEST[Ingestion<br/>파싱→청킹→임베딩]
        KB[검색 인덱스<br/>FAISS + Whoosh]
    end
    
    subgraph 분석
        CLASS[Classification<br/>Agent]
        CONSIST[Consistency<br/>Agent]
        REPORT[Report<br/>Agent]
        CHATBOT[Chatbot<br/>Agent]
    end
    
    subgraph 출력
        RESULT[분석 보고서]
        CHAT_RESULT[챗봇 응답]
    end
    
    USER_DOC --> PARSE
    PARSE --> EMBED
    EMBED --> CLASS
    
    STD_DOC --> INGEST
    GUIDE_DOC --> INGEST
    INGEST --> KB
    
    KB --> CLASS
    KB --> CONSIST
    KB --> CHATBOT
    
    CLASS --> CONSIST
    CONSIST --> REPORT
    REPORT --> RESULT
    
    CHATBOT --> CHAT_RESULT

    style USER_DOC fill:#e3f2fd
    style STD_DOC fill:#e3f2fd
    style GUIDE_DOC fill:#e3f2fd
    style CLASS fill:#e8f5e9
    style CONSIST fill:#e8f5e9
    style REPORT fill:#e8f5e9
    style CHATBOT fill:#fff9c4
    style KB fill:#f3e5f5
    style RESULT fill:#c8e6c9
    style CHAT_RESULT fill:#fff9c4
```

## 데이터 처리 파이프라인

```mermaid
graph LR
    subgraph "Ingestion Pipeline"
        SRC[Source Documents<br/>DOCX/PDF]
        PARSE[Parser<br/>구조 추출]
        CHUNK[Chunker<br/>조항 분할]
        EMBED[Embedder<br/>벡터 생성]
        INDEX[Indexer<br/>FAISS+Whoosh]
    end

    SRC -->|파싱| PARSE
    PARSE -->|청킹| CHUNK
    CHUNK -->|임베딩| EMBED
    EMBED -->|인덱싱| INDEX

    PARSE -->|JSON| EXTRACTED[extracted_documents/]
    CHUNK -->|JSONL| CHUNKED[chunked_documents/]
    INDEX -->|Index Files| INDEXES[search_indexes/]

    style SRC fill:#e3f2fd
    style PARSE fill:#f3e5f5
    style CHUNK fill:#e8f5e9
    style EMBED fill:#fff9c4
    style INDEX fill:#ffe0b2
```

## 사용자 계약서 처리 플로우

```mermaid
sequenceDiagram
    participant User
    participant UI as Streamlit UI
    participant API as FastAPI
    participant Redis
    participant Class as Classification Agent
    participant Consist as Consistency Agent
    participant Report as Report Agent
    participant DB as Database
    participant Azure as Azure OpenAI

    User->>UI: 계약서 업로드 (DOCX)
    UI->>API: POST /upload
    API->>API: DOCX 파싱
    API->>API: 임베딩 생성
    API->>DB: 계약서 저장
    API->>Redis: 분류 작업 큐잉
    API-->>UI: 업로드 완료 (contract_id)

    Redis->>Class: 분류 작업 시작
    Class->>Class: 하이브리드 검색 (FAISS+Whoosh)
    Class->>Azure: LLM 분류 요청
    Azure-->>Class: 분류 결과
    Class->>DB: 분류 결과 저장
    Class-->>Redis: 작업 완료

    UI->>API: GET /api/classification/{id}
    API->>DB: 분류 결과 조회
    API-->>UI: 분류 결과 표시

    User->>UI: 분류 확인
    UI->>API: POST /api/classification/{id}/confirm
    API->>Redis: 검증 작업 큐잉
    API-->>UI: 검증 시작

    Redis->>Consist: 검증 작업 시작
    
    Note over Consist: A1 Stage 1: 조항 매칭
    Consist->>Consist: 하이브리드 검색
    Consist->>Azure: LLM 매칭 검증
    
    par 병렬 처리
        Note over Consist: A1 Stage 2: 누락 검증
        Consist->>Azure: 누락 조항 분석
    and
        Note over Consist: A2: 체크리스트 검증
        Consist->>Azure: 체크리스트 검증
    and
        Note over Consist: A3: 내용 분석
        Consist->>Azure: 내용 비교
    end
    
    Consist->>DB: 검증 결과 저장
    Consist->>Redis: 보고서 작업 큐잉
    Consist-->>Redis: 검증 완료

    Redis->>Report: 보고서 생성 시작
    Report->>DB: 검증 결과 조회
    Report->>Report: Step1: 정규화
    Report->>Report: Step2: 집계
    Report->>Report: Step3: 해결
    Report->>Azure: Step4: 보고서 생성
    Report->>Report: Step5: 최종 통합
    Report->>DB: 보고서 저장
    Report-->>Redis: 보고서 완료

    UI->>API: GET /api/validation/{id}
    API->>DB: 보고서 조회
    API-->>UI: 보고서 표시
    UI-->>User: 분석 결과 확인
```

## Consistency Agent 상세 아키텍처

### 전체 플로우

```mermaid
graph TB
    START[검증 시작]
    
    subgraph A1_STAGE1["A1 Node - Stage 1: 조항 매칭"]
        A1S1_INPUT[사용자 계약서 조항]
        A1S1_SEARCH[하이브리드 검색<br/>FAISS + Whoosh]
        A1S1_MATCH[조항 매칭<br/>Article Matcher]
        A1S1_VERIFY[LLM 매칭 검증<br/>Matching Verifier]
        A1S1_OUTPUT[매칭 결과<br/>matched_articles]
    end
    
    subgraph PARALLEL["병렬 처리"]
        subgraph A1_STAGE2["A1 Node - Stage 2: 누락 검증"]
            A1S2_INPUT[매칭 결과]
            A1S2_MISSING[누락 조항 식별]
            A1S2_LLM[LLM 누락 분석]
            A1S2_OUTPUT[누락 결과<br/>missing_articles]
        end
        
        subgraph A2_NODE["A2 Node: 체크리스트 검증"]
            A2_LOAD[체크리스트 로드]
            A2_VERIFY[LLM 체크리스트 검증]
            A2_OUTPUT[체크리스트 결과<br/>checklist_results]
        end
        
        subgraph A3_NODE["A3 Node: 내용 분석"]
            A3_COMPARE[조항별 내용 비교<br/>LLM]
            A3_OUTPUT[내용 분석 결과<br/>content_analysis]
        end
    end
    
    MERGE[결과 통합]
    END[검증 완료]
    
    START --> A1S1_INPUT
    A1S1_INPUT --> A1S1_SEARCH
    A1S1_SEARCH --> A1S1_MATCH
    A1S1_MATCH --> A1S1_VERIFY
    A1S1_VERIFY --> A1S1_OUTPUT
    
    A1S1_OUTPUT --> A1S2_INPUT
    A1S1_OUTPUT --> A2_LOAD
    A1S1_OUTPUT --> A3_COMPARE
    
    A1S2_INPUT --> A1S2_MISSING
    A1S2_MISSING --> A1S2_LLM
    A1S2_LLM --> A1S2_OUTPUT
    
    A2_LOAD --> A2_VERIFY
    A2_VERIFY --> A2_OUTPUT
    
    A3_COMPARE --> A3_OUTPUT
    
    A1S2_OUTPUT --> MERGE
    A2_OUTPUT --> MERGE
    A3_OUTPUT --> MERGE
    
    MERGE --> END

    style START fill:#e1f5ff
    style A1S1_SEARCH fill:#f3e5f5
    style A1S1_VERIFY fill:#fff9c4
    style A1S2_LLM fill:#fff9c4
    style A2_VERIFY fill:#fff9c4
    style A3_COMPARE fill:#ffe0b2
    style MERGE fill:#c8e6c9
    style END fill:#c8e6c9
```

### A1 Node 상세 구조

```mermaid
graph LR
    subgraph "A1 Stage 1: 조항 매칭"
        INPUT1[사용자 조항]
        
        subgraph "Article Matcher"
            EMBED1[조항 임베딩]
            HYBRID1[하이브리드 검색<br/>Top-K 후보]
            SCORE1[유사도 점수 계산]
        end
        
        subgraph "Matching Verifier"
            LLM1[LLM 매칭 검증<br/>GPT-4]
            FILTER1[신뢰도 필터링]
        end
        
        OUTPUT1[매칭된 조항 쌍]
    end
    
    subgraph "A1 Stage 2: 누락 검증"
        INPUT2[표준계약서 조항 목록]
        COMPARE2[매칭 결과와 비교]
        MISSING2[누락 조항 추출]
        LLM2[LLM 누락 분석<br/>GPT-4]
        OUTPUT2[누락 조항 + 이유]
    end
    
    INPUT1 --> EMBED1
    EMBED1 --> HYBRID1
    HYBRID1 --> SCORE1
    SCORE1 --> LLM1
    LLM1 --> FILTER1
    FILTER1 --> OUTPUT1
    
    OUTPUT1 --> INPUT2
    INPUT2 --> COMPARE2
    COMPARE2 --> MISSING2
    MISSING2 --> LLM2
    LLM2 --> OUTPUT2

    style HYBRID1 fill:#f3e5f5
    style LLM1 fill:#fff9c4
    style LLM2 fill:#fff9c4
    style OUTPUT1 fill:#e8f5e9
    style OUTPUT2 fill:#e8f5e9
```

### A2 Node 상세 구조

```mermaid
graph LR
    INPUT[계약 유형]
    LOAD[활용안내서에서<br/>체크리스트 로드]
    PARSE[체크리스트 파싱]
    ITERATE[각 체크 항목 순회]
    EXTRACT[관련 조항 추출]
    LLM[LLM 검증<br/>GPT-4]
    AGGREGATE[결과 집계]
    OUTPUT[체크리스트 결과<br/>pass/fail/partial]
    
    INPUT --> LOAD
    LOAD --> PARSE
    PARSE --> ITERATE
    ITERATE --> EXTRACT
    EXTRACT --> LLM
    LLM --> AGGREGATE
    AGGREGATE --> OUTPUT

    style INPUT fill:#e1f5ff
    style LOAD fill:#f3e5f5
    style LLM fill:#fff9c4
    style OUTPUT fill:#e8f5e9
```

### A3 Node 상세 구조

```mermaid
graph LR
    INPUT[매칭된 조항 쌍]
    ITERATE[각 조항 쌍 순회]
    CONTEXT[표준계약서 맥락 로드]
    
    LLM[LLM 내용 비교<br/>GPT-4<br/>JSON 출력]
    
    OUTPUT[조항별 분석 결과<br/>missing_items<br/>insufficient_items<br/>analysis<br/>severity]
    
    INPUT --> ITERATE
    ITERATE --> CONTEXT
    CONTEXT --> LLM
    LLM --> OUTPUT

    style INPUT fill:#e1f5ff
    style LLM fill:#fff9c4
    style OUTPUT fill:#e8f5e9
```

### 하이브리드 검색 구조

```mermaid
graph TB
    subgraph "Hybrid Searcher"
        QUERY[검색 쿼리<br/>사용자 조항]
        
        subgraph "Vector Search"
            FAISS_EMBED[쿼리 임베딩]
            FAISS_SEARCH[FAISS 검색]
            FAISS_RESULT[시멘틱 유사 조항<br/>Top-K]
        end
        
        subgraph "Keyword Search"
            WHOOSH_PARSE[키워드 추출]
            WHOOSH_SEARCH[Whoosh 검색<br/>BM25]
            WHOOSH_RESULT[키워드 매칭 조항<br/>Top-K]
        end
        
        MERGE[결과 병합<br/>RRF 알고리즘]
        RERANK[재순위화]
        OUTPUT[최종 Top-K 후보]
    end
    
    QUERY --> FAISS_EMBED
    QUERY --> WHOOSH_PARSE
    
    FAISS_EMBED --> FAISS_SEARCH
    FAISS_SEARCH --> FAISS_RESULT
    
    WHOOSH_PARSE --> WHOOSH_SEARCH
    WHOOSH_SEARCH --> WHOOSH_RESULT
    
    FAISS_RESULT --> MERGE
    WHOOSH_RESULT --> MERGE
    
    MERGE --> RERANK
    RERANK --> OUTPUT

    style FAISS_SEARCH fill:#fff9c4
    style WHOOSH_SEARCH fill:#ffe0b2
    style MERGE fill:#e8f5e9
    style OUTPUT fill:#c8e6c9
```

## Report Agent 처리 단계

```mermaid
graph LR
    subgraph "Report Agent Pipeline"
        INPUT[검증 결과<br/>A1, A2, A3]
        
        STEP1[Step 1: Normalizer<br/>데이터 정규화]
        STEP2[Step 2: Aggregator<br/>결과 집계]
        STEP3[Step 3: Resolver<br/>충돌 해결]
        STEP4[Step 4: Reporter<br/>보고서 생성 LLM]
        STEP5[Step 5: Final Integrator<br/>최종 통합]
        
        OUTPUT[최종 보고서<br/>JSON]
    end

    INPUT --> STEP1
    STEP1 --> STEP2
    STEP2 --> STEP3
    STEP3 --> STEP4
    STEP4 --> STEP5
    STEP5 --> OUTPUT

    style INPUT fill:#e3f2fd
    style STEP1 fill:#f3e5f5
    style STEP2 fill:#e8f5e9
    style STEP3 fill:#fff9c4
    style STEP4 fill:#ffe0b2
    style STEP5 fill:#ffccbc
    style OUTPUT fill:#c8e6c9
```

## 지식베이스 구조

```mermaid
graph TB
    subgraph "Knowledge Base"
        subgraph "표준계약서 (5종)"
            STD1[제공형 표준계약서]
            STD2[창출형 표준계약서]
            STD3[가공형 표준계약서]
            STD4[중개거래형 제공자 표준계약서]
            STD5[중개거래형 이용자 표준계약서]
        end
        
        subgraph "활용안내서"
            GUD1[제공형 활용안내서]
            GUD2[창출형 활용안내서]
            GUD3[가공형 활용안내서]
            GUD4[중개거래형 제공자 활용안내서]
            GUD5[중개거래형 이용자 활용안내서]
        end
        
        subgraph "처리된 데이터"
            CHUNKS[Chunked Documents<br/>조항별 분할]
            EMBED[Embeddings<br/>벡터 표현]
            FAISS_IDX[FAISS Index<br/>시멘틱 검색]
            WHOOSH_IDX[Whoosh Index<br/>키워드 검색]
        end
    end

    STD1 & STD2 & STD3 & STD4 & STD5 -->|파싱+청킹| CHUNKS
    GUD1 & GUD2 & GUD3 & GUD4 & GUD5 -->|파싱+청킹| CHUNKS
    
    CHUNKS -->|임베딩| EMBED
    EMBED -->|인덱싱| FAISS_IDX
    CHUNKS -->|인덱싱| WHOOSH_IDX

    style STD1 fill:#e3f2fd
    style STD2 fill:#e3f2fd
    style STD3 fill:#e3f2fd
    style STD4 fill:#e3f2fd
    style STD5 fill:#e3f2fd
    style GUD1 fill:#f3e5f5
    style GUD2 fill:#f3e5f5
    style GUD3 fill:#f3e5f5
    style GUD4 fill:#f3e5f5
    style GUD5 fill:#f3e5f5
    style FAISS_IDX fill:#fff9c4
    style WHOOSH_IDX fill:#ffe0b2
```

## Docker 컨테이너 구성

```mermaid
graph TB
    subgraph "Docker Compose Services"
        subgraph "Core Services"
            REDIS_C[redis<br/>포트: 6379]
            API_C[fast-api<br/>포트: 8000]
            UI_C[streamlit<br/>포트: 8501]
        end
        
        subgraph "Worker Services"
            CLASS_C[classification-worker<br/>큐: classification]
            CONSIST_C[consistency-worker<br/>큐: consistency_validation]
            REPORT_C[report-worker<br/>큐: report_generation]
            CHATBOT_C[chatbot-worker<br/>큐: chatbot]
        end
        
        subgraph "Utility Services"
            INGEST_C[ingestion<br/>프로필: ingestion]
        end
        
        VOL[Shared Volumes<br/>data/, .env]
    end

    API_C --> REDIS_C
    UI_C --> API_C
    CLASS_C --> REDIS_C
    CONSIST_C --> REDIS_C
    REPORT_C --> REDIS_C
    CHATBOT_C --> REDIS_C
    
    API_C -.->|mount| VOL
    CLASS_C -.->|mount| VOL
    CONSIST_C -.->|mount| VOL
    REPORT_C -.->|mount| VOL
    CHATBOT_C -.->|mount| VOL
    INGEST_C -.->|mount| VOL

    style REDIS_C fill:#ffe1e1
    style API_C fill:#fff4e1
    style UI_C fill:#e1f5ff
    style CLASS_C fill:#e8f5e9
    style CONSIST_C fill:#e8f5e9
    style REPORT_C fill:#e8f5e9
    style CHATBOT_C fill:#e8f5e9
    style INGEST_C fill:#f3e5f5
```

## 기술 스택 레이어

```mermaid
graph TB
    subgraph "Technology Stack"
        subgraph "Presentation Layer"
            STREAMLIT[Streamlit<br/>Python Web UI]
        end
        
        subgraph "API Layer"
            FASTAPI[FastAPI<br/>REST API]
            UVICORN[Uvicorn<br/>ASGI Server]
        end
        
        subgraph "Business Logic Layer"
            AGENTS[Agent Services<br/>Classification, Consistency, Report]
            CELERY[Celery<br/>Task Queue]
        end
        
        subgraph "Data Layer"
            SQLALCHEMY[SQLAlchemy<br/>ORM]
            SQLITE[SQLite<br/>Database]
        end
        
        subgraph "Search Layer"
            FAISS_LIB[FAISS<br/>Vector Search]
            WHOOSH_LIB[Whoosh<br/>Full-text Search]
        end
        
        subgraph "AI Layer"
            AZURE_AI[Azure OpenAI<br/>GPT-4, Embeddings]
        end
        
        subgraph "Infrastructure Layer"
            DOCKER[Docker<br/>Containerization]
            REDIS_INFRA[Redis<br/>Message Broker]
        end
    end

    STREAMLIT --> FASTAPI
    FASTAPI --> UVICORN
    FASTAPI --> AGENTS
    AGENTS --> CELERY
    CELERY --> REDIS_INFRA
    AGENTS --> SQLALCHEMY
    SQLALCHEMY --> SQLITE
    AGENTS --> FAISS_LIB
    AGENTS --> WHOOSH_LIB
    AGENTS --> AZURE_AI
    
    DOCKER -.->|orchestrates| STREAMLIT
    DOCKER -.->|orchestrates| FASTAPI
    DOCKER -.->|orchestrates| AGENTS
    DOCKER -.->|orchestrates| REDIS_INFRA

    style STREAMLIT fill:#e1f5ff
    style FASTAPI fill:#fff4e1
    style AGENTS fill:#e8f5e9
    style AZURE_AI fill:#fff9c4
    style DOCKER fill:#f3e5f5
```
