# Product Overview

## 데이터 표준계약 검증 시스템

AI 기반 한국어 데이터 계약서 분석 및 검증 시스템으로, 5종 표준계약서를 기준으로 사용자 계약서를 분류하고 정합성을 검증합니다.

### Core Functionality
- **Document Upload**: Streamlit 웹 인터페이스를 통한 DOCX 계약서 업로드
- **AI Classification**: RAG + LLM을 활용한 5종 표준계약 유형 자동 분류
- **Hybrid Search**: FAISS(벡터) + Whoosh(키워드) 하이브리드 검색
- **Consistency Validation**: 3단계 정합성 검증 (완전성, 체크리스트, 내용 분석)
- **Report Generation**: 상세 분석 보고서 및 개선 제안 제공

### Key Features

#### Phase 1 (완료)
- DOCX 문서 파싱 및 구조 추출 ("제n조" 패턴)
- AI 기반 계약 유형 분류 (5종: 제공형, 창출형, 가공형, 중개거래형 2종)
- 하이브리드 검색 기반 유사도 매칭
- 실시간 분류 결과 및 신뢰도 점수 표시
- 사용자 분류 검토 및 수정 인터페이스
- Celery + Redis 비동기 처리
- 토큰 사용량 추적 및 모니터링

#### Phase 2 (구현 중)
- **A1 Node**: 완전성 검증 (조항 매칭, 누락 조항 식별)
- **A2 Node**: 체크리스트 검증 (활용안내서 기반)
- **A3 Node**: 내용 분석 (조항별 충실도 평가)
- 병렬 처리 아키텍처 (A1-Stage1 → [A1-Stage2 || A2 || A3])
- 맥락 기반 유연한 검증 (과도한 규격화 방지)
- 상세 검증 보고서 생성

#### Phase 3 (계획)
- VLM 기반 비정형 계약서 파싱
- PDF/DOCX 보고서 다운로드
- 다국어 지원 (영어 계약서)
- 계약서 템플릿 생성 기능

### Target Users
- 법무 전문가 및 계약 관리자
- 데이터 거래 플랫폼 운영자
- 표준계약서 준수가 필요한 조직
- 계약서 품질 개선이 필요한 기업

### System Architecture
- **마이크로서비스**: 각 Agent별 독립 컨테이너
- **비동기 처리**: Redis + Celery 메시지 큐
- **하이브리드 AI**: 임베딩 + LLM 결합 분류
- **확장 가능**: Docker Compose 기반 배포

### Current Status
- **Phase 1**: 완료 (분류 시스템)
- **Phase 2**: 구현 중 (검증 시스템)
- **지원 형식**: 구조화된 DOCX ("제n조" 형식)
- **필수 요구사항**: Azure OpenAI 자격 증명