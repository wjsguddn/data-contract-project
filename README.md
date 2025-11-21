# 데이터 표준계약 검증 시스템

AI 기반 한국어 데이터 계약서 분석 및 검증 시스템. 5종 표준계약서를 기준으로 사용자 계약서를 자동 분류하고, 3단계 정합성 검증을 수행하며, 자연어 질의응답 챗봇을 제공함.

## 프로젝트 개요

본 시스템은 데이터 거래 계약서의 품질을 자동으로 검증하고 개선 제안을 제공하는 AI 기반 플랫폼. RAG(Retrieval-Augmented Generation) 기술과 하이브리드 검색(FAISS + Whoosh)을 활용하여 계약서를 분석하고, 표준계약서 대비 완전성, 체크리스트 준수, 내용 충실도를 평가함.

### 현재 상태
- **Phase 1 (완료)**: 계약서 분류 시스템
- **Phase 2 (완료)**: 정합성 검증 시스템 (A1, A2, A3 노드)
- **Phase 2 (완료)**: 챗봇 질의응답 시스템
- **Phase 3 (계획)**: 보고서 생성 및 고도화 기능

### 지원 형식
- 구조화된 DOCX 파일 ("제n조" 형식)
- 5종 표준계약서: 제공형, 창출형, 가공형, 중개거래형(제공자), 중개거래형(이용자)

## 주요 기능

### 1. 계약서 업로드 및 분류 (Classification Agent)
- DOCX 형식의 계약서 업로드
- RAG 기반 AI 자동 분류 (5종 표준계약서 유형)
  - 데이터 제공형 표준계약서
  - 데이터 창출형 표준계약서
  - 데이터 가공서비스형 표준계약서
  - 데이터 중개거래형 표준계약서 (제공자-운영자)
  - 데이터 중개거래형 표준계약서 (이용자-운영자)
- 주요 조항 추출 및 하이브리드 검색
- Gating 메커니즘을 통한 LLM 호출 최적화
- 분류 신뢰도 점수 및 사용자 검토 인터페이스

### 2. 정합성 검증 (Consistency Agent)
- **A1 노드 (완전성 검증)**: 
  - 하이브리드 검색 기반 조항 매칭
  - 누락 조항 식별 및 LLM 재검증
  - matched, missing, extra 조항 분류
- **A2 노드 (체크리스트 검증)**: 
  - 활용안내서 기반 체크리스트 검증
  - LLM 기반 YES/NO/UNCLEAR 판단
  - matched 조항만 선택적 처리
- **A3 노드 (내용 분석)**: 
  - 조항별 내용 비교 및 충실도 평가
  - 완전성, 명확성, 실무성 점수 산출
  - 문제점 식별 및 개선 제안 생성
- 병렬 처리 아키텍처 (A1-Stage1 → [A1-Stage2 || A2 || A3])
- 맥락 기반 유연한 검증 (과도한 규격화 방지)
- 토큰 사용량 추적 및 최적화

### 3. 계약서 챗봇 (Chatbot Agent)
- 계약서 내용에 대한 자연어 질의응답
- LangGraph 기반 워크플로우 오케스트레이션
- Function Calling 기반 유기적 도구 선택
  - HybridSearchTool: 하이브리드 검색
  - ArticleIndexTool: 조 번호 검색
  - ArticleTitleTool: 조 제목 검색
  - StandardContractTool: 표준계약서 검색
- 대화 컨텍스트 관리 및 참조 해결
- 스트리밍 응답 지원

## 시스템 요구사항

### 필수 요구사항
- Python 3.9 이상
- Docker 및 Docker Compose
- Azure OpenAI API 자격 증명 (GPT-4o, text-embedding-3-large)

### 환경 변수
```bash
# Azure OpenAI 설정 (필수)
AZURE_OPENAI_API_KEY=your_api_key_here
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_EMBEDDING_DEPLOYMENT=text-embedding-3-large
AZURE_GPT_DEPLOYMENT=gpt-4o

# 데이터베이스
DATABASE_URL=sqlite:///data/database/contracts.db

# Redis (메시지 큐 및 캐싱)
REDIS_URL=redis://redis:6379

# Celery (비동기 작업 처리)
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0
```

## 빠른 시작

### 1. 환경 설정
```bash
# 저장소 클론
git clone <repository-url>
cd <repository-name>

# 환경 변수 설정
cp .env.example .env
# .env 파일을 편집하여 Azure OpenAI 자격 증명 입력
```

### 2. Docker로 전체 시스템 실행
```bash
# 전체 시스템 실행 (권장)
docker-compose -f docker/docker-compose.yml up -d

# 서비스 상태 확인
docker-compose -f docker/docker-compose.yml ps

# 로그 확인
docker-compose -f docker/docker-compose.yml logs -f
```

실행되는 서비스:
- `fast-api`: FastAPI 백엔드 서버 (포트 8000)
- `streamlit`: Streamlit 프론트엔드 (포트 8501)
- `redis`: Redis 메시지 큐 (포트 6379)
- `classification-agent`: 분류 에이전트 (Celery Worker)
- `consistency-agent`: 정합성 검증 에이전트 (Celery Worker)
- `chatbot-agent`: 챗봇 에이전트 (Celery Worker)

### 3. 지식베이스 구축 (최초 1회 필수)
```bash
# 표준계약서 5종 + 활용안내서 인덱싱
docker-compose -f docker/docker-compose.yml --profile ingestion run --rm ingestion

# 또는 직접 실행
python -m ingestion.ingest --mode full --file all
```

이 단계에서 수행되는 작업:
- 표준계약서 5종 파싱 (DOCX → JSON)
- 조 단위 청킹 및 임베딩 생성
- FAISS 벡터 인덱스 생성 (시멘틱 검색)
- Whoosh 키워드 인덱스 생성 (BM25 검색)
- 활용안내서 파싱 및 체크리스트 추출

### 4. 웹 인터페이스 접속
- **Streamlit 프론트엔드**: http://localhost:8501
- **FastAPI 백엔드**: http://localhost:8000
- **API 문서 (Swagger)**: http://localhost:8000/docs
- **API 문서 (ReDoc)**: http://localhost:8000/redoc

### 5. 시스템 종료
```bash
# 전체 시스템 종료
docker-compose -f docker/docker-compose.yml down

# 데이터 포함 완전 삭제
docker-compose -f docker/docker-compose.yml down -v
```

## API 엔드포인트

### 계약서 업로드 및 분류

#### 계약서 업로드
```bash
POST /upload
Content-Type: multipart/form-data
```

**요청**:
- `file`: DOCX 파일 (multipart/form-data)

**응답**:
```json
{
  "contract_id": "550e8400-e29b-41d4-a716-446655440000",
  "filename": "user_contract.docx",
  "status": "uploaded",
  "message": "계약서 업로드 완료. 분류 작업 시작됨"
}
```

#### 분류 결과 조회
```bash
GET /api/classification/{contract_id}
```

**응답**:
```json
{
  "contract_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "classified_type": "provide_std_contract",
  "confidence_score": 0.92,
  "classification_details": {
    "top_matches": [
      {"type": "provide_std_contract", "score": 0.92},
      {"type": "create_std_contract", "score": 0.15}
    ]
  },
  "token_usage": {
    "total_tokens": 1250,
    "prompt_tokens": 980,
    "completion_tokens": 270
  }
}
```

#### 분류 확인/수정
```bash
POST /api/classification/{contract_id}/confirm
Query Parameters:
  - confirmed_type: 확인된 계약서 유형 (provide_std_contract, create_std_contract, process_std_contract, brokerage_provider_std_contract, brokerage_user_std_contract)
```

**응답**:
```json
{
  "contract_id": "550e8400-e29b-41d4-a716-446655440000",
  "confirmed_type": "provide_std_contract",
  "status": "confirmed",
  "message": "분류 확인 완료"
}
```

### 정합성 검증

#### 검증 시작
```bash
POST /api/validation/{contract_id}/start
Query Parameters (선택):
  - text_weight: 본문 가중치 (기본 0.7, 범위 0.0-1.0)
  - title_weight: 제목 가중치 (기본 0.3, 범위 0.0-1.0)
  - dense_weight: 시멘틱 검색 가중치 (기본 0.85, 범위 0.0-1.0)
```

**응답**:
```json
{
  "contract_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "started",
  "message": "정합성 검증 작업 시작됨",
  "task_ids": {
    "a1_stage1": "task-a1-stage1-uuid",
    "a1_stage2": "task-a1-stage2-uuid",
    "a2": "task-a2-uuid",
    "a3": "task-a3-uuid"
  }
}
```

#### 검증 결과 조회
```bash
GET /api/validation/{contract_id}
```

**응답**:
```json
{
  "contract_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "a1_result": {
    "matched": [...],
    "missing": [...],
    "extra": [...]
  },
  "a2_result": {
    "checklist_results": [...]
  },
  "a3_result": {
    "article_comparisons": [...],
    "overall_score": 85.5
  },
  "token_usage": {
    "total_tokens": 15000,
    "a1_tokens": 5000,
    "a2_tokens": 4500,
    "a3_tokens": 5500
  }
}
```

#### 토큰 사용량 조회
```bash
GET /api/token-usage/{contract_id}
```

**응답**:
```json
{
  "contract_id": "550e8400-e29b-41d4-a716-446655440000",
  "classification_tokens": 1250,
  "validation_tokens": 15000,
  "chatbot_tokens": 3200,
  "total_tokens": 19450,
  "breakdown": {
    "classification": {...},
    "a1": {...},
    "a2": {...},
    "a3": {...},
    "chatbot": {...}
  }
}
```

### 챗봇 API

#### 챗봇 활성화 상태 확인
```bash
GET /api/chatbot/{contract_id}/status
```

**응답**:
```json
{
  "contract_id": "550e8400-e29b-41d4-a716-446655440000",
  "chatbot_enabled": true,
  "classification_status": "confirmed",
  "message": "챗봇 사용 가능"
}
```

#### 메시지 전송
```bash
POST /api/chatbot/{contract_id}/message
Content-Type: application/json
```

**요청**:
```json
{
  "message": "데이터 제공 대가는 얼마인가요?",
  "session_id": "optional-session-id"
}
```

**응답**:
```json
{
  "response": "제5조(데이터 제공 대가)에 따르면...",
  "sources": [
    {
      "article_index": "제5조",
      "article_title": "데이터 제공 대가",
      "content": "..."
    }
  ],
  "session_id": "session-uuid",
  "token_usage": {
    "prompt_tokens": 450,
    "completion_tokens": 120,
    "total_tokens": 570
  }
}
```

#### 대화 히스토리 조회
```bash
GET /api/chatbot/{contract_id}/history
Query Parameters:
  - session_id: 세션 ID (선택)
```

**응답**:
```json
{
  "contract_id": "550e8400-e29b-41d4-a716-446655440000",
  "session_id": "session-uuid",
  "history": [
    {
      "role": "user",
      "content": "데이터 제공 대가는 얼마인가요?",
      "timestamp": "2024-01-15T10:30:00Z"
    },
    {
      "role": "assistant",
      "content": "제5조(데이터 제공 대가)에 따르면...",
      "timestamp": "2024-01-15T10:30:05Z"
    }
  ]
}
```

### 지식베이스 상태

#### 지식베이스 상태 확인
```bash
GET /api/knowledge-base/status
```

**응답**:
```json
{
  "status": "ready",
  "indexed_contracts": [
    "provide_std_contract",
    "create_std_contract",
    "process_std_contract",
    "brokerage_provider_std_contract",
    "brokerage_user_std_contract"
  ],
  "faiss_index_size": 1250,
  "whoosh_index_size": 1250,
  "last_updated": "2024-01-15T09:00:00Z"
}
```

## 챗봇 사용 방법

### 1. 챗봇 활성화
- 계약서 업로드 및 분류 완료 후 자동으로 활성화됩니다
- 검증 작업과 독립적으로 동작합니다

### 2. 질문 유형

#### 조 번호로 질문
```
"제5조 내용이 뭐야?"
"별지1에 뭐가 있어?"
```

#### 조 제목으로 질문
```
"데이터 제공 조항 찾아줘"
"대가 및 지급조건에 대해 알려줘"
```

#### 내용 기반 질문
```
"데이터 보안에 대한 내용 있어?"
"계약 해지 조건은 뭐야?"
```

#### 복합 질문
```
"제5조와 제7조를 비교해줘"
"이 계약의 해지나 만료 조건들을 정리해줘"
```

### 3. 챗봇 기능
- **유기적 도구 선택**: 질문에 따라 최적의 검색 전략 자동 선택
- **참조 해결**: 조항 간 참조 추적
- **대화 컨텍스트**: 이전 대화 내용 참조 가능
- **출처 명시**: 답변에 사용된 조항 정보 제공

## 프로젝트 구조

```
.
├── backend/                          # 백엔드 서비스
│   ├── fastapi/                     # FastAPI REST API 서버
│   │   ├── main.py                 # 메인 애플리케이션 엔트리포인트
│   │   ├── user_contract_parser.py # 사용자 계약서 파싱
│   │   └── user_contract_indexer.py # 사용자 계약서 인덱싱
│   │
│   ├── classification_agent/        # 분류 에이전트
│   │   └── agent.py                # RAG + LLM 분류 로직
│   │
│   ├── consistency_agent/           # 정합성 검증 에이전트
│   │   ├── agent.py                # 통합 검증 워크플로우
│   │   ├── models.py               # 데이터 모델
│   │   ├── hybrid_searcher.py      # 하이브리드 검색
│   │   ├── a1_node/                # A1: 완전성 검증 노드
│   │   │   ├── a1_node.py         # A1 메인 로직
│   │   │   ├── article_matcher.py # 조항 매칭
│   │   │   └── matching_verifier.py # LLM 매칭 검증
│   │   ├── a2_node/                # A2: 체크리스트 검증 노드
│   │   │   ├── a2_node.py         # A2 메인 로직
│   │   │   ├── checklist_loader.py # 체크리스트 로드
│   │   │   └── checklist_verifier.py # LLM 체크리스트 검증
│   │   └── a3_node/                # A3: 내용 분석 노드
│   │       ├── a3_node.py         # A3 메인 로직
│   │       └── content_comparator.py # 내용 비교
│   │
│   ├── chatbot_agent/               # 챗봇 에이전트
│   │   ├── agent.py                # LangGraph 기반 오케스트레이터
│   │   ├── agent_runtime.py        # 에이전트 실행 환경
│   │   ├── agent_persistence.py    # 대화 히스토리 저장
│   │   ├── agent_recovery.py       # 에러 복구
│   │   ├── autonomous_agent.py     # 자율 에이전트 로직
│   │   ├── context_manager.py      # 대화 컨텍스트 관리
│   │   ├── context_builder.py      # 컨텍스트 구축
│   │   ├── session_manager.py      # 세션 관리
│   │   ├── reference_resolver.py   # 참조 해결
│   │   ├── smart_reference_resolver.py # 스마트 참조 해결
│   │   ├── content_extractor.py    # 내용 발췌
│   │   ├── function_calling_adapter.py # Function Calling 어댑터
│   │   ├── lightweight_classifier.py # 경량 분류기
│   │   ├── llm_cache.py            # LLM 캐싱
│   │   ├── models.py               # 데이터 모델
│   │   ├── tools/                  # Function Calling 도구
│   │   │   ├── base.py            # 도구 베이스 클래스
│   │   │   ├── hybrid_search_tool.py # 하이브리드 검색 도구
│   │   │   ├── article_index_tool.py # 조 번호 검색 도구
│   │   │   ├── article_title_tool.py # 조 제목 검색 도구
│   │   │   └── standard_contract_tool.py # 표준계약서 검색 도구
│   │   └── validators/             # 검증기
│   │       ├── scope_validator.py # 범위 검증
│   │       └── response_validator.py # 응답 검증
│   │
│   ├── report_agent/                # 보고서 생성 에이전트 (계획)
│   │   ├── agent.py                # 보고서 생성 로직
│   │   ├── step1_normalizer.py     # 데이터 정규화
│   │   ├── step2_aggregator.py     # 조별 집계
│   │   ├── step3_resolver.py       # 참조 해결
│   │   ├── step4_reporter.py       # 조별 보고서 생성
│   │   ├── step5_final_integrator.py # 최종 통합
│   │   ├── report_formatter.py     # 보고서 포맷팅
│   │   └── report_section_saver.py # 보고서 섹션 저장
│   │
│   └── shared/                      # 공통 모듈
│       ├── core/                   # 핵심 비즈니스 로직
│       │   └── celery_app.py      # Celery 설정
│       ├── database.py             # SQLAlchemy 모델
│       ├── services/               # 공통 서비스
│       │   ├── knowledge_base_loader.py # 지식베이스 로드
│       │   ├── embedding_generator.py # 임베딩 생성
│       │   ├── embedding_loader.py # 임베딩 로드
│       │   ├── search_service.py   # 검색 서비스
│       │   └── whoosh_searcher.py  # Whoosh 검색
│       └── utils/                  # 유틸리티
│           └── korean_analyzer.py  # 한국어 분석
│
├── frontend/                        # 프론트엔드
│   ├── app.py                      # Streamlit 메인 애플리케이션
│   └── .streamlit/                 # Streamlit 설정
│       └── config.toml
│
├── ingestion/                       # 문서 처리 파이프라인
│   ├── ingest.py                   # CLI 메인 모듈
│   ├── parsers/                    # 문서 파서
│   │   ├── std_contract_docx_parser.py # 표준계약서 파서
│   │   ├── guidebook_docx_parser.py # 활용안내서 파서
│   │   └── guidebook/              # 활용안내서 전용 파서
│   │       ├── create_parser.py
│   │       ├── provide_parser.py
│   │       ├── process_parser.py
│   │       ├── brokerage_provider_parse.py
│   │       ├── brokerage_user_parse.py
│   │       └── checklist/          # 체크리스트 파서
│   │           └── checklist_parse.py
│   ├── processors/                 # 청킹 및 임베딩 처리기
│   │   ├── chunker.py             # 기본 청커
│   │   ├── art_chunker.py         # 조 단위 청커
│   │   ├── embedder.py            # 임베딩 생성기
│   │   └── searcher.py            # 검색 테스트
│   └── indexers/                   # 검색 인덱스 생성기
│       ├── faiss_indexer.py       # FAISS 인덱서
│       └── whoosh_indexer.py      # Whoosh 인덱서
│
├── data/                            # 데이터 저장소
│   ├── source_documents/           # 원본 문서 (PDF, DOCX)
│   ├── extracted_documents/        # 파싱된 구조화 데이터 (JSON)
│   ├── chunked_documents/          # 청킹된 문서 (JSONL)
│   │   └── guidebook_chunked_documents/ # 활용안내서 청크
│   │       ├── checklist_documents/ # 체크리스트 문서
│   │       └── commentary_documents/ # 해설 문서
│   ├── search_indexes/             # 검색 인덱스
│   │   ├── faiss/                 # FAISS 벡터 인덱스
│   │   └── whoosh/                # Whoosh 키워드 인덱스
│   ├── user_contract_indexes/      # 사용자 계약서 인덱스
│   │   ├── faiss/
│   │   └── whoosh/
│   ├── parsed_user_contracts/      # 파싱된 사용자 계약서
│   └── database/                   # SQLite 데이터베이스
│       └── contracts.db
│
├── docker/                          # Docker 설정
│   ├── docker-compose.yml          # 멀티 컨테이너 오케스트레이션
│   ├── Dockerfile.backend          # FastAPI 컨테이너
│   ├── Dockerfile.chatbot          # 챗봇 에이전트 컨테이너
│   ├── Dockerfile.classification   # 분류 에이전트 컨테이너
│   ├── Dockerfile.consistency      # 정합성 에이전트 컨테이너
│   ├── Dockerfile.report           # 보고서 에이전트 컨테이너 (계획)
│   └── Dockerfile.ingestion        # 문서 처리 컨테이너
│
├── docs/                            # 상세 문서
│   ├── CLASSIFICATION_AGENT.md     # 분류 에이전트 문서
│   ├── CONSISTENCY_AGENT.md        # 정합성 검증 에이전트 문서
│   ├── CONSISTENCY_A1_HYBRID_SEARCH.md # A1 하이브리드 검색
│   ├── CONSISTENCY_A1_MISSING_VERIFICATION.md # A1 누락 검증
│   ├── CONSISTENCY_A2_NODE.md      # A2 체크리스트 검증
│   ├── CONSISTENCY_A3_NODE.md      # A3 내용 분석
│   ├── CONSISTENCY_OUTPUT_SCHEMAS.md # 출력 스키마
│   ├── CHATBOT_AGENT.md            # 챗봇 에이전트 문서
│   ├── CHATBOT_TOOLS.md            # 챗봇 도구 문서
│   ├── REPORT_AGENT.md             # 보고서 에이전트 문서
│   ├── INGESTION_PIPELINE.md       # 문서 처리 파이프라인
│   └── SYSTEM_ARCHITECTURE.md      # 시스템 아키텍처
│
├── requirements/                    # 의존성 관리
│   ├── requirements.txt            # 공통 의존성
│   ├── requirements-backend.txt    # FastAPI 의존성
│   ├── requirements-frontend.txt   # Streamlit 의존성
│   ├── requirements-classification.txt # 분류 에이전트 의존성
│   ├── requirements-consistency.txt # 정합성 에이전트 의존성
│   ├── requirements-report.txt     # 보고서 에이전트 의존성
│   └── requirements-ingestion.txt  # 문서 처리 의존성
│
├── tests/                           # 테스트
│   ├── unit/                       # 단위 테스트
│   ├── integration/                # 통합 테스트
│   └── e2e/                        # 엔드투엔드 테스트
│
├── .env                             # 환경 변수 설정
├── .gitignore                       # Git 무시 파일
└── README.md                        # 프로젝트 개요 (본 문서)
```

### 주요 모듈 설명

#### Classification Agent
RAG 기반 계약서 분류 시스템. 주요 조항 추출, 하이브리드 검색, Gating 메커니즘을 통한 LLM 호출 최적화를 수행함.

#### Consistency Agent
3단계 정합성 검증 시스템. A1(완전성), A2(체크리스트), A3(내용 분석) 노드를 병렬 실행하여 계약서 품질을 평가함.

#### Chatbot Agent
LangGraph 기반 대화형 질의응답 시스템. Function Calling을 통해 4가지 도구를 유기적으로 선택하여 사용자 질문에 답변함.

#### Report Agent (계획)
검증 결과를 통합하여 상세 분석 보고서를 생성하는 시스템. 5단계 파이프라인을 통해 조별 보고서를 생성하고 최종 통합함.

#### Ingestion Pipeline
표준계약서와 활용안내서를 파싱, 청킹, 임베딩, 인덱싱하는 4단계 문서 처리 파이프라인. FAISS와 Whoosh 인덱스를 생성함.

## 기술 스택

### Backend
- **FastAPI**: REST API 서버
- **SQLAlchemy**: ORM 및 데이터베이스 관리
- **SQLite**: 경량 데이터베이스
- **Redis**: 메시지 큐 및 캐싱
- **Celery**: 비동기 작업 처리

### Frontend
- **Streamlit**: 웹 인터페이스

### AI & Search
- **Azure OpenAI**: GPT-4o, text-embedding-3-large
- **FAISS**: 벡터 검색 (시멘틱 검색)
- **Whoosh**: 키워드 검색 (BM25)

### Infrastructure
- **Docker**: 컨테이너화
- **Docker Compose**: 멀티 컨테이너 오케스트레이션

## 개발 환경 설정

### 로컬 개발
```bash
# 가상환경 생성
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux/Mac

# 의존성 설치
pip install -r requirements/requirements.txt
pip install -r requirements/requirements-backend.txt
pip install -r requirements/requirements-frontend.txt

# 개별 서비스 실행
# FastAPI 백엔드
python -m uvicorn backend.fastapi.main:app --host 0.0.0.0 --port 8000 --reload

# Streamlit 프론트엔드
streamlit run frontend/app.py

# Celery Workers
celery -A backend.shared.core.celery_app worker --loglevel=info --queues=classification
celery -A backend.shared.core.celery_app worker --loglevel=info --queues=consistency_validation
```

## 문제 해결

### 챗봇이 활성화되지 않는 경우
1. 계약서 분류가 완료되었는지 확인
2. FastAPI 백엔드가 실행 중인지 확인
3. 브라우저 콘솔에서 API 호출 오류 확인

### 검색 결과가 없는 경우
1. 지식베이스가 구축되었는지 확인
2. 사용자 계약서 인덱스가 생성되었는지 확인
3. 검색 가중치 조정 시도

### Docker 컨테이너 오류
```bash
# 로그 확인
docker-compose -f docker/docker-compose.yml logs chatbot-agent

# 컨테이너 재시작
docker-compose -f docker/docker-compose.yml restart chatbot-agent

# 전체 재구축
docker-compose -f docker/docker-compose.yml down
docker-compose -f docker/docker-compose.yml up -d --build
```

## 상세 문서

프로젝트의 각 컴포넌트에 대한 상세 문서는 `docs/` 디렉토리에서 확인할 수 있습니다.

### 시스템 아키텍처
- [SYSTEM_ARCHITECTURE.md](docs/SYSTEM_ARCHITECTURE.md) - 전체 시스템 아키텍처 및 데이터 흐름
- [PARALLEL_PROCESSING_ARCHITECTURE.md](docs/PARALLEL_PROCESSING_ARCHITECTURE.md) - 병렬 처리 아키텍처
- [DATA_SHARING_AND_DB.md](docs/DATA_SHARING_AND_DB.md) - 데이터 공유 및 데이터베이스 구조

### Classification Agent (분류 에이전트)
- [CLASSIFICATION_AGENT.md](docs/CLASSIFICATION_AGENT.md) - 분류 에이전트 전체 구조 및 작동 흐름
  - RAG 기반 분류 메커니즘
  - 하이브리드 검색 (FAISS + Whoosh)
  - Gating 메커니즘
  - LLM Few-shot 분류
  - API 스키마 및 Celery 작업 흐름

### Consistency Agent (정합성 검증 에이전트)
- [CONSISTENCY_AGENT.md](docs/CONSISTENCY_AGENT.md) - 정합성 검증 에이전트 전체 구조
  - 3개 노드 (A1, A2, A3) 개요
  - 순차 실행 vs 병렬 처리
  - 데이터 흐름 및 에러 처리
- [CONSISTENCY_AGENT_FLOW.md](docs/CONSISTENCY_AGENT_FLOW.md) - 정합성 검증 플로우 다이어그램

#### A1 Node (완전성 검증)
- [CONSISTENCY_A1_HYBRID_SEARCH.md](docs/CONSISTENCY_A1_HYBRID_SEARCH.md) - A1 하이브리드 검색 및 매칭
  - FAISS 벡터 검색
  - Whoosh 키워드 검색
  - 점수 융합 알고리즘
  - 청크 → 조 단위 집계
  - 가중치 조정 가이드
- [CONSISTENCY_A1_MISSING_VERIFICATION.md](docs/CONSISTENCY_A1_MISSING_VERIFICATION.md) - A1 누락 검증
  - 누락 조항 식별 프로세스
  - LLM 재검증 메커니즘
  - 재매칭 로직
- [CONSISTENCY_A1_SUMMARY.md](docs/CONSISTENCY_A1_SUMMARY.md) - A1 노드 요약
- [A1_FLOW_DIAGRAMS.md](docs/A1_FLOW_DIAGRAMS.md) - A1 플로우 다이어그램
- [A1_HYBRID_SEARCH_ARCHITECTURE.md](docs/A1_HYBRID_SEARCH_ARCHITECTURE.md) - A1 하이브리드 검색 아키텍처
- [A1_MISSING_VERIFICATION.md](docs/A1_MISSING_VERIFICATION.md) - A1 누락 검증 상세

#### A2 Node (체크리스트 검증)
- [CONSISTENCY_A2_NODE.md](docs/CONSISTENCY_A2_NODE.md) - A2 체크리스트 검증
  - 체크리스트 로드 및 필터링
  - article_mapping 활용
  - LLM 검증 프로세스
  - YES/NO/UNCLEAR 결과 구조
- [CONSISTENCY_A2_SUMMARY.md](docs/CONSISTENCY_A2_SUMMARY.md) - A2 노드 요약

#### A3 Node (내용 분석)
- [CONSISTENCY_A3_NODE.md](docs/CONSISTENCY_A3_NODE.md) - A3 내용 분석
  - 조항 쌍 생성 및 비교
  - LLM 내용 비교
  - 평가 기준 (완전성, 명확성, 실무성)
  - 점수 및 개선 제안 구조
- [CONSISTENCY_A3_SUMMARY.md](docs/CONSISTENCY_A3_SUMMARY.md) - A3 노드 요약
- [A3_FLOW_DIAGRAM.md](docs/A3_FLOW_DIAGRAM.md) - A3 플로우 다이어그램

#### 출력 스키마
- [CONSISTENCY_OUTPUT_SCHEMAS.md](docs/CONSISTENCY_OUTPUT_SCHEMAS.md) - A1/A2/A3 출력 스키마
  - A1 출력 스키마 (article_mapping.json)
  - A2 출력 스키마 (checklist_result.json)
  - A3 출력 스키마 (content_comparison.json)
  - 스키마 간 관계 및 JSON 예시
- [A1_A2_A3_OUTPUT_SCHEMA.md](docs/A1_A2_A3_OUTPUT_SCHEMA.md) - 통합 출력 스키마

### Chatbot Agent (챗봇 에이전트)
- [CHATBOT_AGENT.md](docs/CHATBOT_AGENT.md) - 챗봇 에이전트 전체 구조
  - LangGraph 아키텍처
  - 노드 구조 및 전환 조건
  - 상태 및 컨텍스트 관리
  - 에러 처리 및 재시도
- [CHATBOT_TOOLS.md](docs/CHATBOT_TOOLS.md) - 챗봇 도구 및 Function Calling
  - Function Calling 메커니즘
  - 4가지 도구 (HybridSearch, ArticleIndex, ArticleTitle, StandardContract)
  - 입출력 스키마
  - 도구 체이닝
- [CHATBOT_FLOW_ANALYSIS.md](docs/CHATBOT_FLOW_ANALYSIS.md) - 챗봇 플로우 분석
- [CHATBOT_LANGGRAPH_DIAGRAM.md](docs/CHATBOT_LANGGRAPH_DIAGRAM.md) - LangGraph 다이어그램

### Report Agent (보고서 생성 에이전트)
- [REPORT_AGENT.md](docs/REPORT_AGENT.md) - 보고서 생성 에이전트 구조
  - 5단계 보고서 생성 프로세스
  - 데이터 통합 (A1, A2, A3 결과 병합)
  - 보고서 구조 및 출력 스키마

### Ingestion Pipeline (문서 처리 파이프라인)
- [INGESTION_PIPELINE.md](docs/INGESTION_PIPELINE.md) - 문서 처리 파이프라인
  - 4단계 파이프라인 (파싱, 청킹, 임베딩, 인덱싱)
  - 파서 및 청커 모듈
  - FAISS 및 Whoosh 인덱스 생성
  - CLI 명령어 및 실행 모드

### 지식베이스 및 검색
- [KNOWLEDGE_BASE_SUMMARY.md](docs/KNOWLEDGE_BASE_SUMMARY.md) - 지식베이스 요약
- [RRF_FUSION.md](docs/RRF_FUSION.md) - Reciprocal Rank Fusion 알고리즘

## 라이선스

본 프로젝트의 라이선스 정보는 별도로 명시되지 않았습니다.

## 기여

기여 가이드라인은 별도로 명시되지 않았습니다.

## 문의

프로젝트 관련 문의사항은 이슈 트래커를 통해 제출해 주시기 바랍니다.
