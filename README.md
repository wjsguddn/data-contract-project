# 데이터 표준계약 검증 시스템

AI 기반 한국어 데이터 계약서 분석 및 검증 시스템으로, 5종 표준계약서를 기준으로 사용자 계약서를 분류하고 정합성을 검증합니다.

## 주요 기능

### 1. 계약서 업로드 및 분류
- DOCX 형식의 계약서 업로드
- AI 기반 자동 분류 (5종 표준계약서 유형)
  - 데이터 제공형 계약
  - 데이터 창출형 계약
  - 데이터 가공서비스형 계약
  - 데이터 중개거래형 계약 (제공자-운영자)
  - 데이터 중개거래형 계약 (이용자-운영자)

### 2. 정합성 검증
- **A1 노드**: 완전성 검증 (조항 매칭, 누락 조항 식별)
- **A2 노드**: 체크리스트 검증 (활용안내서 기반)
- **A3 노드**: 내용 분석 (조항별 충실도 평가)
- 하이브리드 검색 (FAISS + Whoosh)
- 맥락 기반 유연한 검증

### 3. 계약서 챗봇
- 계약서 내용에 대한 자연어 질의응답
- Function Calling 기반 유기적 도구 선택
- 하이브리드 검색을 통한 관련 조항 검색
- 조 번호/제목 기반 직접 접근
- 대화 컨텍스트 관리 및 참조 해결

## 시스템 요구사항

### 필수 요구사항
- Python 3.9 이상
- Docker 및 Docker Compose
- Azure OpenAI API 자격 증명

### 환경 변수
```bash
# Azure OpenAI 설정 (필수)
AZURE_OPENAI_API_KEY=your_api_key_here
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_EMBEDDING_DEPLOYMENT=text-embedding-3-large
AZURE_GPT_DEPLOYMENT=gpt-4o

# 데이터베이스
DATABASE_URL=sqlite:///data/database/contracts.db

# Redis
REDIS_URL=redis://redis:6379
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

### 2. Docker로 실행
```bash
# 전체 시스템 실행
docker-compose -f docker/docker-compose.yml up -d

# 서비스 확인
docker-compose -f docker/docker-compose.yml ps
```

### 3. 지식베이스 구축 (최초 1회)
```bash
# 표준계약서 인덱싱
docker-compose -f docker/docker-compose.yml --profile ingestion run --rm ingestion
```

### 4. 웹 인터페이스 접속
- Streamlit 프론트엔드: http://localhost:8501
- FastAPI 백엔드: http://localhost:8000
- API 문서: http://localhost:8000/docs

## API 엔드포인트

### 계약서 업로드 및 분류
```bash
# 계약서 업로드 (자동 분류 시작)
POST /upload
Content-Type: multipart/form-data
Body: file (DOCX)

# 분류 결과 조회
GET /api/classification/{contract_id}

# 분류 확인/수정
POST /api/classification/{contract_id}/confirm?confirmed_type={type}
```

### 정합성 검증
```bash
# 검증 시작
POST /api/validation/{contract_id}/start
Query Parameters:
  - text_weight: 본문 가중치 (기본 0.7)
  - title_weight: 제목 가중치 (기본 0.3)
  - dense_weight: 시멘틱 가중치 (기본 0.85)

# 검증 결과 조회
GET /api/validation/{contract_id}

# 토큰 사용량 조회
GET /api/token-usage/{contract_id}
```

### 챗봇 API
```bash
# 챗봇 활성화 상태 확인
GET /api/chatbot/{contract_id}/status

# 메시지 전송
POST /api/chatbot/{contract_id}/message
Content-Type: application/json
Body: {
  "message": "데이터 제공 대가는 얼마인가요?",
  "session_id": "optional-session-id"
}

# 대화 히스토리 조회
GET /api/chatbot/{contract_id}/history?session_id={session_id}
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
├── backend/
│   ├── fastapi/              # REST API 서버
│   ├── classification_agent/ # 분류 에이전트
│   ├── consistency_agent/    # 정합성 검증 에이전트
│   ├── chatbot_agent/        # 챗봇 에이전트 (신규)
│   │   ├── agent.py         # 챗봇 오케스트레이터
│   │   ├── tools/           # Function Calling 도구
│   │   ├── validators/      # 범위 및 응답 검증
│   │   ├── tool_planner.py  # 도구 계획 수립
│   │   ├── content_extractor.py  # 내용 발췌
│   │   ├── reference_resolver.py # 참조 해결
│   │   └── context_manager.py    # 대화 컨텍스트 관리
│   └── shared/              # 공통 모듈
├── frontend/
│   └── app.py               # Streamlit 웹 인터페이스
├── ingestion/               # 문서 처리 파이프라인
├── data/                    # 데이터 저장소
└── docker/                  # Docker 설정
```

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
