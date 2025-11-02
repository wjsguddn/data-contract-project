# Implementation Plan - Consistency Agent A2 Node

## Overview

A2 노드(Checklist Validation) 구현을 위한 태스크 목록입니다. A1 노드의 매칭 결과를 기반으로 활용안내서 체크리스트를 LLM으로 검증합니다.

## Tasks

- [x] 1. 기본 인프라 및 데이터 구조 확인





- [x] 1.1 ValidationResult DB 모델 확인


  - checklist_validation 필드가 JSON 타입으로 존재하는지 확인
  - 필요시 마이그레이션 스크립트 작성
  - _Requirements: 5.1_

- [x] 1.2 체크리스트 JSON 파일 확인




  - data/chunked_documents/guidebook_chunked_documents/checklist_documents/ 경로 확인
  - 5종 계약 유형별 체크리스트 파일 존재 확인
  - JSON 구조 검증 (check_text, reference, global_id)
  - _Requirements: 2.1, 2.2_


- [x] 1.3 A1 매칭 결과 구조 확인





  - ValidationResult.completeness_check 구조 확인
  - matching_details 배열 구조 확인
  - matched_articles_global_ids 필드 존재 확인
  - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [ ] 2. ChecklistLoader 구현 (backend/consistency_agent/a2_node/)
- [x] 2.1 ChecklistLoader 클래스 기본 구조 구현


  - **파일 생성**: backend/consistency_agent/a2_node/checklist_loader.py
  - __init__ 메서드: 캐시 딕셔너리 초기화
  - 기본 속성 및 로거 설정
  - _Requirements: 2.1, 2.2, 8.2_

- [x] 2.2 체크리스트 파일 로드 구현

  - load_checklist 메서드 구현
  - contract_type 기반 파일 경로 생성
  - JSON 파일 읽기 및 파싱
  - 유효성 검증 (valid_types 체크)
  - _Requirements: 2.1, 2.2, 2.3_


- [ ] 2.3 체크리스트 캐싱 구현
  - 계약 유형별 캐시 저장
  - 캐시 히트 시 파일 재로드 방지
  - 로깅 추가
  - _Requirements: 8.2_

- [x] 2.4 Global ID 기반 필터링 구현

  - filter_by_global_ids 메서드 구현
  - global_id 리스트로 체크리스트 필터링
  - 중복 제거 (check_text 기준)
  - _Requirements: 2.4, 2.5, 2.6_


- [x] 2.5 에러 처리 구현

  - FileNotFoundError 처리
  - JSONDecodeError 처리
  - ValueError 처리 (잘못된 contract_type)
  - _Requirements: 7.2_

- [ ] 3. ChecklistVerifier 구현 (backend/consistency_agent/a2_node/)
- [x] 3.1 ChecklistVerifier 클래스 기본 구조 구현


  - **파일 생성**: backend/consistency_agent/a2_node/checklist_verifier.py
  - __init__ 메서드: AzureOpenAI 클라이언트 초기화
  - CONFIDENCE_THRESHOLD 상수 정의 (0.7)
  - _Requirements: 3.1, 3.2, 3.3_


- [ ] 3.2 단일 항목 검증 구현
  - verify_single 메서드 구현
  - LLM 프롬프트 생성 (사용자 조항 + 체크리스트 질문)
  - Azure OpenAI GPT-4 호출
  - JSON 응답 파싱 (result, evidence, confidence)
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_


- [ ] 3.3 배치 검증 구현
  - verify_batch 메서드 구현
  - 체크리스트 항목을 batch_size(10개)로 분할
  - 배치 프롬프트 생성 (번호 부여)
  - LLM 호출 및 응답 파싱

  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

- [ ] 3.4 배치 실패 시 폴백 구현
  - 배치 검증 실패 시 개별 검증으로 전환
  - 개별 검증도 실패 시 항목 건너뛰기

  - 에러 로깅
  - _Requirements: 4.6, 7.3_

- [ ] 3.5 표준 조항 컨텍스트 포함 검증 구현
  - verify_with_context 메서드 구현
  - 사용자 조항 + 표준 조항 + 체크리스트 프롬프트 생성

  - "표준계약서를 참고하여 더 정확히 판단" 지시 포함
  - LLM 호출 및 응답 파싱
  - _Requirements: 10.3, 10.4, 10.5, 10.6_

- [ ] 3.6 신뢰도 기반 재검증 구현
  - verify_with_low_confidence_handling 메서드 구현
  - 1차 검증 신뢰도 < 0.7 시 재검증 트리거

  - 표준 조항 로드 (_load_std_clause 호출)
  - 2차 검증 (verify_with_context 호출)
  - 재검증 후에도 신뢰도 < 0.7 시 UNCLEAR 처리
  - _Requirements: 10.1, 10.2, 10.7, 10.8_

- [x] 3.7 표준 조항 로드 구현

  - _load_std_clause 메서드 구현
  - 지식베이스에서 global_id로 청크 조회
  - base global_id 추출 및 매칭
  - 제목 + 내용 결합하여 반환
  - _Requirements: 10.4, 10.9_

- [x] 4. ChecklistCheckNode 메인 클래스 구현 (backend/consistency_agent/a2_node/)




- [x] 4.1 ChecklistCheckNode 클래스 기본 구조 구현


  - **파일 생성**: backend/consistency_agent/a2_node/a2_node.py
  - __init__ 메서드: 의존성 주입 (db_session, llm_client)
  - ChecklistLoader, ChecklistVerifier 초기화
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

- [x] 4.2 A1 매칭 결과 로드 구현


  - _load_a1_results 메서드 구현
  - ValidationResult.completeness_check 조회
  - ClassificationResult.confirmed_type 조회
  - contract_type 유효성 검증
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_

- [x] 4.3 사용자 조항 텍스트 로드 구현


  - _get_user_clause_text 메서드 구현
  - ContractDocument.parsed_data에서 조항 조회
  - 제목 + 내용 결합
  - _Requirements: 3.1_

- [x] 4.4 통계 계산 구현


  - _calculate_statistics 메서드 구현
  - total_checklist_items, verified_items 계산
  - passed_items (YES), failed_items (NO) 계산
  - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

- [x] 4.5 단일 조항 검증 로직 구현

  - 사용자 조항별로 순회
  - matched_articles_global_ids 추출
  - 관련 체크리스트 필터링
  - ChecklistVerifier.verify_batch 호출
  - 결과 수집
  - _Requirements: 2.4, 2.5, 3.1, 3.2, 4.1, 4.2_

- [x] 4.6 전체 체크리스트 검증 로직 구현

  - check_checklist 메서드 구현
  - A1 결과 로드
  - 체크리스트 로드
  - 모든 사용자 조항 순회하며 검증
  - 통계 계산
  - 최종 결과 구성
  - _Requirements: 모든 요구사항_

- [x] 4.7 진행 상황 로깅 구현

  - 각 조항 검증 시작/완료 로그
  - 체크리스트 항목 수 로그
  - 처리 시간 측정
  - _Requirements: 7.4, 7.5, 7.6_

- [x] 5. DB 저장 구현

- [x] 5.1 ValidationResult 저장 로직 구현

  - _checklist_save_db 메서드 구현 (Task 4에서 구현됨)
  - ValidationResult 조회 또는 생성
  - checklist_validation 필드에 결과 저장
  - DB 커밋
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7_

- [x] 5.2 에러 처리 구현


  - DB 저장 실패 시 에러 로깅
  - 트랜잭션 롤백
  - 예외 전파
  - _Requirements: 7.1, 7.2, 7.3_

- [x] 6. Consistency Agent 통합 (backend/consistency_agent/)



- [x] 6.1 agent.py에 A2 노드 호출 추가


  - **파일 수정**: backend/consistency_agent/agent.py
  - A1 완료 후 A2 노드 호출 로직 추가
  - ChecklistCheckNode 인스턴스 생성 및 실행
  - 에러 처리
  - _Requirements: 모든 요구사항_

- [x] 6.2 Celery Task 등록 (선택적)

  - A2 전용 Celery task 생성 (필요 시)
  - 또는 기존 validation task에 통합
  - _Requirements: 모든 요구사항_

- [x] 7. 프론트엔드 통합 (frontend/)





- [x] 7.1 체크리스트 결과 표시 함수 구현


  - **파일 수정**: frontend/app.py
  - display_checklist_results 함수 추가
  - 토글 버튼 구현
  - 통계 표시 (전체/통과/미충족)
  - _Requirements: 11.1, 11.2, 11.3_

- [x] 7.2 조항별 체크리스트 결과 표시

  - 조항 번호 및 제목 헤더
  - YES: 녹색 체크 아이콘 + evidence
  - NO: 빨간색 X 아이콘 + 메시지
  - UNCLEAR: 노란색 물음표 + 신뢰도 + 메시지
  - _Requirements: 11.4, 11.5, 11.6, 11.7, 11.8, 11.9, 11.10, 11.11, 11.12_

- [x] 7.3 API 엔드포인트 확인

  - **파일 확인/수정**: backend/fastapi/main.py
  - GET /api/validation/{contract_id} 엔드포인트 확인
  - checklist_validation 필드 포함 여부 확인
  - 필요 시 수정
  - _Requirements: 11.14_

- [ ] 8. 테스트 작성
- [ ] 8.1 ChecklistLoader 단위 테스트
  - 파일 로드 테스트
  - 캐싱 테스트
  - global_id 필터링 테스트
  - 에러 처리 테스트
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

- [ ] 8.2 ChecklistVerifier 단위 테스트
  - 단일 항목 검증 테스트
  - 배치 검증 테스트
  - 신뢰도 기반 재검증 테스트
  - 표준 조항 로드 테스트
  - UNCLEAR 처리 테스트
  - _Requirements: 3.1~3.9, 10.1~10.10_

- [ ] 8.3 ChecklistCheckNode 통합 테스트
  - A1 결과 로드 테스트
  - 전체 검증 플로우 테스트
  - 통계 계산 테스트
  - DB 저장 테스트
  - _Requirements: 모든 요구사항_

- [ ] 8.4 E2E 테스트
  - 실제 계약서로 A1 → A2 전체 플로우 테스트
  - 5종 계약 유형별 테스트
  - 프론트엔드 표시 확인
  - _Requirements: 모든 요구사항_

- [ ] 9. 문서화
- [ ] 9.1 코드 주석 및 docstring 작성
  - 모든 클래스 및 메서드에 docstring 추가
  - 복잡한 로직에 인라인 주석 추가
  - _Requirements: 모든 요구사항_

- [ ] 9.2 README 업데이트
  - A2 노드 설명 추가
  - 실행 방법 문서화
  - 환경 변수 설정 가이드
  - _Requirements: 모든 요구사항_

---

## Implementation Notes

### 파일 생성 위치
**모든 A2 노드 코어 파일은 `backend/consistency_agent/a2_node/` 디렉토리에 생성:**
- `checklist_loader.py` - 체크리스트 로드 및 필터링
- `checklist_verifier.py` - LLM 기반 검증 로직
- `a2_node.py` - 메인 오케스트레이터
- `__init__.py` - 모듈 초기화 (이미 존재)

**기타 수정 파일:**
- `backend/consistency_agent/agent.py` - A2 노드 통합
- `frontend/app.py` - 체크리스트 결과 표시
- `backend/fastapi/main.py` - API 엔드포인트 (필요 시)

### 실행 순서
1. **기본 인프라** (Task 1): DB 및 데이터 구조 확인
2. **핵심 컴포넌트** (Task 2-3): ChecklistLoader, ChecklistVerifier 구현
3. **메인 클래스** (Task 4): ChecklistCheckNode 통합
4. **DB 저장** (Task 5): ValidationResult 저장
5. **통합** (Task 6): Consistency Agent 연동
6. **프론트엔드** (Task 7): Streamlit UI 추가
7. **테스트** (Task 8): 단위/통합/E2E 테스트
8. **문서화** (Task 9): 주석 및 가이드

### 의존성
- Task 2-3은 Task 1 완료 후 병렬 진행 가능
- Task 4는 Task 2-3 완료 후 진행
- Task 5는 Task 4 완료 후 진행
- Task 6-7은 Task 5 완료 후 병렬 진행 가능
- Task 8-9는 Task 6-7 완료 후 진행

### 테스트 전략
- 각 컴포넌트 구현 후 즉시 단위 테스트 작성
- 통합 테스트는 메인 클래스 완성 후 작성
- E2E 테스트는 프론트엔드 통합 후 작성

### 핵심 기능
- **배치 처리**: 10개 체크리스트를 한 번의 LLM 호출로 처리
- **신뢰도 기반 재검증**: 신뢰도 < 0.7 시 표준 조항 컨텍스트 추가
- **UNCLEAR 상태**: 재검증 후에도 신뢰도 낮으면 수동 검토 요청
- **Global ID 매핑**: contract_type 기반 체크리스트 자동 로드

### 예상 소요 시간
- Task 1: 0.5시간
- Task 2: 2-3시간
- Task 3: 4-5시간
- Task 4: 3-4시간
- Task 5: 1-2시간
- Task 6: 1-2시간
- Task 7: 2-3시간
- Task 8: 3-4시간
- Task 9: 1-2시간
- **총 예상 시간**: 18-26시간

### 주의사항
- Azure OpenAI API 키 필수
- A1 노드가 먼저 완료되어야 A2 실행 가능
- 체크리스트 JSON 파일 5종 모두 필요
- LLM 호출 비용 고려 (배치 처리로 최적화)
