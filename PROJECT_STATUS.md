# 프로젝트 현재 상태

## 개요
데이터 표준계약 검증 시스템 - 5종의 데이터 표준계약서를 기반으로 사용자 계약서를 검증하는 AI 시스템

## 완료된 작업

### 1. 기본 인프라 구축 ✅
- **Docker 환경**: 멀티 컨테이너 아키텍처 (FastAPI, Redis, Celery Workers)
- **데이터베이스**: SQLite 기반 (`data/database/contracts.db`)
- **모델**: ContractDocument, ClassificationResult, ValidationResult, TokenUsage
- **메시지 큐**: Redis + Celery 비동기 작업 처리 (분류, 검증 큐 분리)
- **볼륨 공유**: Docker 볼륨을 통한 데이터 공유

### 2. 지식베이스 구축 시스템 ✅
- **Ingestion Pipeline**: 표준계약서 + 활용안내서 파싱, 청킹, 임베딩, 인덱싱
- **하이브리드 검색**: FAISS (벡터) + Whoosh (키워드) 결합 검색
- **지식베이스 로더**: `backend/shared/services/knowledge_base_loader.py`
- **상태 확인**: `GET /api/knowledge-base/status` API
- **지원 유형**: 5종 표준계약서 (제공형, 창출형, 가공형, 중개거래형 2종)

### 3. 사용자 계약서 처리 파이프라인 ✅
- **파일**: `backend/fastapi/user_contract_parser.py`
- **파싱 방식**: "제n조" 패턴 매칭 (구조화된 DOCX 지원)
- **임베딩 생성**: 업로드 시 자동 임베딩 생성 및 저장
- **API**: `POST /upload` - DOCX 업로드, 파싱, 임베딩, 자동 분류 큐 전송
- **메타데이터**: 서문(preamble) 수집, 파싱 통계 포함

### 4. Classification Agent 구현 ✅
- **파일**: `backend/classification_agent/agent.py`
- **분류 전략**: 
  - 하이브리드 RAG 검색 (FAISS + Whoosh)
  - Gating 메커니즘 (임베딩 vs LLM Few-shot)
  - Azure OpenAI GPT-4 기반 최종 분류
  - 신뢰도 점수 및 분류 근거 생성
- **비동기 처리**: Celery Task (`classification.classify_contract`)
- **토큰 추적**: API 호출별 토큰 사용량 로깅

### 5. Consistency Agent 구현 ✅
- **파일**: `backend/consistency_agent/agent.py`
- **A1 Node (완전성 검증)**: 
  - 조항 매칭 (`article_matcher.py`)
  - LLM 매칭 검증 (`matching_verifier.py`)
  - 누락 조항 식별 및 재검증
- **A2 Node (체크리스트 검증)**:
  - 활용안내서 기반 체크리스트 로드
  - LLM 기반 체크리스트 항목 검증
- **A3 Node (내용 분석)**:
  - 조항별 내용 비교 및 충실도 평가
  - 개선 제안 생성
- **병렬 처리**: A1-Stage1 → [A1-Stage2 || A2 || A3]

### 6. FastAPI 백엔드 ✅
- **파일**: `backend/fastapi/main.py`
- **분류 API**:
  - `POST /upload` - DOCX 업로드 및 파싱
  - `GET /api/classification/{contract_id}` - 분류 결과 조회
  - `POST /api/classification/{contract_id}/confirm` - 사용자 분류 확인/수정
- **검증 API**:
  - `POST /api/validation/{contract_id}/start` - 검증 시작 (병렬/순차 선택)
  - `GET /api/validation/{contract_id}` - 검증 결과 조회
- **모니터링 API**:
  - `GET /api/knowledge-base/status` - 지식베이스 상태
  - `GET /api/token-usage/{contract_id}` - 토큰 사용량 조회

### 7. Streamlit 프론트엔드 ✅
- **파일**: `frontend/app.py`
- **주요 기능**:
  - DOCX 파일 업로드 인터페이스
  - 파싱 결과 및 계약서 구조 미리보기
  - 분류 결과 표시 (유형별 유사도 점수 포함)
  - 사용자 분류 확인/수정 UI
  - 검증 결과 조회 및 표시
  - 실시간 폴링을 통한 작업 상태 추적

### 8. 하이브리드 검색 시스템 ✅
- **FAISS 인덱서**: 벡터 검색 (`ingestion/indexers/faiss_indexer.py`)
- **Whoosh 인덱서**: 키워드 검색 (`ingestion/indexers/whoosh_indexer.py`)
- **하이브리드 검색**: 가중 평균 기반 점수 통합
- **한국어 분석**: 형태소 분석 및 키워드 추출 (`backend/shared/utils/korean_analyzer.py`)

### 9. 토큰 사용량 모니터링 ✅
- **TokenUsage 모델**: 컴포넌트별, API 타입별 토큰 사용량 추적
- **자동 로깅**: Classification, Consistency Agent에서 자동 로깅
- **집계 API**: 계약서별 토큰 사용량 통계 제공

## 현재 상태

### Phase 1 완료 (기본 분류 시스템)
- ✅ **인프라**: Docker Compose, Redis, Celery, SQLite
- ✅ **지식베이스**: 표준계약서 5종 + 활용안내서 파싱, 청킹, 임베딩, 하이브리드 인덱싱
- ✅ **사용자 계약서 처리**: DOCX 파싱, 임베딩 생성, DB 저장
- ✅ **Classification Agent**: 하이브리드 RAG + LLM Gating 기반 분류
- ✅ **API 백엔드**: FastAPI 엔드포인트 구현 (분류, 검증, 모니터링)
- ✅ **웹 프론트엔드**: Streamlit 기반 사용자 인터페이스
- ✅ **비동기 처리**: Celery 작업 큐를 통한 백그라운드 처리

### Phase 2 구현 완료 (정합성 검증 시스템)
- ✅ **A1 Node**: 완전성 검증 (조항 매칭, 누락 조항 식별, LLM 재검증)
- ✅ **A2 Node**: 체크리스트 검증 (활용안내서 기반, LLM 검증)
- ✅ **A3 Node**: 내용 분석 (조항별 충실도 평가, 개선 제안)
- ✅ **병렬 처리**: A1-Stage1 → [A1-Stage2 || A2 || A3] 아키텍처
- ✅ **하이브리드 검색**: FAISS + Whoosh 결합 검색
- ✅ **토큰 모니터링**: API 호출별 토큰 사용량 추적

### 테스트 및 검증 필요
- ⚠️ **Consistency Agent 통합 테스트**
  - A1, A2, A3 노드 전체 플로우 검증
  - 병렬 처리 안정성 테스트
  - 실제 계약서 샘플로 검증 정확도 평가
  - 토큰 사용량 최적화 검토

### Phase 2 미구현 (고도화 기능)
- ❌ **Report Agent**: 통합 보고서 생성 및 품질 검증
- ❌ **활용안내서 완전 통합**: 체크리스트 외 가이드라인 활용
- ❌ **보고서 다운로드**: PDF/DOCX 형식 보고서 생성
- ❌ **VLM 파싱**: 비정형 계약서 구조 인식

## 기술 스택
- **Backend**: FastAPI, SQLAlchemy, SQLite
- **Frontend**: Streamlit
- **AI**: Azure OpenAI (GPT-4, text-embedding-3-large)
- **검색**: FAISS (벡터) + Whoosh (키워드) 하이브리드
- **Queue**: Redis + Celery (분류, 검증 큐 분리)
- **Container**: Docker Compose (마이크로서비스 아키텍처)
- **언어 처리**: 한국어 형태소 분석, 키워드 추출

## 데이터 구조

### 사용자 계약서 파싱 결과
```json
{
  "articles": [
    {
      "number": 1,
      "title": "목적",
      "text": "제1조(목적)",
      "content": ["본 계약은...", "데이터이용자는..."]
    }
  ]
}
```

### 지식베이스 (Ingestion 결과)
```
data/
├── chunked_documents/         # *_chunks.json (5종)
├── search_indexes/
│   ├── faiss/                # *.faiss (5종)
│   └── whoosh/               # 디렉토리 (5종)
└── database/
    └── contracts.db          # SQLite
```

## 다음 작업 우선순위

### 즉시 수행 (Phase 2 완성)
1. **Consistency Agent 통합 테스트**
   - A1, A2, A3 노드 전체 플로우 검증
   - 병렬 처리 안정성 및 성능 테스트
   - 실제 계약서 샘플로 검증 정확도 평가
   - 토큰 사용량 최적화 및 비용 분석

2. **Report Agent 구현**
   - A1, A2, A3 결과 통합 및 보고서 생성
   - 과도한 규격화 방지 (QA 프로세스)
   - 사용자 친화적 보고서 템플릿
   - PDF/DOCX 다운로드 기능

### Phase 3 준비
1. **활용안내서 완전 통합**
   - 체크리스트 외 가이드라인 및 해설 활용
   - 조문비교표 기반 상세 분석
   - 계약 유형별 특화 검증 로직

2. **VLM 기반 파싱 연구**
   - 비정형 계약서 구조 인식
   - 이미지 기반 문서 처리
   - 다양한 계약서 형식 지원

3. **성능 및 확장성 개선**
   - 대용량 계약서 처리 최적화
   - 멀티테넌트 지원
   - 실시간 모니터링 및 알림

## 중요 설계 원칙

1. **맥락 기반 유연한 검증**: 표준계약서와 다르더라도 의미적으로 유사하면 인정
2. **Phase 1 단순화**: 활용안내서 제외, 규격화된 DOCX만 지원
3. **Docker 볼륨 공유**: 별도 벡터 DB 없이 파일 기반 공유

## 테스트 방법

```bash
# 1. 지식베이스 구축
docker-compose -f docker/docker-compose.yml --profile ingestion run --rm ingestion

# 2. 서버 시작
docker-compose -f docker/docker-compose.yml up fast-api

# 3. 프론트엔드
streamlit run frontend/app.py

# 4. 상태 확인
curl http://localhost:8000/api/knowledge-base/status
```

## 문제 해결

- **지식베이스 없음**: ingestion CLI 실행 필요
- **DB 초기화 실패**: `rm data/database/contracts.db` 후 재시작
- **파싱 실패**: DOCX 파일이 "제n조" 형식인지 확인

## 아키텍처 개요

```
┌─────────────────┐
│   Streamlit     │  ← 웹 사용자 인터페이스
│   Frontend      │
└────────┬────────┘
         │ HTTP API
         ↓
┌─────────────────┐
│    FastAPI      │  ← API Gateway & 업로드 처리
│    Backend      │
└────────┬────────┘
         │ Redis Queue
         ↓
┌─────────────────────────────────────────┐
│         Celery Workers                  │
│  ┌──────────┐  ┌──────────┐  ┌────────┐│
│  │Classifi- │→ │Consisten-│→ │ Report ││
│  │cation    │  │cy        │  │ Agent  ││
│  └──────────┘  └──────────┘  └────────┘│
└─────────────────┬───────────────────────┘
                  │ RAG Query
                  ↓
┌─────────────────────────────────────────┐
│      Knowledge Base (검색 인덱스)        │
│  ┌──────────────┐  ┌──────────────┐    │
│  │ Standard     │  │ Guidebook    │    │
│  │ Contracts    │  │ (Phase 2)    │    │
│  │ (5종)        │  │              │    │
│  └──────────────┘  └──────────────┘    │
│  FAISS + Whoosh (Hybrid Search)        │
└─────────────────────────────────────────┘
```

---

**마지막 업데이트**: 2025-11-05
**현재 단계**: Phase 2 구현 완료, 통합 테스트 및 Report Agent 구현 필요
**다음 작업**: Consistency Agent 통합 테스트, Report Agent 구현