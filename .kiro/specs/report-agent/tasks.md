# Implementation Plan: Report Agent

## 1. 프로젝트 구조 및 기본 설정

Report Agent의 기본 프로젝트 구조와 핵심 인터페이스를 생성합니다.

- `backend/report_agent/` 디렉토리 구조 생성
- `backend/report_agent/__init__.py` 생성
- `backend/report_agent/agent.py` 생성 (메인 ReportAgent 클래스 스켈레톤)
- `backend/report_agent/exceptions.py` 생성 (커스텀 예외 클래스)
- _Requirements: Requirement 1, 7, 9_

## 2. Step1Normalizer 구현

A1과 A3 결과를 파싱하여 사용자 조항 기준으로 정규화하는 Step1Normalizer 클래스를 구현합니다.

- [ ] 2.1 `backend/report_agent/step1_normalizer.py` 생성 및 Step1Normalizer 클래스 작성
  - `__init__()` 구현 (KnowledgeBaseLoader 의존성)
  - `normalize()` 메인 메서드 구현
  - _Requirements: Requirement 1_

- [ ] 2.2 A1 파싱 메서드 구현
  - `_parse_a1_missing()` 구현 (`is_truly_missing: true` 항목 추출)
  - `_parse_a1_matching()` 구현 (매칭된 표준 조항 추출)
  - `_expand_article_to_clauses()` 구현 (조 단위 참조를 모든 하위 항목으로 확장)
  - _Requirements: Requirement 1.1, 1.2, 1.7_

- [ ] 2.3 A3 파싱 메서드 구현
  - `_parse_a3_results()` 구현 (matched, insufficient, missing 항목 추출)
  - `_extract_clause_references()` 구현 (정규식으로 "제N조", "제N조 제M항" 패턴 파싱)
  - 조 단위 참조(예: "제23조") 처리 (모든 하위 항목으로 확장)
  - _Requirements: Requirement 1.3, 1.4, 1.5, 1.6, 1.7_

- [ ] 2.4 중복 제거 로직 구현
  - `_remove_duplicates()` 구현 (A3에서 언급된 항목을 overall_missing_clauses에서 제거)
  - A1 오탐지 복구 처리 (A3에서 언급된 항목은 overall_missing에 포함 안 함)
  - _Requirements: Requirement 1.12_

## 3. Step2Aggregator 구현

표준 항목 기준으로 재집계하고 충돌을 감지하는 Step2Aggregator 클래스를 구현합니다.

- [ ] 3.1 `backend/report_agent/step2_aggregator.py` 생성 및 Step2Aggregator 클래스 작성
  - `aggregate()` 메인 메서드 구현
  - `_group_by_std_clause()` 구현 (표준 항목 ID 기준으로 재구조화)
  - _Requirements: Requirement 2_

- [ ] 3.2 충돌 감지 로직 구현
  - `_detect_conflicts()` 구현 (충돌하는 평가 식별: insufficient + missing)
  - 서로 다른 상태가 여러 개 존재하면 `has_conflict: true` 표시
  - _Requirements: Requirement 2.2, 2.3_

## 4. Step3Resolver 구현

우선순위 규칙과 LLM 재검증을 사용하여 충돌을 해소하는 Step3Resolver 클래스를 구현합니다.

- [ ] 4.1 `backend/report_agent/step3_resolver.py` 생성 및 Step3Resolver 클래스 작성
  - `__init__()` 구현 (LLM 클라이언트 의존성)
  - `resolve()` 메인 메서드 구현
  - _Requirements: Requirement 3, 3.5_

- [ ] 4.2 우선순위 규칙 구현
  - `_apply_priority_rules()` 구현 ("sufficient > insufficient > missing" 로직)
  - 충돌 없는 경우 처리 (단일 상태)
  - _Requirements: Requirement 3.1, 3.2, 3.3, 3.4_

- [ ] 4.3 LLM 충돌 해소 구현
  - `_llm_verify_conflict()` 구현 (충돌하는 평가에 대해 LLM 호출)
  - 충돌 해소용 프롬프트 템플릿 작성
  - LLM 응답 파싱하여 최종 상태 추출 (sufficient/insufficient/missing)
  - _Requirements: Requirement 3.5.1, 3.5.2, 3.5.3_

- [ ] 4.4 해소 결과 적용 구현
  - `_apply_resolution()` 구현 (LLM 판단에 따라 user_articles 업데이트)
  - LLM 최종 상태에 따라 충돌 항목 제거
  - A3 원본 분석 텍스트 유지
  - _Requirements: Requirement 3.5.5, 3.5.6, 3.5.7, 3.5.8_

- [ ] 4.5 분석 텍스트 첨부 구현
  - `_attach_analysis_text()` 구현 (A3 원본 분석 텍스트 추가)
  - 각 insufficient/missing 항목에 대해 A3 결과에서 분석 텍스트 가져오기
  - overall_missing_clauses 항목에 대해 LLM 분석 생성
  - _Requirements: Requirement 3.5.5, 3.5.6_

## 5. Step4Reporter 구현

통계 및 포맷팅을 포함한 최종 보고서를 생성하는 Step4Reporter 클래스를 구현합니다.

- [ ] 5.1 `backend/report_agent/step4_reporter.py` 생성 및 Step4Reporter 클래스 작성
  - `generate_final_report()` 메인 메서드 구현
  - 계약서 메타데이터 추가 (contract_id, contract_type, generated_at)
  - _Requirements: Requirement 6_

- [ ] 5.2 통계 계산 구현
  - `_calculate_statistics()` 구현 (total, sufficient, insufficient, missing 개수 계산)
  - sufficient 개수 계산: total - insufficient - missing
  - _Requirements: Requirement 6.2_

- [ ] 5.3 overall_missing_clauses 포맷팅 구현
  - `_format_overall_missing()` 구현 (제목 및 분석 텍스트 추가)
  - KnowledgeBaseLoader에서 표준 조항 제목 가져오기
  - _Requirements: Requirement 6.3_

- [ ] 5.4 user_articles 포맷팅 구현
  - `_format_user_articles()` 구현 (matched, insufficient, missing 항목에 제목 추가)
  - 원본 계약서 데이터에서 사용자 조항 제목 가져오기
  - KnowledgeBaseLoader에서 표준 조항 제목 가져오기
  - _Requirements: Requirement 6.4, 6.5_

## 6. ReportAgent 메인 클래스 통합

모든 컴포넌트를 메인 ReportAgent 클래스에 통합하고 전체 파이프라인을 구현합니다.

- [ ] 6.1 ReportAgent 메인 워크플로우 구현
  - `generate_report()` 메서드 구현 (Step 1-4 오케스트레이션)
  - `_load_input_data()` 구현 (데이터베이스에서 A1, A3 결과 가져오기)
  - Step1 → Step2 → Step3 → Step4 체인 연결
  - _Requirements: Requirement 1-6_

- [ ] 6.2 데이터베이스 작업 구현
  - `_save_to_db()` 구현 (Step 1, 2, 3 및 최종 보고서를 ValidationResult 테이블에 저장)
  - `report_step1_normalized`, `report_step2_aggregated`, `report_step3_resolved`, `final_report` 필드에 저장
  - `status` 필드 업데이트 ("generating_report" → "completed")
  - _Requirements: Requirement 7.1, 7.2, 7.3, 7.4, 7.5_

- [ ] 6.3 에러 처리 구현
  - 각 단계에 try-catch 블록 추가
  - LLM 호출 재시도 로직 구현 (최대 3회)
  - 데이터베이스 저장 재시도 로직 구현 (최대 3회)
  - 실패 시 부분 결과 저장
  - _Requirements: Requirement 7.6, 7.8, 9.5_

- [ ] 6.4 로깅 구현
  - 각 단계별 로깅 추가 (정규화, 집계, 해소, 보고서 생성)
  - 충돌 해소 및 상태 변경 로깅
  - 제외/포함 항목 개수 로깅
  - _Requirements: Requirement 9.1, 9.2, 9.3_

## 7. Celery 태스크 통합

비동기 실행을 위해 Report Agent를 Celery와 통합합니다.

- [ ] 7.1 Report Agent용 Celery 태스크 생성
  - `backend/report_agent/tasks.py` 생성 및 `generate_report_task()` 작성
  - A1, A2, A3 완료 후 실행되도록 설정
  - 실행 중 ValidationResult status 필드 업데이트
  - _Requirements: Requirement 8.1, 8.2, 8.3, 8.4_

- [ ] 7.2 Consistency Agent에서 Report Agent 트리거 추가
  - `backend/consistency_agent/agent.py` 수정 (A3 완료 후 Report Agent 태스크 호출)
  - contract_id를 Report Agent 태스크에 전달
  - _Requirements: Requirement 8.1_

## 8. API 엔드포인트 추가

최종 보고서를 조회하는 FastAPI 엔드포인트를 추가합니다.

- [ ] 8.1 보고서 조회 엔드포인트 생성
  - `backend/fastapi/main.py`에 `GET /api/report/{contract_id}` 엔드포인트 추가
  - ValidationResult 테이블에서 final_report 반환
  - 보고서가 없으면 404 처리
  - _Requirements: Requirement 6, 8.5_

- [ ] 8.2 보고서 상태 엔드포인트 추가
  - `GET /api/report/{contract_id}/status` 엔드포인트 추가
  - 현재 상태 반환 (generating_report, completed, failed)
  - 가능한 경우 진행 정보 반환
  - _Requirements: Requirement 8.5_

## 9. 프론트엔드 리포트 페이지 구현

최종 보고서를 표시하는 프론트엔드 리포트 페이지를 구현합니다.

- [ ] 9.1 검증 결과 페이지에 리포트 버튼 추가
  - `frontend/app.py`에 [리포트 보기] 버튼 추가 (status가 "completed"일 때)
  - 버튼 클릭 시 리포트 페이지로 이동
  - _Requirements: Requirement 6.5.1, 6.5.2_

- [ ] 9.2 리포트 페이지 레이아웃 생성
  - 리포트 표시용 새 Streamlit 페이지 생성
  - 계약서 정보 헤더 추가 (파일명, 유형, 검증일)
  - 시각적 지표가 포함된 요약 통계 섹션 추가
  - _Requirements: Requirement 6.5.3, 6.5.4_

- [ ] 9.3 overall_missing_clauses 섹션 구현
  - "전체 계약서에서 누락된 조항" 섹션 표시
  - 각 누락 조항의 제목 및 분석 표시
  - _Requirements: Requirement 6.5.5_

- [ ] 9.4 user_articles 섹션 구현
  - 각 사용자 조항을 카드 형식으로 표시
  - matched 조항은 ✅ 표시
  - insufficient 조항은 ⚠️ 표시 및 분석 표시
  - missing 조항은 ❌ 표시 및 분석 표시
  - _Requirements: Requirement 6.5.6_

- [ ] 9.5 마크다운 렌더링 구현
  - 분석 텍스트를 마크다운 형식으로 렌더링
  - 가독성을 위한 적절한 스타일 적용
  - _Requirements: Requirement 6.5.7_

- [ ] 9.6 로딩 상태 추가
  - status가 "generating_report"일 때 로딩 스피너 표시
  - 2초마다 상태 업데이트 폴링
  - _Requirements: Requirement 6.5.8_

## 10. 통합 테스트 및 검증

실제 데이터로 전체 Report Agent 파이프라인을 테스트합니다.

- [ ] 10.1 테스트 데이터 생성
  - 다양한 시나리오의 샘플 A1 및 A3 결과 준비
  - 충돌 케이스 포함 (insufficient + missing)
  - A1 오탐지 케이스 포함
  - _Requirements: All requirements_

- [ ] 10.2 Step 1-4 개별 테스트
  - 샘플 A1/A3 데이터로 Step1Normalizer 테스트
  - Step 1 출력으로 Step2Aggregator 테스트
  - Step 2 출력 및 충돌로 Step3Resolver 테스트
  - Step 3 출력으로 Step4Reporter 테스트
  - _Requirements: All requirements_

- [ ] 10.3 엔드투엔드 파이프라인 테스트
  - A1/A3 입력부터 최종 보고서까지 전체 파이프라인 실행
  - 모든 단계의 데이터베이스 저장 검증
  - 최종 보고서 구조 및 내용 검증
  - _Requirements: All requirements_

- [ ] 10.4 프론트엔드 리포트 페이지 테스트
  - status가 "completed"일 때 리포트 버튼 표시 확인
  - 리포트 페이지의 모든 섹션 올바르게 표시 확인
  - 마크다운 렌더링 및 스타일 확인
  - _Requirements: Requirement 6.5_

