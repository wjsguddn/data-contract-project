# 시스템 아키텍처

> **최종 업데이트**: 2025-11-03
> **분석 기준**: 실제 코드베이스 검증 (문서 아님)

본 문서는 데이터 계약서 검증 시스템의 전체 아키텍처를 설명합니다.

## 목차
1. [시스템 개요](#시스템-개요)
2. [전체 아키텍처](#전체-아키텍처)
3. [컨테이너 구성](#컨테이너-구성)
4. [데이터 흐름](#데이터-흐름)
5. [검색 아키텍처](#검색-아키텍처)
6. [데이터 저장소](#데이터-저장소)
7. [AI/ML 통합](#aiml-통합)

---

## 시스템 개요

**프로젝트명**: 데이터 계약서 검증 플랫폼
**목적**: 사용자 계약서를 5개 표준 계약서 유형으로 자동 분류하고, RAG 기반 하이브리드 검색으로 일관성을 검증
**기술 스택**: FastAPI, Streamlit, Celery, Redis, SQLite, FAISS, Whoosh, Azure OpenAI
**아키텍처 패턴**: 마이크로서비스 + 비동기 태스크 처리 + RAG (Retrieval-Augmented Generation)

---

## 전체 아키텍처

```mermaid
graph TB
    subgraph "클라이언트"
        UI[Streamlit Frontend<br/>파일 업로드, 결과 표시]
    end

    subgraph "Docker Compose 환경"
        subgraph "API Layer"
            API[FastAPI Backend<br/>:8000<br/>REST API 서버]
        end

        subgraph "Task Queue"
            Redis[Redis<br/>:6379<br/>Broker & Result Backend]
        end

        subgraph "Celery Workers"
            CW1[Classification Worker<br/>Queue: classification<br/>계약서 분류]
            CW2[Consistency Worker<br/>Queue: consistency_validation<br/>일관성 검증 A1, A2, A3]
            CW3[Report Worker<br/>Queue: report<br/>보고서 생성 stub]
        end

        subgraph "데이터 저장소"
            DB[(SQLite Database<br/>contracts.db<br/>5개 테이블)]
            FS[File Storage<br/>data/<br/>파싱 결과, 사용자 계약서]
        end

        subgraph "검색 엔진"
            FAISS[FAISS Vector Indexes<br/>search_indexes/faiss/<br/>10개 인덱스<br/>text + title 이중화]
            Whoosh[Whoosh Keyword Indexes<br/>search_indexes/whoosh/<br/>5개 인덱스<br/>한국어 형태소 분석]
        end
    end

    subgraph "외부 서비스"
        Azure[Azure OpenAI<br/>GPT-4o<br/>text-embedding-3-large]
    end

    subgraph "지식 베이스 구축 CLI"
        Ingestion[Ingestion CLI<br/>docker-compose --profile ingestion<br/>파싱, 청킹, 임베딩, 인덱싱]
    end

    %% 사용자 플로우
    UI -->|HTTP POST /upload| API
    UI -->|HTTP GET /api/classification/:id| API
    UI -->|HTTP POST /api/validation/:id/start| API
    API -->|응답| UI

    %% 백엔드 → 큐
    API -->|Celery Task 발행| Redis
    Redis -->|Task 배포| CW1
    Redis -->|Task 배포| CW2
    Redis -->|Task 배포| CW3

    %% 워커 → DB/파일
    CW1 <-->|Read/Write| DB
    CW2 <-->|Read/Write| DB
    CW3 <-->|Read/Write| DB
    API <-->|SQLAlchemy ORM| DB
    API -->|파싱 결과 저장| FS

    %% 워커 → 검색
    CW1 -->|임베딩 유사도 검색| FAISS
    CW2 -->|하이브리드 검색| FAISS
    CW2 -->|하이브리드 검색| Whoosh

    %% AI 서비스 호출
    API -->|임베딩 생성| Azure
    CW1 -->|LLM 분류 Few-shot| Azure
    CW2 -->|LLM 검증/분석| Azure

    %% 지식 베이스 구축
    Ingestion -->|표준 계약서 파싱| FS
    Ingestion -->|임베딩 생성| Azure
    Ingestion -->|인덱스 생성| FAISS
    Ingestion -->|인덱스 생성| Whoosh

    %% 스타일링
    classDef frontend fill:#e1f5ff,stroke:#01579b,stroke-width:2px
    classDef backend fill:#fff9c4,stroke:#f57f17,stroke-width:2px
    classDef worker fill:#f3e5f5,stroke:#4a148c,stroke-width:2px
    classDef storage fill:#e8f5e9,stroke:#1b5e20,stroke-width:2px
    classDef external fill:#ffebee,stroke:#b71c1c,stroke-width:2px
    classDef queue fill:#fff3e0,stroke:#e65100,stroke-width:2px

    class UI frontend
    class API backend
    class CW1,CW2,CW3 worker
    class DB,FS,FAISS,Whoosh storage
    class Azure external
    class Redis queue
    class Ingestion backend
```

---

## 컨테이너 구성

### Docker Compose Services

| 서비스명 | 이미지 | 포트 | 역할 | 의존성 | 상태 |
|---------|-------|-----|-----|--------|------|
| **fast-api** | Dockerfile.backend | 8000 | FastAPI REST API 서버 | redis | ✅ 실행 중 |
| **classification-worker** | Dockerfile.classification | - | 계약서 분류 Celery Worker | redis | ✅ 실행 중 |
| **consistency-validation-worker** | Dockerfile.consistency | - | 일관성 검증 Celery Worker | redis | ✅ 실행 중 |
| **report-worker** | Dockerfile.report | - | 보고서 생성 Celery Worker | redis | ⚠️ Stub |
| **redis** | redis:7-alpine | 6379 | Celery Broker/Backend | - | ✅ 실행 중 |
| **ingestion** | Dockerfile.ingestion | - | 지식 베이스 구축 CLI | - | 🔧 Profile 서비스 |

**참고**:
- Streamlit Frontend는 Docker Compose에 포함되지 않음 (별도 실행)
- Ingestion은 `--profile ingestion` 플래그로 수동 실행

### 볼륨 공유

```yaml
volumes:
  - ./data:/app/data                          # 파싱 결과, DB, 사용자 계약서
  - ./search_indexes:/app/search_indexes      # FAISS, Whoosh 인덱스
  - ./backend:/app/backend                    # 코드 핫 리로드 (개발)
  - ./ingestion:/app/ingestion                # 지식 베이스 구축 코드
  - redis_data:/data                          # Redis 영속화
```

---

## 데이터 흐름

### 1. 사용자 계약서 처리 플로우

```mermaid
sequenceDiagram
    actor User
    participant UI as Streamlit
    participant API as FastAPI
    participant Redis as Redis Queue
    participant CW1 as Classification<br/>Worker
    participant CW2 as Consistency<br/>Worker
    participant DB as SQLite
    participant Search as FAISS + Whoosh
    participant LLM as Azure OpenAI

    %% 업로드 단계
    User->>UI: 1. DOCX 파일 업로드
    UI->>API: POST /upload (multipart)
    API->>API: UserContractParser 파싱
    API->>LLM: 임베딩 생성 (각 조문)
    API->>DB: ContractDocument 저장<br/>(parsed_data + embeddings)
    API->>Redis: classify_contract_task 발행
    API-->>UI: contract_id 반환

    %% 분류 단계
    Redis->>CW1: Task 배포
    CW1->>DB: 계약서 조회
    CW1->>Search: 5개 표준계약서 유사도 계산
    alt Gap >= 0.05 (명확한 경우)
        CW1->>CW1: 임베딩 결과 사용 (LLM 생략)
    else Gap < 0.05 (애매한 경우)
        CW1->>LLM: Few-shot 분류 (5개 예제)
    end
    CW1->>DB: ClassificationResult 저장

    UI->>API: 2. 폴링: GET /api/classification/:id
    API-->>UI: 분류 결과 (5개 유형 점수)

    User->>UI: 3. 분류 확인/수정
    UI->>API: POST /api/classification/:id/confirm

    %% 검증 단계
    User->>UI: 4. "계약서 검증" 버튼 클릭
    UI->>API: POST /api/validation/:id/start<br/>(text_weight, title_weight, dense_weight)
    API->>Redis: validate_contract_task 발행
    API-->>UI: task_id 반환

    %% A1: 완전성 검사
    Redis->>CW2: Task 배포
    Note over CW2: A1 Node: Completeness Check
    CW2->>DB: 표준 계약서 청크 조회
    loop 각 사용자 조문
        CW2->>Search: 하이브리드 검색 (FAISS + Whoosh)
        CW2->>CW2: 조문 단위 점수 집계
    end
    CW2->>CW2: 누락된 표준 조문 식별
    CW2->>LLM: 누락 조문 재검증 (거짓 양성 제거)
    CW2->>DB: ValidationResult.completeness_check 저장

    %% A2: 체크리스트 검증
    Note over CW2: A2 Node: Checklist Check
    CW2->>CW2: 매칭된 조문별 체크리스트 로드
    loop 각 체크리스트 항목
        CW2->>LLM: 자동 검증 (YES/NO/UNCLEAR/MANUAL)
    end
    CW2->>DB: ValidationResult.checklist_validation 저장

    %% A3: 내용 분석
    Note over CW2: A3 Node: Content Analysis
    loop 각 매칭된 조문
        CW2->>Search: 표준 내용 검색 (세부 항목 단위)
        CW2->>LLM: 내용 비교 및 개선안 생성
    end
    CW2->>DB: ValidationResult.content_analysis 저장

    UI->>API: 5. 폴링: GET /api/validation/:id
    API-->>UI: 검증 결과 (A1+A2+A3)
    UI->>User: 6. 결과 시각화<br/>(매칭, 체크리스트, 분석, 제안)
```

### 2. 지식 베이스 구축 플로우

```mermaid
graph LR
    A[표준 계약서 PDF/DOCX<br/>5개 파일] --> B[Parsing<br/>조문 구조 추출]
    B --> C[Chunking<br/>조문 단위 청킹]
    C --> D[Embedding<br/>Azure OpenAI<br/>text-embedding-3-large]
    D --> E1[FAISS 인덱싱<br/>text_norm + title<br/>이중 인덱스]
    D --> E2[Whoosh 인덱싱<br/>BM25 + Mecab<br/>한국어 형태소 분석]

    style A fill:#ffccbc
    style B fill:#fff9c4
    style C fill:#c5e1a5
    style D fill:#b3e5fc
    style E1 fill:#e1bee7
    style E2 fill:#f8bbd0
```

**실행 명령**:
```bash
docker-compose --profile ingestion run --rm ingestion run --mode full --file all
```

---

## 검색 아키텍처

### 하이브리드 검색 구조

```mermaid
graph TB
    subgraph "Query Input"
        Q[검색 쿼리<br/>text: 조문 내용<br/>title: 조문 제목]
    end

    subgraph "Dual Vector Search FAISS"
        E[Embedding Generator<br/>Azure OpenAI]
        F1[Text Index<br/>text_norm embedding<br/>~400 chunks]
        F2[Title Index<br/>title embedding<br/>~400 chunks]
        E --> F1
        E --> F2
        F1 --> DS1[Top 50<br/>text score]
        F2 --> DS2[Top 50<br/>title score]
    end

    subgraph "Keyword Search Whoosh"
        W1[BM25 Scorer<br/>Mecab Tokenizer]
        W1 --> WS1[Top 50<br/>text score]
        W1 --> WS2[Top 50<br/>title score]
    end

    subgraph "Score Fusion"
        N1[Min-Max Normalization]
        N2[Weighted Fusion]
        DS1 --> N1
        DS2 --> N1
        WS1 --> N1
        WS2 --> N1
        N1 --> N2
    end

    subgraph "Final Ranking"
        R[Top K Results<br/>global_id, score, reasoning]
    end

    Q --> E
    Q --> W1
    N2 --> R

    style Q fill:#e3f2fd
    style E fill:#fff9c4
    style F1 fill:#f3e5f5
    style F2 fill:#f3e5f5
    style W1 fill:#fce4ec
    style N2 fill:#c8e6c9
    style R fill:#ffccbc
```

### 가중치 구조

| 레벨 | 파라미터 | 기본값 | 설명 |
|-----|----------|--------|------|
| **필드 가중치** | text_weight | 0.7 | 조문 내용 중요도 |
| | title_weight | 0.3 | 조문 제목 중요도 |
| **검색 방식 가중치** | dense_weight | 0.85 | 벡터 검색 비중 |
| | sparse_weight | 0.15 | 키워드 검색 비중 |

**수식**:
```
final_score = (text_score * 0.7 + title_score * 0.3) * 0.85(dense) +
              (text_score * 0.7 + title_score * 0.3) * 0.15(sparse)
```

**적응형 가중치**:
- Sparse 검색 결과가 없으면 → Dense 가중치 1.0으로 자동 조정 (0.85 제한 해제)

---

## 데이터 저장소

### 1. SQLite Database 스키마

```mermaid
erDiagram
    ContractDocument ||--o{ ClassificationResult : "has"
    ContractDocument ||--o{ ValidationResult : "has"
    ContractDocument ||--o{ Report : "has"
    ContractDocument ||--o{ TokenUsage : "tracks"

    ContractDocument {
        string contract_id PK
        string filename
        string file_path
        datetime upload_date
        json parsed_data "구조화된 조문 + 임베딩"
        json parsed_metadata "파싱 통계"
        string status "uploaded|parsing|parsed|classifying|classified|validating|validated|error"
    }

    ClassificationResult {
        int id PK
        string contract_id FK
        string predicted_type "provide|create|process|brokerage_provider|brokerage_user"
        float confidence
        json scores "5개 유형별 점수"
        string confirmed_type "사용자 확인/수정"
        boolean user_override
        string reasoning
        datetime created_at
    }

    ValidationResult {
        int id PK
        string contract_id FK
        string contract_type
        json completeness_check "A1 매칭 결과"
        json checklist_validation "A2 체크리스트 결과"
        json content_analysis "A3 내용 분석"
        float overall_score
        json recommendations
        datetime created_at
    }

    Report {
        int id PK
        string contract_id FK
        string contract_type
        text overall_assessment
        json issues
        json positive_points
        json recommendations
        datetime created_at
    }

    TokenUsage {
        int id PK
        string contract_id FK
        string component "classification_agent|consistency_agent"
        string api_type "chat_completion|embedding"
        string model
        int prompt_tokens
        int completion_tokens
        int total_tokens
        json extra_info
        datetime timestamp
    }
```

### 2. 파일 시스템 구조

```
c:\Python Projects\data-contract-project\
├── data/
│   ├── database/
│   │   └── contracts.db                              # SQLite DB
│   ├── source_documents/                             # 표준 계약서 원본 (5개)
│   │   ├── provide_std_contract.pdf
│   │   ├── create_std_contract.pdf
│   │   ├── process_std_contract.pdf
│   │   ├── brokerage_provider_std_contract.pdf
│   │   └── brokerage_user_std_contract.pdf
│   ├── extracted_documents/                          # 파싱된 JSON (5개)
│   │   └── {type}_std_contract_structured.json      # 조문 구조
│   ├── chunked_documents/                            # 청크 JSON (5개)
│   │   └── {type}_std_contract_chunks.json          # ~80-100 조문/청크
│   ├── parsed_user_contracts/                        # 사용자 계약서 (디버깅용)
│   │   └── {filename}_{contract_id}.json
│   └── sample_user_contracts/                        # 테스트 파일
│
└── search_indexes/
    ├── faiss/                                        # 벡터 인덱스 (10개)
    │   ├── provide_std_contract_text.faiss          # 내용 인덱스
    │   ├── provide_std_contract_title.faiss         # 제목 인덱스
    │   ├── create_std_contract_text.faiss
    │   ├── create_std_contract_title.faiss
    │   ├── process_std_contract_text.faiss
    │   ├── process_std_contract_title.faiss
    │   ├── brokerage_provider_std_contract_text.faiss
    │   ├── brokerage_provider_std_contract_title.faiss
    │   ├── brokerage_user_std_contract_text.faiss
    │   └── brokerage_user_std_contract_title.faiss
    │
    └── whoosh/                                       # 키워드 인덱스 (5개)
        ├── provide_std_contract/
        │   ├── _MAIN_*.toc
        │   └── _MAIN_*.seg
        ├── create_std_contract/
        ├── process_std_contract/
        ├── brokerage_provider_std_contract/
        └── brokerage_user_std_contract/
```

### 3. 청크 데이터 구조

```json
{
  "id": "chunk_001",
  "global_id": "urn:contract:provide:article:1",
  "unit_type": "article",
  "parent_id": null,
  "title": "제1조(목적)",
  "text_raw": "이 계약은 데이터 제공에 관한...",
  "text_norm": "계약 데이터 제공 ...",
  "source_file": "provide_std_contract",
  "order_index": 1,
  "embeddings": {
    "title": [0.012, -0.045, ...],      // 3072 dim
    "text_norm": [0.023, -0.012, ...]   // 3072 dim
  }
}
```

---

## AI/ML 통합

### Azure OpenAI 사용 현황

```mermaid
graph TB
    subgraph "Embedding API"
        E1[사용자 계약서 업로드<br/>FastAPI /upload]
        E2[지식 베이스 구축<br/>Ingestion CLI]
        E3[A3 내용 검색<br/>Consistency Worker]
    end

    subgraph "Chat Completion API"
        C1[분류 Few-shot<br/>Classification Worker<br/>Gap < 0.05 시에만]
        C2[A1 누락 조문 재검증<br/>MatchingVerifier]
        C3[A2 체크리스트 검증<br/>ChecklistVerifier]
        C4[A3 내용 비교<br/>ContentComparator]
    end

    subgraph "Azure OpenAI"
        Azure[text-embedding-3-large<br/>3072 dim<br/>---<br/>gpt-4o<br/>JSON mode]
    end

    E1 --> Azure
    E2 --> Azure
    E3 --> Azure
    C1 --> Azure
    C2 --> Azure
    C3 --> Azure
    C4 --> Azure

    style E1 fill:#b3e5fc
    style E2 fill:#b3e5fc
    style E3 fill:#b3e5fc
    style C1 fill:#ffccbc
    style C2 fill:#ffccbc
    style C3 fill:#ffccbc
    style C4 fill:#ffccbc
    style Azure fill:#ffebee
```

### LLM 호출 최적화

| 단계 | 최적화 기법 | 효과 |
|-----|-----------|------|
| **분류** | Hybrid Gating | LLM 호출 ~60% 감소 |
| **업로드** | 임베딩 캐싱 | 재업로드 시 임베딩 재사용 |
| **검증** | Sparse 실패 시 Dense 100% | Whoosh 오류 시 벡터 검색만 사용 |
| **토큰 추적** | TokenUsage 테이블 | 비용 모니터링 및 분석 |

### 토큰 사용량 추적

```python
# backend/shared/services/embedding_generator.py
def log_token_usage(contract_id, component, api_type, model, tokens):
    """
    component: classification_agent | consistency_agent
    api_type: chat_completion | embedding
    """
    TokenUsage.create(
        contract_id=contract_id,
        component=component,
        api_type=api_type,
        model=model,
        prompt_tokens=tokens["prompt_tokens"],
        completion_tokens=tokens["completion_tokens"],
        total_tokens=tokens["total_tokens"]
    )
```

**재시도 로직**: SQLite 락 발생 시 3회 재시도 (지수 백오프)

---

## 주요 기술적 특징

### 1. 이중 벡터 인덱스 (Dual Vector Index)

- **기존 문제**: 제목과 내용을 하나의 임베딩으로 합치면 정보 손실
- **해결책**: 제목과 내용을 별도 인덱스로 분리
- **효과**: 제목 기반 매칭 정확도 향상 (특히 짧은 조문)

### 2. Hybrid Gating (분류 에이전트)

- **기존 문제**: 모든 분류에 LLM 사용 시 비용 과다
- **해결책**:
  - Gap >= 0.05: 임베딩 결과만 사용 (빠름, 저렴)
  - Gap < 0.05: LLM Few-shot 호출 (정확, 비쌈)
- **효과**: 비용 60% 절감, 응답 속도 향상

### 3. 적응형 하이브리드 검색

- **기존 문제**: Whoosh 인덱스 오류 시 전체 검색 실패
- **해결책**: Sparse 결과 없으면 Dense 가중치 1.0으로 자동 전환
- **효과**: 시스템 안정성 향상

### 4. 한국어 형태소 분석 (Mecab)

- **기존 문제**: 영어 토크나이저로는 한국어 의미 추출 불가
- **해결책**: Mecab 형태소 분석기 + 품사 필터링 (명사, 동사, 형용사)
- **효과**: BM25 키워드 검색 정확도 향상

---

## 구현 상태

| 컴포넌트 | 상태 | 비고 |
|---------|------|------|
| FastAPI Backend | ✅ 완료 | 10개 엔드포인트 |
| Streamlit Frontend | ✅ 완료 | 단일 페이지, Docker 미포함 |
| Classification Worker | ✅ 완료 | Hybrid Gating 적용 |
| Consistency Worker | ✅ 완료 | A1, A2, A3 노드 |
| Report Worker | ⚠️ Stub | `{"status": "ok"}` 반환만 |
| 지식 베이스 구축 | ✅ 완료 | 5개 표준 계약서 인덱싱 |
| 하이브리드 검색 | ✅ 완료 | FAISS + Whoosh 이중 인덱스 |
| 토큰 추적 | ✅ 완료 | DB 저장 및 API 조회 |
| 인증/권한 | ❌ 미구현 | 보안 없음 |
| CORS 설정 | ❌ 미구현 | 프론트엔드 통신 제한 가능 |
| Docker Streamlit | ❌ 미구현 | 수동 실행 필요 |

---

## 환경 설정

### 필수 환경 변수

```bash
# Azure OpenAI
AZURE_OPENAI_API_KEY=your_api_key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_GPT_DEPLOYMENT=gpt-4o
AZURE_EMBEDDING_DEPLOYMENT=text-embedding-3-large

# Redis
REDIS_URL=redis://redis:6379

# Database
DATABASE_URL=sqlite:///./data/database/contracts.db
```

### 포트 매핑

- **8000**: FastAPI (http://localhost:8000)
- **6379**: Redis (내부 네트워크만)
- **Streamlit**: Docker Compose에 없음 (별도 실행)

### 실행 명령어

```bash
# 전체 시스템 시작
docker-compose up -d

# 지식 베이스 구축 (최초 1회)
docker-compose --profile ingestion run --rm ingestion run -m full -f all

# Streamlit 실행 (별도 터미널)
cd frontend
streamlit run app.py

# 로그 확인
docker-compose logs -f fast-api
docker-compose logs -f classification-worker
docker-compose logs -f consistency-validation-worker
```

---

## 성능 지표

| 항목 | 값 |
|-----|---|
| 표준 계약서 청크 수 | ~400 (5개 계약서 합계) |
| 검색 응답 시간 | < 500ms |
| 분류 시간 (임베딩만) | ~2초 |
| 분류 시간 (LLM 포함) | ~5초 |
| A1 노드 실행 시간 | ~30초 (50개 조문 가정) |
| A2 노드 실행 시간 | ~20초 (20개 체크리스트 가정) |
| A3 노드 실행 시간 | ~60초 (50개 조문 가정) |
| 전체 검증 시간 | ~2분 |

---

## 참고 문서

- [하이브리드 검색 로직](./HYBRID_SEARCH_LOGIC.md)
- [A1 노드 매칭 플로우](./A1_SEARCH_MATCHING_FLOW.md)
- [프로젝트 상태](../PROJECT_STATUS.md)
- [기술 스택](./.kiro/steering/tech.md)
- [제품 개요](./.kiro/steering/product.md)

---

## 변경 이력

- **2025-11-03**: 초기 작성 (실제 코드베이스 분석 기반)
  - 이중 벡터 인덱스 구조 반영
  - Hybrid Gating 최적화 반영
  - A1/A2/A3 노드 실제 구현 상태 반영
  - Report Worker stub 상태 명시
