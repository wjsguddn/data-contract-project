# 데이터베이스 스키마 문서

## 개요

이 문서는 `contracts.db` SQLite 데이터베이스의 전체 스키마를 정의합니다.

**데이터베이스 위치**: `data/database/contracts.db`  
**ORM**: SQLAlchemy  
**스키마 정의 파일**: `backend/shared/database.py`

### 문서 작성 소스

- 코드베이스 (`backend/` 디렉토리)
- 데이터 생성 로직 (파서, 에이전트, 노드)
- 데이터 저장 로직 (Celery 작업, DB 업데이트)

### 주요 특징

- **JSON 필드**: 대부분의 분석 결과는 JSON 형태로 저장됨
- **중첩 구조**: 복잡한 분석 결과는 깊은 중첩 구조를 가짐
- **배열 표기**: `[...]` 는 여러 항목이 존재할 수 있음을 의미
- **선택적 필드**: 일부 필드는 조건에 따라 존재하지 않을 수 있음

---

## 테이블 목록

1. [contract_documents](#1-contract_documents) - 사용자 계약서 문서
2. [classification_results](#2-classification_results) - 계약서 분류 결과
3. [validation_results](#3-validation_results) - 정합성 검증 결과
4. [reports](#4-reports) - 최종 보고서 (Phase 2, 미구현)
5. [token_usage](#5-token_usage) - API 토큰 사용량 추적

---

## 1. contract_documents

### 스키마

| 컬럼명            | 타입     | 제약조건            | 설명                                 |
| ----------------- | -------- | ------------------- | ------------------------------------ |
| `contract_id`     | String   | PRIMARY KEY, INDEX  | 계약서 고유 식별자 (UUID)            |
| `filename`        | String   | NOT NULL            | 업로드된 파일명                      |
| `upload_date`     | DateTime | DEFAULT: utcnow()   | 업로드 일시                          |
| `file_path`       | String   | NULLABLE            | 임시 파일 저장 경로                  |
| `parsed_data`     | JSON     | NULLABLE            | 파싱된 구조화 데이터 (조항 목록 등)  |
| `parsed_metadata` | JSON     | NULLABLE            | 파싱 메타데이터 (통계, 파싱 설정 등) |
| `status`          | String   | DEFAULT: "uploaded" | 처리 상태                            |

### status 필드 값

- `uploaded` - 업로드 완료
- `parsing` - 파싱 중
- `parsed` - 파싱 완료
- `classifying` - 분류 중
- `classified` - 분류 완료
- `validating` - 검증 중
- `validated` - 검증 완료
- `completed` - 전체 처리 완료
- `error` - 오류 발생

### parsed_data 구조

**소스**:

- 파싱: `backend/fastapi/user_contract_parser.py` - `UserContractParser.parse_simple_structure()`
- 임베딩: `backend/shared/services/embedding_generator.py` - `EmbeddingGenerator.generate_embeddings()`
- 저장: `backend/fastapi/main.py` - `/api/upload` 엔드포인트

```json
{
  "preamble": ["계약서 제목", "당사자 정보", "..."],
  "articles": [
    {
      "article_id": "user_article_001",
      "number": 1,
      "title": "목적",
      "text": "제1조(목적)",
      "content": ["이 계약은...", "데이터 제공에 관한...", "..."]
    },
    {
      "article_id": "user_article_002",
      "number": 2,
      "title": "정의",
      "text": "제2조(정의)",
      "content": [
        "이 계약에서 사용하는 용어의 정의는 다음과 같다.",
        "1. \"데이터\"란...",
        "2. \"제공자\"란...",
        "..."
      ]
    }
  ],
  "embeddings": {
    "metadata": {
      "model": "text-embedding-3-large",
      "created_at": "2025-11-02T10:30:45.123456+00:00",
      "embedding_version": "v1"
    },
    "article_embeddings": [
      {
        "article_no": 1,
        "title_embedding": [0.123, -0.456, 0.789, "... (3072차원)"],
        "sub_items": [
          {
            "index": 1,
            "text_embedding": [0.234, -0.567, 0.89, "... (3072차원)"]
          },
          {
            "index": 2,
            "text_embedding": [0.345, -0.678, 0.901, "... (3072차원)"]
          }
        ]
      },
      {
        "article_no": 2,
        "title_embedding": [0.456, -0.789, 0.012, "... (3072차원)"],
        "sub_items": [
          {
            "index": 1,
            "text_embedding": [0.567, -0.89, 0.123, "... (3072차원)"]
          }
        ]
      }
    ]
  }
}
```

**필드 설명**:

- `preamble`: "제1조" 이전의 모든 텍스트 (배열)
- `articles`: 조항 목록 (배열)
  - `article_id`: 고유 ID (형식: `user_article_{번호:03d}`)
  - `number`: 조 번호 (정수)
  - `title`: 조 제목 (괄호 안 텍스트 추출)
  - `text`: 조 전체 텍스트 (예: "제1조(목적)")
  - `content`: 조의 하위 내용 (평면 구조 배열)
- `embeddings`: 임베딩 데이터 (업로드 후 자동 생성, 실패 시 없을 수 있음)
  - `metadata`: 임베딩 메타데이터
    - `model`: 사용된 임베딩 모델명
    - `created_at`: 생성 일시 (ISO 8601, UTC)
    - `embedding_version`: 임베딩 버전 (현재 "v1")
  - `article_embeddings`: 조항별 임베딩 (배열, 조 번호 순 정렬)
    - `article_no`: 조 번호
    - `title_embedding`: 조 제목(text 필드)의 임베딩 벡터 (3072차원 배열, null 가능)
    - `sub_items`: 하위항목별 임베딩 (배열, index 순 정렬)
      - `index`: 하위항목 순번 (1부터 시작)
      - `text_embedding`: 하위항목 내용의 임베딩 벡터 (3072차원 배열)

**임베딩 생성 프로세스**:

1. 계약서 업로드 직후 자동 생성
2. 배치 크기: 16개씩 처리
3. 조 제목(text)과 각 하위항목(content)을 개별 임베딩
4. 실패 시에도 계약서는 저장됨 (embeddings 필드 없음)
5. 기존 임베딩이 최신 버전이면 재생성 건너뜀

### parsed_metadata 구조

**소스**: `backend/fastapi/user_contract_parser.py` - `parse_to_dict()`

```json
{
  "total_articles": 20,
  "recognized_articles": 20,
  "unrecognized_sections": 0,
  "confidence": 1.0,
  "parser_version": "phase1_simple",
  "preamble_lines": 3
}
```

**필드 설명**:

- `total_articles`: 전체 조항 수
- `recognized_articles`: 인식된 조항 수 (현재는 total_articles와 동일)
- `unrecognized_sections`: 인식 실패 섹션 수 (현재는 항상 0)
- `confidence`: 파싱 신뢰도 (조항이 있으면 1.0, 없으면 0.0)
- `parser_version`: 파서 버전 (현재 "phase1_simple")
- `preamble_lines`: 서문 줄 수

### 데이터 소스

- **생성**: `backend/fastapi/main.py` - `/api/upload` 엔드포인트
- **파싱**: `backend/fastapi/user_contract_parser.py` - `UserContractParser.parse_to_dict()`

### 참조하는 곳

- `backend/fastapi/main.py` - 계약서 조회, 상태 업데이트
- `backend/classification_agent/agent.py` - 분류 작업 시 계약서 데이터 로드
- `backend/consistency_agent/agent.py` - 검증 작업 시 계약서 데이터 로드
- `backend/shared/services/embedding_loader.py` - 임베딩 생성 시 계약서 데이터 로드

---

## 2. classification_results

**목적**: AI 기반 계약서 분류 결과 저장 (5종 표준계약서 유형 분류)

### 스키마

| 컬럼명           | 타입     | 제약조건                   | 설명                    |
| ---------------- | -------- | -------------------------- | ----------------------- |
| `id`             | Integer  | PRIMARY KEY, AUTOINCREMENT | 레코드 고유 ID          |
| `contract_id`    | String   | INDEX, NOT NULL            | 계약서 ID (외래키 역할) |
| `predicted_type` | String   | NOT NULL                   | AI가 예측한 계약 유형   |
| `confidence`     | Float    | NOT NULL                   | 예측 신뢰도 (0.0 ~ 1.0) |
| `scores`         | JSON     | NULLABLE                   | 각 유형별 점수          |
| `reasoning`      | Text     | NULLABLE                   | 분류 이유 (내부 로깅용) |
| `user_override`  | String   | NULLABLE                   | 사용자가 수정한 유형    |
| `confirmed_type` | String   | NOT NULL                   | 최종 확정된 유형        |
| `created_at`     | DateTime | DEFAULT: utcnow()          | 생성 일시               |

### predicted_type / confirmed_type 값

- `provide` - 데이터 제공 계약
- `create` - 데이터 생성 계약
- `process` - 데이터 처리 계약
- `brokerage_provider` - 데이터 중개 계약 (제공자용)
- `brokerage_user` - 데이터 중개 계약 (이용자용)

### scores 구조

**소스**: `backend/classification_agent/agent.py` - `ClassificationAgent._calculate_similarity_scores()`

```json
{
  "provide": 0.8523,
  "create": 0.1247,
  "process": 0.0234,
  "brokerage_provider": 0.0156,
  "brokerage_user": 0.0089
}
```

**필드 설명**:

- 각 계약 유형별 코사인 유사도 점수 (0.0 ~ 1.0)
- 표준계약서 상위 20개 청크와의 평균 유사도

### reasoning 구조

**소스**: `backend/classification_agent/agent.py` - `ClassificationAgent._llm_classify()`

LLM이 반환한 전체 응답 텍스트가 저장됩니다:

```
유형: provide
신뢰도: 0.85
이유: 계약서의 주요 조항들이 데이터 제공 계약의 특징을 보입니다. 특히 제3조에서 데이터 제공 범위를 명시하고 있으며...
```

### 데이터 소스

- **생성**: `backend/classification_agent/agent.py` - `classify_contract_task` Celery 작업
- **분류 로직**:
  1. 사용자 계약서 주요 5개 조항 추출
  2. 5종 표준계약서와 임베딩 유사도 계산
  3. Azure OpenAI GPT-4로 최종 분류 판단

### 참조하는 곳

- `backend/fastapi/main.py` - `/api/classification/{contract_id}` 엔드포인트 (조회)
- `backend/fastapi/main.py` - `/api/classification/{contract_id}/confirm` 엔드포인트 (사용자 수정)
- `backend/fastapi/main.py` - `/api/validate/{contract_id}` 엔드포인트 (검증 시작 전 분류 확인)
- `backend/consistency_agent/agent.py` - 검증 작업 시 계약 유형 확인

---

## 3. validation_results

**목적**: 정합성 검증 결과 저장 (Consistency Agent의 3단계 검증 결과)

### 스키마

| 컬럼명                 | 타입     | 제약조건                   | 설명                           |
| ---------------------- | -------- | -------------------------- | ------------------------------ |
| `id`                   | Integer  | PRIMARY KEY, AUTOINCREMENT | 레코드 고유 ID                 |
| `contract_id`          | String   | INDEX, NOT NULL            | 계약서 ID (외래키 역할)        |
| `contract_type`        | String   | NULLABLE                   | 계약 유형 (A3 노드에서 설정)   |
| `completeness_check`   | JSON     | NULLABLE                   | 완전성 검증 결과 (A1 노드)     |
| `checklist_validation` | JSON     | NULLABLE                   | 체크리스트 검증 결과 (A2 노드) |
| `content_analysis`     | JSON     | NULLABLE                   | 내용 분석 결과 (A3 노드)       |
| `overall_score`        | Float    | NULLABLE                   | 전체 점수                      |
| `issues`               | JSON     | NULLABLE                   | 이슈 리스트                    |
| `suggestions`          | JSON     | NULLABLE                   | 개선 제안                      |
| `recommendations`      | JSON     | NULLABLE                   | 권장사항 (agent.py에서 사용)   |
| `created_at`           | DateTime | DEFAULT: utcnow()          | 생성 일시                      |

### completeness_check 구조 (A1 노드)

**소스**: `backend/consistency_agent/a1_node/a1_node.py` - `CompletenessCheckNode.check_completeness()`

```json
{
  "contract_id": "550e8400-e29b-41d4-a716-446655440000",
  "contract_type": "provide",
  "total_user_articles": 20,
  "matched_user_articles": 18,
  "total_standard_articles": 20,
  "matched_standard_articles": 18,
  "missing_standard_articles": [
    {
      "parent_id": "제5조",
      "title": "데이터의 제공",
      "chunks": [
        {
          "id": "제5조 조본문",
          "global_id": "urn:std:provide:art:005:att",
          "unit_type": "articleText",
          "parent_id": "제5조",
          "title": "데이터의 제공",
          "order_index": 5,
          "text_raw": "...",
          "text_norm": "...",
          "anchors": [],
          "source_file": "provide_std_contract_structured.json"
        },
        {
          "id": "제5조 제1항",
          "global_id": "urn:std:provide:art:005:cla:001",
          "unit_type": "clause",
          "parent_id": "제5조",
          "title": "데이터의 제공",
          "order_index": 6,
          "text_raw": "...",
          "text_norm": "...",
          "anchors": [],
          "source_file": "provide_std_contract_structured.json"
        }
      ]
    }
  ],
  "missing_article_analysis": [
    {
      "standard_article_id": "urn:std:provide:art:005",
      "standard_article_title": "데이터의 제공",
      "is_truly_missing": true,
      "confidence": 0.85,
      "matched_user_article": null,
      "reasoning": "LLM 분석 결과 실제로 누락된 조항으로 확인됨",
      "recommendation": "'데이터의 제공' 조항 추가 필요",
      "evidence": "사용자 계약서에서 데이터 제공 방법에 대한 명시적 조항을 찾을 수 없음",
      "risk_assessment": "중요 조항 누락으로 계약 이행 시 분쟁 가능성 있음",
      "top_candidates": [
        {
          "user_article": {
            "article_id": "user_article_007",
            "number": 7,
            "title": "데이터 이용",
            "text": "제7조(데이터 이용)",
            "content": ["..."]
          },
          "similarity": 0.65,
          "avg_similarity": 0.62,
          "num_matches": 3,
          "matched_chunks": [
            {
              "standard_chunk": {"id": "제5조 조본문", "...": "..."},
              "user_sub_item": "데이터 이용자는...",
              "user_sub_item_index": 0,
              "similarity": 0.65
            }
          ]
        }
      ],
      "candidates_analysis": [
        {
          "is_match": false,
          "confidence": 0.75,
          "reasoning": "데이터 이용에 관한 내용이지 제공 방법은 아님",
          "recommendation": "'데이터의 제공' 조항을 추가할 것을 권장합니다"
        }
      ]
    }
  ],
  "matching_details": [
    {
      "user_article_no": 1,
      "user_article_id": "user_article_001",
      "user_article_title": "목적",
      "matched": true,
      "matched_articles": ["제1조"],
      "matched_articles_global_ids": ["urn:std:provide:art:001"],
      "matched_articles_details": [
        {
          "parent_id": "제1조",
          "global_id": "urn:std:provide:art:001",
          "title": "목적",
          "combined_score": 0.92,
          "num_sub_items": 2,
          "matched_sub_items": [0, 1],
          "avg_dense_score": 0.89,
          "avg_dense_score_raw": 0.87,
          "avg_sparse_score": 0.95,
          "avg_sparse_score_raw": 12.5,
          "sub_items_scores": [
            {
              "chunk_id": "제1조 조본문",
              "global_id": "urn:std:provide:art:001:att",
              "text": "본 계약은 ○○○(이하 "데이터제공자"라 한다)가...",
              "dense_score": 0.89,
              "dense_score_raw": 0.87,
              "sparse_score": 0.95,
              "sparse_score_raw": 12.5,
              "combined_score": 0.91
            }
          ]
        }
      ],
      "verification_details": [
        {
          "candidate_article_id": "제1조",
          "is_match": true,
          "confidence": 0.95,
          "reasoning": "목적 조항으로 내용이 일치함"
        }
      ]
    }
  ],
  "processing_time": 45.23,
  "verification_date": "2025-11-02T10:30:45.123456"
}
```

**필드 설명**:

- `contract_id`: 계약서 ID
- `contract_type`: 계약 유형
- `total_user_articles`: 사용자 계약서 전체 조항 수
- `matched_user_articles`: 매칭된 사용자 조항 수
- `total_standard_articles`: 표준계약서 전체 조항 수
- `matched_standard_articles`: 매칭된 표준 조항 수
- `missing_standard_articles`: 누락된 표준 조항 목록 (배열)
  - `parent_id`: 조 ID (예: "제5조")
  - `title`: 조 제목
  - `chunks`: 해당 조의 청크 목록 (임베딩 포함)
- `missing_article_analysis`: 누락 조항 재검증 결과 (배열)
  - `standard_article_id`: 표준 조항 base global_id (예: "urn:std:provide:art:005")
  - `standard_article_title`: 표준 조항 제목
  - `is_truly_missing`: 실제 누락 여부 (boolean)
  - `confidence`: 판단 신뢰도 (0.0 ~ 1.0)
  - `matched_user_article`: 매칭된 사용자 조항 전체 객체 (없으면 null)
  - `reasoning`: LLM 판단 근거
  - `recommendation`: 개선 권장사항
  - `evidence`: 판단 증거 (종합 분석 텍스트)
  - `risk_assessment`: 위험도 평가
  - `top_candidates`: 유사 후보 조항 목록 (배열, 최대 3개)
    - `user_article`: 사용자 조항 전체 객체
    - `similarity`: 최대 유사도
    - `avg_similarity`: 평균 유사도
    - `num_matches`: 매칭된 하위항목 개수
    - `matched_chunks`: 매칭된 청크 상세 정보 (배열)
  - `candidates_analysis`: 후보별 LLM 분석 결과 (배열)
    - `is_match`: 매칭 여부 (boolean)
    - `confidence`: 신뢰도
    - `reasoning`: 판단 근거
    - `recommendation`: 권장사항
- `matching_details`: 전체 조항별 매칭 상세 정보 (배열)
  - `user_article_no`: 사용자 조항 번호
  - `user_article_id`: 사용자 조항 ID
  - `matched`: 매칭 성공 여부
  - `matched_articles`: 매칭된 표준 조항 parent_id 목록
  - `matched_articles_global_ids`: 매칭된 표준 조항 global_id 목록
  - `matched_articles_details`: 매칭 상세 정보 (점수, 하위항목 등)
  - `verification_details`: LLM 검증 결과
- `processing_time`: 처리 시간 (초)
- `verification_date`: 검증 일시 (ISO 8601)

### checklist_validation 구조 (A2 노드) - 미구현

**현재 상태**: A2 노드는 구현되지 않았음.

저장되는 값:

```json
{
  "status": "pending"
}
```

### content_analysis 구조 (A3 노드) - 실제

**소스**:

- `backend/consistency_agent/a3_node/a3_node.py` - `ContentAnalysisNode.analyze_contract()`
- `backend/consistency_agent/a3_node/content_comparator.py` - `ContentComparator.compare_articles()`
- `backend/consistency_agent/models.py` - `ContentAnalysisResult.to_dict()`

```json
{
  "contract_id": "550e8400-e29b-41d4-a716-446655440000",
  "contract_type": "provide",
  "article_analysis": [
    {
      "user_article_no": 1,
      "user_article_title": "목적",
      "matched": true,
      "similarity": 0.92,
      "std_article_id": "제1조",
      "std_article_title": "목적",
      "is_special": false,
      "matched_articles": [
        {
          "parent_id": "제1조",
          "global_id": "urn:std:provide:art:001",
          "title": "목적",
          "score": 0.92,
          "num_sub_items": 1,
          "matched_sub_items": [0],
          "matched_chunks": [
            {
              "id": "제1조 조본문",
              "global_id": "urn:std:provide:art:001:att",
              "unit_type": "articleText",
              "parent_id": "제1조",
              "title": "목적",
              "order_index": 1,
              "text_raw": "  본 계약은 ○○○(이하 "데이터제공자"라 한다)가 □□□(이하 "데이터이용자"라 한다)에게 데이터를 제공하여...",
              "text_norm": "본 계약은 ○○○(이하 "데이터제공자"라 한다)가 □□□(이하 "데이터이용자"라 한다)에게 데이터를 제공하여...",
              "anchors": [],
              "source_file": "provide_std_contract_structured.json"
            }
          ]
        }
      ],
      "sub_item_results": [],
      "suggestions": [
        {
          "selected_standard_articles": ["제1조"],
          "issue_type": "content",
          "missing_items": [
            "계약 당사자(제공자, 이용자) 명시",
            "데이터 제공의 구체적 목적"
          ],
          "insufficient_items": ["계약 범위가 모호함"],
          "analysis": "**문제 여부**: 있음\n\n**누락된 내용**:\n- 계약 당사자(제공자, 이용자) 명시\n- 데이터 제공의 구체적 목적\n\n**불충분한 내용**:\n- 계약 범위가 모호함\n\n**종합 분석**:\n사용자 조항은 계약의 기본 목적을 명시하고 있으나, 표준계약서에 비해 구체성이 부족합니다...",
          "severity": "medium"
        }
      ],
      "reasoning": "표준계약서 제1조와 매칭됨",
      "analysis_timestamp": "2025-11-02T10:35:12.456789"
    },
    {
      "user_article_no": 5,
      "user_article_title": "데이터의 제공",
      "matched": true,
      "similarity": 0.88,
      "std_article_id": "제5조",
      "std_article_title": "데이터의 제공",
      "is_special": false,
      "matched_articles": [
        {
          "parent_id": "제5조",
          "global_id": "urn:std:provide:art:005",
          "title": "데이터의 제공",
          "score": 0.88,
          "num_sub_items": 3,
          "matched_sub_items": [0, 1, 2],
          "matched_chunks": ["..."]
        }
      ],
      "sub_item_results": [],
      "suggestions": [
        {
          "selected_standard_articles": ["제5조"],
          "issue_type": "content",
          "missing_items": [],
          "insufficient_items": [],
          "analysis": "**문제 여부**: 없음\n\n**누락된 내용**:\n- 없음\n\n**불충분한 내용**:\n- 없음\n\n**종합 분석**:\n사용자 조항은 표준계약서의 핵심 내용을 충실히 반영하고 있습니다. 데이터 제공 방법, 시기, 형식 등이 명확히 기술되어 있으며...",
          "severity": "info"
        }
      ],
      "reasoning": "표준계약서 제5조와 매칭됨",
      "analysis_timestamp": "2025-11-02T10:35:15.789012"
    }
  ],
  "total_articles": 20,
  "analyzed_articles": 18,
  "special_articles": 0,
  "analysis_timestamp": "2025-11-02T10:35:12.456789",
  "processing_time": 120.45
}
```

**필드 설명**:

- `contract_id`: 계약서 ID
- `contract_type`: 계약 유형
- `article_analysis`: 조항별 분석 결과 (배열)
  - `user_article_no`: 사용자 조항 번호
  - `user_article_title`: 사용자 조항 제목
  - `matched`: 매칭 성공 여부 (A1 결과 참조)
  - `similarity`: 첫 번째 매칭 조의 유사도 (UI 표시용, A1 점수)
  - `std_article_id`: 첫 번째 매칭 조 parent_id (UI 표시용)
  - `std_article_title`: 첫 번째 매칭 조 제목
  - `is_special`: 특수 조항 여부 (현재 항상 false)
  - `matched_articles`: 매칭된 모든 표준 조항 (배열, A1 결과 기반)
    - `parent_id`: 조 ID (예: "제1조")
    - `global_id`: 조 base global_id (예: "urn:std:provide:art:001")
    - `title`: 조 제목
    - `score`: 종합 점수 (A1의 combined_score)
    - `num_sub_items`: 하위항목 개수 (A1 결과)
    - `matched_sub_items`: 매칭된 하위항목 인덱스 목록 (A1 결과, 0부터 시작)
    - `matched_chunks`: 해당 조의 모든 청크 목록 (배열)
      - `id`: 청크 ID (예: "제1조 조본문", "제2조 제1호")
      - `global_id`: 청크 global_id (예: "urn:std:provide:art:001:att")
      - `unit_type`: 청크 유형 ("articleText", "clause", "subClause" 등)
      - `parent_id`: 부모 조 ID
      - `title`: 조 제목
      - `order_index`: 문서 내 순서
      - `text_raw`: 원본 텍스트
      - `text_norm`: 정규화된 텍스트
      - `anchors`: 앵커 정보 (배열)
      - `source_file`: 원본 파일명
      - **임베딩은 포함되지 않음** (별도 FAISS 인덱스에 저장)
  - `sub_item_results`: 하위항목별 비교 결과 (배열, **현재 항상 빈 배열**)
    - A3는 조항 전체 단위로만 분석하며, 하위항목별 개별 비교는 수행하지 않음
  - `suggestions`: 조항 전체 개선 제안 (배열)
    - `selected_standard_articles`: 비교 대상 표준 조항 ID 목록
    - `issue_type`: 이슈 유형 (현재 항상 "content")
    - `missing_items`: 누락된 내용 목록 (배열, LLM 파싱 결과)
    - `insufficient_items`: 불충분한 내용 목록 (배열, LLM 파싱 결과)
    - `analysis`: LLM의 전체 분석 텍스트 (마크다운 형식)
    - `severity`: 심각도
      - `"info"`: 문제 없음 (긍정적 분석)
      - `"low"`: 경미한 문제
      - `"medium"`: 중간 수준 문제 (누락 1-2개 또는 불충분 2개 이상)
      - `"high"`: 심각한 문제 (누락 3개 이상 또는 총 5개 이상)
  - `reasoning`: 매칭 근거 (A1 참조 정보)
  - `analysis_timestamp`: 분석 일시 (ISO 8601)
- `total_articles`: 전체 조항 수
- `analyzed_articles`: 분석된 조항 수 (매칭 성공한 조항 수)
- `special_articles`: 특수 조항 수 (현재 항상 0)
- `analysis_timestamp`: 전체 분석 일시 (ISO 8601)
- `processing_time`: 처리 시간 (초)

**중요 사항**:

- A3는 A1의 매칭 결과를 재사용하여 중복 검색을 방지
- `matched_articles`는 A1의 결과를 그대로 사용
- `sub_item_results`는 현재 구현에서 사용되지 않음 (항상 빈 배열)
- LLM 비교는 조항 전체 단위로만 수행
- 상위 4개 매칭 조항에 대해서만 LLM 비교 수행 (성능 최적화)

### 데이터 소스

- **A1 노드**: `backend/consistency_agent/a1_node/a1_node.py` - `CompletenessCheckNode.check_completeness()`
  - Celery 작업: `backend/consistency_agent/agent.py` - `check_completeness_task`
- **A2 노드**: 미구현 (Phase 2 예정)
- **A3 노드**: `backend/consistency_agent/a3_node/a3_node.py` - `ContentAnalysisNode.analyze_contract()`
  - Celery 작업: `backend/consistency_agent/agent.py` - `analyze_content_task`
- **통합**: `backend/consistency_agent/agent.py` - `validate_contract_task` Celery 작업 (A1 → A3 순차 실행)

### 참조하는 곳

- `backend/fastapi/main.py` - `/api/validation/{contract_id}` 엔드포인트 (조회)
- `backend/consistency_agent/agent.py` - 검증 결과 업데이트
- `backend/consistency_agent/a3_node/a3_node.py` - A1 노드 결과 로드 (누락 조항 확인)
- `frontend/app.py` - Streamlit UI에서 검증 결과 표시

---

## 4. reports

**목적**: 최종 분석 보고서 저장

**현재 상태**: Phase 2 기능으로 미구현. 테이블은 정의되어 있으나 사용되지 않음.

### 스키마

| 컬럼명               | 타입     | 제약조건                   | 설명                    |
| -------------------- | -------- | -------------------------- | ----------------------- |
| `id`                 | Integer  | PRIMARY KEY, AUTOINCREMENT | 레코드 고유 ID          |
| `contract_id`        | String   | INDEX, NOT NULL            | 계약서 ID (외래키 역할) |
| `contract_type`      | String   | NOT NULL                   | 계약 유형               |
| `validation_date`    | DateTime | DEFAULT: utcnow()          | 검증 일시               |
| `overall_assessment` | JSON     | NULLABLE                   | 전체 평가               |
| `issues`             | JSON     | NULLABLE                   | 이슈 리스트             |
| `positive_points`    | JSON     | NULLABLE                   | 긍정적 평가             |
| `recommendations`    | JSON     | NULLABLE                   | 개선 권장사항           |
| `created_at`         | DateTime | DEFAULT: utcnow()          | 생성 일시               |

### 데이터 소스

- **생성 예정**: `backend/report_agent/agent.py` - `generate_report` Celery 작업 (Phase 2)
  - 현재는 빈 함수만 존재: `return {"status": "ok"}`

### 참조하는 곳

- 현재 미사용 (Phase 2에서 구현 예정)

---

## 5. token_usage

**목적**: Azure OpenAI API 토큰 사용량 추적 (비용 관리 및 모니터링)

### 스키마

| 컬럼명              | 타입     | 제약조건                   | 설명                             |
| ------------------- | -------- | -------------------------- | -------------------------------- |
| `id`                | Integer  | PRIMARY KEY, AUTOINCREMENT | 레코드 고유 ID                   |
| `contract_id`       | String   | INDEX, NOT NULL            | 계약서 ID (외래키 역할)          |
| `component`         | String   | NOT NULL                   | 호출한 컴포넌트                  |
| `api_type`          | String   | NOT NULL                   | API 유형                         |
| `model`             | String   | NOT NULL                   | 사용한 모델명                    |
| `prompt_tokens`     | Integer  | DEFAULT: 0                 | 입력 토큰 수                     |
| `completion_tokens` | Integer  | DEFAULT: 0                 | 출력 토큰 수 (chat completion만) |
| `total_tokens`      | Integer  | DEFAULT: 0                 | 총 토큰 수                       |
| `created_at`        | DateTime | DEFAULT: utcnow()          | 생성 일시                        |
| `extra_info`        | JSON     | NULLABLE                   | 추가 정보                        |

### component 값

- `classification_agent` - 분류 에이전트
- `consistency_agent` - 정합성 검증 에이전트
- `embedding_generator` - 임베딩 생성기

### api_type 값

- `chat_completion` - GPT 채팅 완성 API
- `embedding` - 임베딩 생성 API

### model 값

- `gpt-4o` - GPT-4 Omni 모델
- `gpt-4` - GPT-4 모델
- `text-embedding-3-large` - 임베딩 모델

### extra_info 구조 (실제)

**Classification Agent**:

```json
{
  "purpose": "contract_classification"
}
```

또는

```json
{
  "purpose": "similarity_calculation"
}
```

**Consistency Agent (Hybrid Searcher)**:

```json
{
  "purpose": "hybrid_search",
  "query_type": "article_matching"
}
```

**Consistency Agent (A3 Node)**:

```json
{
  "purpose": "content_comparison",
  "user_article_no": 5,
  "std_article_ids": ["제5조", "제6조"]
}
```

**Embedding Generator**:

```json
{
  "purpose": "user_contract_embedding",
  "batch_size": 10,
  "article_count": 20
}
```

### 데이터 소스

- `backend/classification_agent/agent.py` - `ClassificationAgent._log_token_usage()`
  - chat_completion: 분류 판단 시
  - embedding: 유사도 계산 시
- `backend/consistency_agent/hybrid_searcher.py` - `HybridSearcher._log_token_usage()`
  - embedding: 하이브리드 검색 시
- `backend/consistency_agent/a3_node/a3_node.py` - `ContentAnalysisNode._log_token_usage()`
  - chat_completion: 내용 비교 시
- `backend/shared/services/embedding_generator.py` - `EmbeddingGenerator._log_token_usage()`
  - embedding: 사용자 계약서 임베딩 생성 시

### 참조하는 곳

- `backend/fastapi/main.py` - `/api/token-usage/{contract_id}` 엔드포인트 (조회)

---

## 데이터 흐름

### 1. 계약서 업로드 및 분류

```
1. 사용자 업로드 (Streamlit)
   ↓
2. FastAPI: /api/upload
   → contract_documents 생성 (status: "uploaded")
   ↓
3. 파싱 (UserContractParser)
   → contract_documents 업데이트 (parsed_data, status: "parsed")
   ↓
4. 분류 작업 시작 (Celery)
   → contract_documents 업데이트 (status: "classifying")
   ↓
5. Classification Agent 실행
   → classification_results 생성
   → token_usage 기록 (여러 건)
   → contract_documents 업데이트 (status: "classified")
```

### 2. 정합성 검증

```
1. 사용자 검증 요청 (Streamlit)
   ↓
2. FastAPI: /api/validate/{contract_id}
   → classification_results 조회 (계약 유형 확인)
   → contract_documents 업데이트 (status: "validating")
   ↓
3. Consistency Agent 실행 (Celery - validate_contract_task)
   ↓
4. A1 노드 (완전성 검증 - check_completeness_task)
   → validation_results 생성/업데이트 (completeness_check)
   → completeness_check 필드에 매칭 결과 저장
     - matching_details: 전체 조항별 매칭 상세 정보
     - missing_standard_articles: 누락된 표준 조항 목록
     - missing_article_analysis: 누락 조항 재검증 결과
   ↓
5. A2 노드 (체크리스트 검증) - 미구현
   → validation_results 업데이트 (checklist_validation: {"status": "pending"})
   ↓
6. A3 노드 (내용 분석 - analyze_content_task)
   → A1의 completeness_check.matching_details 로드
   → 매칭된 조항들의 내용 비교 수행
   → validation_results 업데이트 (content_analysis)
   → token_usage 기록 (LLM 비교 시마다)
   ↓
7. 검증 완료
   → contract_documents 업데이트 (status: "validated")
```

**주요 특징**:

- A3는 A1의 매칭 결과를 재사용 (중복 검색 방지)
- A1의 `matching_details`에서 조항별 매칭 정보 로드
- A3는 매칭된 조항들의 내용만 LLM으로 비교

### 3. 결과 조회

```
1. Streamlit UI
   ↓
2. FastAPI: /api/classification/{contract_id}
   → classification_results 조회
   ↓
3. FastAPI: /api/validation/{contract_id}
   → validation_results 조회
   ↓
4. FastAPI: /api/token-usage/{contract_id}
   → token_usage 조회 (모든 레코드)
```

---

## 인덱스

### 자동 생성 인덱스

- `contract_documents.contract_id` (PRIMARY KEY)
- `classification_results.id` (PRIMARY KEY)
- `classification_results.contract_id` (INDEX)
- `validation_results.id` (PRIMARY KEY)
- `validation_results.contract_id` (INDEX)
- `reports.id` (PRIMARY KEY)
- `reports.contract_id` (INDEX)
- `token_usage.id` (PRIMARY KEY)
- `token_usage.contract_id` (INDEX)

---

## 외래키 관계

SQLite에서는 명시적인 외래키 제약조건을 사용하지 않지만, 논리적 관계는 다음과 같습니다:

```
contract_documents (1) ─── (0..1) classification_results
                     │
                     ├─── (0..1) validation_results
                     │
                     ├─── (0..1) reports
                     │
                     └─── (0..n) token_usage
```

- 하나의 계약서(`contract_documents`)는 최대 1개의 분류 결과(`classification_results`)를 가집니다
- 하나의 계약서는 최대 1개의 검증 결과(`validation_results`)를 가집니다
- 하나의 계약서는 최대 1개의 보고서(`reports`)를 가집니다
- 하나의 계약서는 여러 개의 토큰 사용 기록(`token_usage`)을 가집니다

---

## 데이터베이스 초기화

**함수**: `backend/shared/database.py` - `init_db()`

```python
def init_db():
    """데이터베이스 테이블 생성"""
    Base.metadata.create_all(bind=engine)
```

**호출 위치**: `backend/fastapi/main.py` - 애플리케이션 시작 시

---

## 환경 변수

```bash
DATABASE_URL=sqlite:///data/database/contracts.db
```

Docker 환경에서는 `/app/data/database/contracts.db` 경로 사용

---

## 주의사항

1. **JSON 필드 인코딩**: 한글 데이터를 위해 `ensure_ascii=False` 설정 사용
2. **동시성**: SQLite는 `check_same_thread=False` 설정으로 멀티스레드 환경 지원
3. **트랜잭션**: SQLAlchemy 세션을 통한 자동 트랜잭션 관리
4. **세션 관리**: FastAPI의 `Depends(get_db)`를 통한 자동 세션 생성/종료

---

## 실제 사용 예시

### 계약서 조회 (FastAPI)

```python
from backend.shared.database import get_db, ContractDocument

db = next(get_db())
contract = db.query(ContractDocument).filter(
    ContractDocument.contract_id == "550e8400-e29b-41d4-a716-446655440000"
).first()

# 파싱된 데이터 접근
articles = contract.parsed_data.get('articles', [])
first_article = articles[0]
print(f"제{first_article['number']}조: {first_article['title']}")
```

### 분류 결과 조회

```python
from backend.shared.database import get_db, ClassificationResult

db = next(get_db())
classification = db.query(ClassificationResult).filter(
    ClassificationResult.contract_id == contract_id
).first()

print(f"예측 유형: {classification.predicted_type}")
print(f"신뢰도: {classification.confidence:.2%}")
print(f"점수: {classification.scores}")
```

### 검증 결과 조회 (A1 매칭 정보)

```python
from backend.shared.database import get_db, ValidationResult

db = next(get_db())
validation = db.query(ValidationResult).filter(
    ValidationResult.contract_id == contract_id
).first()

# A1 완전성 검증 결과
completeness = validation.completeness_check
print(f"매칭: {completeness['matched_user_articles']}/{completeness['total_user_articles']}")
print(f"누락: {len(completeness['missing_standard_articles'])}개")

# 특정 조항의 매칭 정보
for detail in completeness['matching_details']:
    if detail['user_article_no'] == 5:
        print(f"제5조 매칭 결과: {detail['matched_articles']}")
        print(f"매칭 점수: {detail['matched_articles_details'][0]['combined_score']}")
```

### 검증 결과 조회 (A3 내용 분석)

```python
# A3 내용 분석 결과
content_analysis = validation.content_analysis
print(f"분석: {content_analysis['analyzed_articles']}/{content_analysis['total_articles']}")

# 특정 조항의 분석 정보
for article in content_analysis['article_analysis']:
    if article['user_article_no'] == 5:
        print(f"제5조 매칭: {article['std_article_id']}")
        print(f"유사도: {article['similarity']:.2%}")
        print(f"하위항목 비교: {len(article['sub_item_results'])}개")
```

### 토큰 사용량 조회

```python
from backend.shared.database import get_db, TokenUsage

db = next(get_db())
usages = db.query(TokenUsage).filter(
    TokenUsage.contract_id == contract_id
).all()

total_tokens = sum(u.total_tokens for u in usages)
print(f"총 토큰 사용량: {total_tokens:,}")

# 컴포넌트별 집계
from collections import defaultdict
by_component = defaultdict(int)
for u in usages:
    by_component[u.component] += u.total_tokens

for component, tokens in by_component.items():
    print(f"{component}: {tokens:,} tokens")
```

---

## 버전 정보

- **작성일**: 2025-11-02
- **최종 업데이트**: 2025-11-02
- **데이터베이스 버전**: 1.0
- **마이그레이션 도구**: Alembic (설정됨, 현재 미사용)
- **문서 버전**: 1.0 (실제 코드 분석 기반)
