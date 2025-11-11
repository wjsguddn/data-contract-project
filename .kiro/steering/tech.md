# 기술 스택 및 빌드 시스템

## 핵심 기술 스택

### Backend
- **FastAPI**: REST API 서버 (Python 3.x)
- **SQLAlchemy**: ORM 및 데이터베이스 관리
- **SQLite**: 경량 데이터베이스 (개발/테스트용)
- **Redis**: 메시지 큐 및 캐싱
- **Celery**: 비동기 작업 처리 (분류, 검증 에이전트)
- **Uvicorn**: ASGI 서버

### Frontend
- **Streamlit**: 웹 인터페이스 (Python 기반)

### AI & Search
- **Azure OpenAI**: GPT-4, text-embedding-3-large
- **FAISS**: 벡터 검색 인덱싱 (시멘틱 검색)
- **Whoosh**: 키워드 검색 인덱싱 (BM25)
- **하이브리드 검색**: FAISS + Whoosh 결합

### Document Processing
- **PyMuPDF**: PDF 파싱 및 텍스트 추출
- **python-docx**: DOCX 파일 파싱
- **한국어 분석**: 형태소 분석 및 키워드 추출

### Infrastructure
- **Docker**: 컨테이너화
- **Docker Compose**: 멀티 컨테이너 오케스트레이션

## 주요 명령어

### 개발 환경 설정
```bash
# 가상환경 생성 및 활성화
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux/Mac

# 의존성 설치
pip install -r requirements/requirements.txt
pip install -r requirements/requirements-backend.txt
pip install -r requirements/requirements-frontend.txt
```

### Docker 실행
```bash
# 전체 시스템 실행
docker-compose -f docker/docker-compose.yml up -d

# 특정 서비스만 실행
docker-compose -f docker/docker-compose.yml up fast-api redis

# 문서 수집(ingestion) 실행
docker-compose -f docker/docker-compose.yml --profile ingestion run --rm ingestion
```

### 개발 서버 실행
```bash
# 전체 시스템 실행 (권장)
docker-compose -f docker/docker-compose.yml up -d

# 개별 서비스 실행
# FastAPI 백엔드 (포트 8000)
python -m uvicorn backend.fastapi.main:app --host 0.0.0.0 --port 8000 --reload

# Streamlit 프론트엔드 (포트 8501)
streamlit run frontend/app.py

# Celery Workers (각 에이전트별)
celery -A backend.shared.core.celery_app worker --loglevel=info --queues=classification
celery -A backend.shared.core.celery_app worker --loglevel=info --queues=consistency_validation

# Redis (메시지 큐)
redis-server
```

### 문서 처리 파이프라인
```bash
# 지식베이스 구축 (표준계약서 5종 + 활용안내서)
docker-compose -f docker/docker-compose.yml --profile ingestion run --rm ingestion

# 또는 직접 실행
python -m ingestion.ingest

# 전체 파이프라인 실행 (파싱→청킹→임베딩→인덱싱)
python -m ingestion.ingest --mode full --file all

# 단계별 실행
python -m ingestion.ingest --mode parsing --file provide_std_contract.docx
python -m ingestion.ingest --mode chunking --file provide_std_contract_structured.json
python -m ingestion.ingest --mode embedding --file provide_std_contract_chunks.json

# 하이브리드 검색 인덱스 생성 (FAISS + Whoosh)
python -m ingestion.ingest --mode indexing --file provide_std_contract_chunks.json
```

## 환경 변수
```bash
# Azure OpenAI 설정 (필수)
AZURE_OPENAI_API_KEY=your_api_key_here
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_EMBEDDING_DEPLOYMENT=text-embedding-3-large
AZURE_GPT_DEPLOYMENT=gpt-4

# Redis 설정
REDIS_URL=redis://localhost:6379/0

# 데이터베이스 설정
DATABASE_URL=sqlite:///data/database/contracts.db

# Celery 설정
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
```

**중요**: Azure OpenAI 환경 변수가 설정되지 않으면 Classification Agent와 Consistency Agent가 동작하지 않습니다.

## 주요 API 엔드포인트

### 계약서 업로드 및 분류
```bash
# 계약서 업로드 (자동 분류 시작)
POST /upload

# 분류 결과 조회
GET /api/classification/{contract_id}

# 분류 확인/수정
POST /api/classification/{contract_id}/confirm
```

### 정합성 검증 (Phase 2)
```bash
# 검증 시작 (병렬 처리)
POST /api/validation/{contract_id}/start

# 검증 결과 조회
GET /api/validation/{contract_id}

# 토큰 사용량 조회
GET /api/token-usage/{contract_id}
```

### 지식베이스 상태
```bash
# 지식베이스 상태 확인
GET /api/knowledge-base/status
```