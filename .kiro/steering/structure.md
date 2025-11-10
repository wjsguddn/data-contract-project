# 프로젝트 구조 및 조직

## 디렉토리 구조

### 루트 레벨
- `.env`: 환경 변수 설정 파일
- `.gitignore`: Git 무시 파일 목록
- `.kiro/`: Kiro AI 설정 및 스티어링 규칙
- `.venv/`: Python 가상환경

### 백엔드 (`backend/`)
```
backend/
├── fastapi/                    # FastAPI 웹 서버
│   ├── main.py                # 메인 애플리케이션 엔트리포인트
│   └── user_contract_parser.py # 사용자 계약서 파싱
├── classification_agent/       # 문서 분류 에이전트
│   └── agent.py               # RAG + LLM 분류 로직
├── consistency_agent/          # 정합성 검증 에이전트
│   ├── agent.py               # 통합 검증 워크플로우
│   ├── a1_node/               # 완전성 검증 노드
│   │   ├── a1_node.py        # A1 메인 로직
│   │   ├── article_matcher.py # 조항 매칭
│   │   └── matching_verifier.py # LLM 매칭 검증
│   ├── a2_node/               # 체크리스트 검증 노드
│   │   ├── a2_node.py        # A2 메인 로직
│   │   ├── checklist_loader.py # 체크리스트 로드
│   │   └── checklist_verifier.py # LLM 체크리스트 검증
│   ├── a3_node/               # 내용 분석 노드
│   │   ├── a3_node.py        # A3 메인 로직
│   │   └── content_comparator.py # 내용 비교
│   ├── models.py              # 데이터 모델
│   └── hybrid_searcher.py     # 하이브리드 검색
├── report_agent/               # 보고서 생성 에이전트 (계획)
│   └── agent.py               # 보고서 생성 로직
└── shared/                     # 공통 모듈
    ├── core/                  # 핵심 비즈니스 로직
    │   └── celery_app.py     # Celery 설정
    ├── database.py            # SQLAlchemy 모델
    ├── services/              # 공통 서비스
    │   ├── knowledge_base_loader.py # 지식베이스 로드
    │   ├── embedding_service.py     # 임베딩 생성
    │   └── whoosh_searcher.py       # Whoosh 검색
    └── utils/                 # 유틸리티
        └── korean_analyzer.py # 한국어 분석
```

### 프론트엔드 (`frontend/`)
```
frontend/
├── app.py            # Streamlit 메인 애플리케이션
└── .streamlit/       # Streamlit 설정
```

### 문서 처리 (`ingestion/`)
```
ingestion/
├── ingest.py         # CLI 메인 모듈
├── parsers/          # 문서 파서 (PDF, DOCX)
├── processors/       # 청킹 및 임베딩 처리기
├── indexers/         # 검색 인덱스 생성기
└── test_chunker.py   # 청킹 테스트
```

### 데이터 (`data/`)
```
data/
├── source_documents/     # 원본 문서 (PDF, DOCX)
├── extracted_documents/  # 파싱된 구조화 데이터 (JSON)
├── chunked_documents/    # 청킹된 문서 (JSONL)
├── search_indexes/       # FAISS/Whoosh 인덱스
└── database/            # SQLite 데이터베이스
```

### 인프라 (`docker/`)
```
docker/
├── docker-compose.yml         # 멀티 컨테이너 오케스트레이션
├── Dockerfile.backend         # FastAPI 컨테이너
├── Dockerfile.classification  # 분류 에이전트 컨테이너
├── Dockerfile.consistency     # 정합성 에이전트 컨테이너
├── Dockerfile.report          # 보고서 에이전트 컨테이너 (계획)
└── Dockerfile.ingestion       # 문서 처리 컨테이너
```

### 의존성 (`requirements/`)
```
requirements/
├── requirements.txt              # 공통 의존성
├── requirements-backend.txt      # FastAPI 의존성
├── requirements-frontend.txt     # Streamlit 의존성
├── requirements-classification.txt  # 분류 에이전트 의존성
├── requirements-consistency.txt     # 정합성 에이전트 의존성
├── requirements-report.txt          # 보고서 에이전트 의존성
└── requirements-ingestion.txt       # 문서 처리 의존성
```

### 테스트 (`tests/`)
```
tests/
├── unit/         # 단위 테스트
├── integration/  # 통합 테스트
└── e2e/         # 엔드투엔드 테스트
```

## 아키텍처 패턴

### 마이크로서비스 아키텍처
- 각 에이전트는 독립적인 서비스로 구성
- Redis를 통한 메시지 큐 기반 통신
- Docker 컨테이너로 격리된 실행 환경

### 데이터 플로우
1. **업로드**: Streamlit → FastAPI → DOCX 파싱 → 임베딩 생성
2. **분류**: Classification Agent (RAG + LLM) → 유형 결정
3. **검증**: Consistency Agent 
   - A1: 조항 매칭 및 완전성 검증
   - A2: 체크리스트 검증 (병렬)
   - A3: 내용 분석 (병렬)
4. **보고서**: Report Agent → 통합 분석 보고서 생성

### 명명 규칙
- **파일명**: snake_case (예: `pdf_parser.py`)
- **클래스명**: PascalCase (예: `ArticleChunker`)
- **함수명**: snake_case (예: `chunk_file()`)
- **상수명**: UPPER_SNAKE_CASE (예: `DATABASE_URL`)
- **디렉토리명**: snake_case 또는 kebab-case

### 코드 조직 원칙
- 각 에이전트는 독립적인 모듈로 구성
- 공통 기능은 `shared/` 디렉토리에 배치
- 설정 파일과 비즈니스 로직 분리
- 테스트 코드는 해당 모듈과 동일한 구조로 조직