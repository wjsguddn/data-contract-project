# Requirements Document

## Introduction

Report Agent는 A1, A2, A3 노드의 검증 결과를 통합하고 정합성을 보정하여 최종 분석 보고서를 생성하는 시스템입니다. 특히 표준계약서 항목 단위로 여러 사용자 조항에서 발생한 상충되는 평가 결과를 우선순위 규칙에 따라 통합하고, 진짜 문제(누락, 불충분)만 보고서에 포함시킵니다.

## Glossary

- **Report Agent**: A1, A2, A3 결과를 통합하고 정합성을 보정하여 최종 보고서를 생성하는 에이전트
- **표준 항목 (Standard Clause)**: 표준계약서의 조, 항, 호 단위 항목 (예: 제5조 제2항)
- **사용자 조항 (User Article)**: 사용자 계약서의 조 단위 항목 (예: 제3조)
- **정합성 보정 (Consistency Correction)**: 동일 표준 항목에 대한 상충된 평가를 우선순위 규칙으로 통합하는 프로세스
- **상태 (Status)**: 표준 항목의 충족 상태 (sufficient, insufficient, missing)
- **A1 Node**: 완전성 검증 노드 (조항 매칭 및 누락 식별)
- **A2 Node**: 체크리스트 검증 노드 (활용안내서 기반 요구사항 검증)
- **A3 Node**: 내용 분석 노드 (조항별 충실도 평가)
- **Normalization**: A1/A3 결과를 표준 항목 ID 기준으로 재구조화하는 단계
- **Aggregation**: 동일 표준 항목에 대한 모든 평가 상태를 수집하는 단계
- **Conflict Resolution**: 상충된 평가에 우선순위 규칙을 적용하여 최종 상태를 결정하는 단계
- **Content Sync**: 보정된 상태에 따라 분석 텍스트를 자동으로 수정하는 단계

## Requirements

### Requirement 1: A1/A3 결과 1차 정규화 (사용자 조항 기준)

**User Story:** Report Agent 개발자로서, A1의 오탐지 재검증 결과와 A3의 조항별 분석 결과를 사용자 조항 기준으로 파싱하여 matched, insufficient, missing 항목을 명확히 구분하고 싶습니다.

#### Acceptance Criteria

1. WHEN A1 Stage 2 결과를 입력받으면, THE Report Agent SHALL missing_article_analysis를 순회하며 is_truly_missing이 true인 항목의 standard_article_id를 추출한다
2. WHEN A1에서 진짜 누락 항목을 추출하면, THE Report Agent SHALL 해당 표준 항목 ID와 모든 하위 항목 ID를 "overall_missing_clauses" 목록에 추가하고 사용자 조항과 무관한 전역 누락으로 분류한다
2.5. WHEN A1 Stage 2에서 is_truly_missing이 false인 항목(오탐지)을 발견하면, THE Report Agent SHALL 해당 항목을 무시하고 A3 결과에서만 처리한다
3. WHEN A3 분석 결과를 입력받으면, THE Report Agent SHALL 각 사용자 조항(article_analysis)을 순회하며 suggestions 필드에서 missing_items와 insufficient_items를 추출한다
4. WHEN missing_items 또는 insufficient_items의 텍스트를 파싱하면, THE Report Agent SHALL 정규식을 사용하여 "제N조", "제N조 제M항", "제N조 제M호" 형식의 표준 조항 참조를 추출한다
5. WHEN 표준 조항 참조를 추출하면, THE Report Agent SHALL KnowledgeBaseLoader를 사용하여 해당 contract_type의 모든 표준계약서 청크를 로드한다
6. WHEN 표준계약서 청크를 검색하면, THE Report Agent SHALL 추출된 조/항/호 번호와 매칭되는 global_id를 찾아 정확한 ID 형식(예: "urn:std:provide:art:014:cla:002")을 확보한다
7. WHERE "제N조" 형식(조 단위)으로만 언급된 경우, THE Report Agent SHALL 해당 조의 모든 하위 항목(sub, cla) global_id를 자동으로 포함한다
8. WHEN 사용자 조항별 파싱이 완료되면, THE Report Agent SHALL 사용자 조항 번호를 키로 하는 딕셔너리를 생성하고 각 조항의 insufficient, missing 표준 항목 ID 목록만 저장한다
9. WHERE A3 결과에 matched_articles가 포함되어 있으나 동일 조항에 대해 insufficient 또는 missing 평가도 존재하는 경우, THE Report Agent SHALL matched 상태를 무시하고 insufficient 또는 missing 상태만 저장한다
10. WHERE 정규식 매칭이 실패하거나 global_id를 찾을 수 없는 경우, THE Report Agent SHALL 해당 항목을 경고 로그에 기록하고 원본 텍스트를 보존한다
11. WHERE A3 결과에 matched_articles만 있고 insufficient/missing 평가가 없는 경우, THE Report Agent SHALL 해당 표준 조항을 Step 1에 저장하지 않는다
12. WHERE A1에서 누락으로 판단된 항목이 A3에서 특정 사용자 조항의 insufficient 또는 missing으로 언급된 경우, THE Report Agent SHALL A3의 사용자 조항 기준 분류를 우선하고 A1의 전역 누락 목록에서 제거한다

### Requirement 2: 2차 정규화 (표준 항목 기준 재집계)

**User Story:** Report Agent 개발자로서, 1차 정규화된 사용자 조항 기준 데이터를 표준 항목 기준으로 재집계하여 교차 검증이 가능하도록 하고 싶습니다.

#### Acceptance Criteria

1. WHEN 1차 정규화가 완료되면, THE Report Agent SHALL 모든 사용자 조항의 결과를 순회하며 표준 항목 global_id를 키로 하는 딕셔너리를 생성한다
2. WHEN 표준 항목별로 데이터를 집계하면, THE Report Agent SHALL 각 표준 항목에 대해 어느 사용자 조항에서 어떤 상태(sufficient, insufficient, missing)로 평가되었는지 기록한다
3. WHEN 표준 항목별 집계가 완료되면, THE Report Agent SHALL 각 표준 항목에 대해 관련 사용자 조항 목록과 상태 목록을 포함하는 데이터 구조를 생성한다
4. WHERE 동일 표준 항목이 여러 사용자 조항에서 언급된 경우, THE Report Agent SHALL 모든 평가 상태를 배열로 보존한다

### Requirement 3: 상태 통합 및 충돌 해소 (규칙 기반)

**User Story:** Report Agent 개발자로서, 동일한 표준 항목에 대해 여러 사용자 조항에서 상충되는 평가가 있을 때 기본 우선순위 규칙에 따라 1차 판단을 하고 싶습니다.

#### Acceptance Criteria

1. WHEN 동일 표준 항목에 대해 "sufficient" 평가가 하나라도 존재하면, THE Report Agent SHALL 1차 판단을 "sufficient"로 설정한다
2. WHEN 동일 표준 항목에 대해 "sufficient" 평가가 없고 "insufficient" 평가가 하나라도 존재하면, THE Report Agent SHALL 1차 판단을 "insufficient"로 설정한다
3. WHEN 동일 표준 항목에 대해 "missing" 평가만 존재하면, THE Report Agent SHALL 1차 판단을 "missing"으로 설정한다
4. WHEN 1차 판단이 완료되면, THE Report Agent SHALL 기본 우선순위 규칙 "sufficient > insufficient > missing"을 적용한다
5. WHERE 동일 상태의 평가가 여러 개 존재하는 경우, THE Report Agent SHALL 모든 평가를 배열로 보존하여 LLM 재검증 단계로 전달한다

### Requirement 3.5: LLM 기반 충돌 해소

**User Story:** Report Agent 개발자로서, 동일 표준 항목에 대해 상충되는 평가(insufficient + missing 등)가 있을 때 LLM을 활용하여 최종 상태를 정확히 판단하고 싶습니다.

#### Acceptance Criteria

1. WHEN 동일 표준 항목에 대해 서로 다른 상태(insufficient, missing) 평가가 2개 이상 존재하면, THE Report Agent SHALL A3 원본 결과에서 해당 사용자 조항들의 분석 텍스트를 추출하고 LLM에게 최종 상태 판단을 요청한다
2. WHEN LLM에게 판단을 요청하면, THE Report Agent SHALL 표준 항목의 전체 내용(global_id로 청크 로드), 각 사용자 조항의 평가 상태, A3 원본 분석 텍스트를 포함한 프롬프트를 생성한다
3. WHEN LLM이 최종 상태(sufficient, insufficient, missing)를 반환하면, THE Report Agent SHALL 해당 상태를 최종 상태로 채택하고 LLM의 판단 근거를 로그에 기록한다
4. WHERE LLM이 "sufficient"로 판단하면, THE Report Agent SHALL 해당 항목을 보고서에서 제외하고 보정 이유를 correction_log에 기록한다
5. WHERE LLM이 "insufficient"로 판단하면, THE Report Agent SHALL Step 3 결과에 "insufficient" 상태의 사용자 조항 ID와 A3 원본 분석 텍스트를 저장하고 "missing" 상태의 평가는 제거한다
6. WHERE LLM이 "missing"으로 판단하면, THE Report Agent SHALL Step 3 결과에 "missing" 상태의 사용자 조항 ID와 A3 원본 분석 텍스트를 저장하고 "insufficient" 상태의 평가는 제거한다
7. WHERE LLM이 "sufficient"로 판단하면, THE Report Agent SHALL Step 3 결과에서 해당 표준 항목과 관련된 모든 평가를 제거한다
8. WHERE 동일 상태(insufficient + insufficient 또는 missing + missing)의 평가가 여러 개 존재하는 경우, THE Report Agent SHALL 첫 번째 사용자 조항의 A3 원본 분석 텍스트를 Step 3에 저장하고 나머지는 제거한다

### Requirement 4: 보고서 필터링

**User Story:** 사용자로서, 실제로 문제가 있는 항목(누락, 불충분)만 보고서에서 확인하고 충족된 항목은 보고 싶지 않습니다.

#### Acceptance Criteria

1. WHEN 표준 항목의 최종 상태가 "sufficient"이면, THE Report Agent SHALL 해당 항목을 최종 보고서에서 제외한다
2. WHEN 표준 항목의 최종 상태가 "insufficient" 또는 "missing"이면, THE Report Agent SHALL 해당 항목을 최종 보고서에 포함한다
3. WHEN 보고서를 생성하면, THE Report Agent SHALL 전체 표준 항목 수, sufficient 항목 수, insufficient 항목 수, missing 항목 수를 요약 통계로 제공한다
4. WHERE 보정 과정에서 상태가 변경된 항목이 있는 경우, THE Report Agent SHALL 보정 로그를 별도로 기록하여 추적 가능하도록 한다
5. WHERE 디버깅 모드가 활성화된 경우, THE Report Agent SHALL 제외된 항목도 보정 이유와 함께 로그에 기록한다

### Requirement 5: 텍스트 동기화

**User Story:** Report Agent 개발자로서, 보정된 상태에 따라 기존 분석 텍스트도 자동으로 수정하여 일관성을 유지하고 싶습니다.

#### Acceptance Criteria

1. WHEN 표준 항목의 상태가 "missing"에서 "sufficient"로 변경되면, THE Report Agent SHALL 해당 항목의 분석 텍스트에서 "누락" 표현을 제거하거나 "다른 조항에서 반영됨"으로 교체한다
2. WHEN 표준 항목의 상태가 "missing"에서 "insufficient"로 변경되면, THE Report Agent SHALL 분석 텍스트를 "완전 누락"에서 "부분적 불충분"으로 수정한다
3. WHEN 표준 항목의 상태가 "insufficient"에서 "sufficient"로 변경되면, THE Report Agent SHALL 분석 텍스트에서 "불충분" 표현을 제거하고 "보완됨" 문장으로 교체한다
4. WHERE 원본 분석 텍스트가 존재하지 않는 경우, THE Report Agent SHALL 보정된 상태에 맞는 기본 텍스트를 생성한다
5. WHERE 여러 사용자 조항이 관련된 경우, THE Report Agent SHALL 모든 관련 조항 정보를 텍스트에 포함하여 맥락을 제공한다

### Requirement 6: 최종 보고서 생성

**User Story:** 사용자로서, 정합성이 보정된 최종 결과를 구조화된 JSON 형식으로 받아 프론트엔드에서 표시하고 싶습니다.

#### Acceptance Criteria

1. WHEN 모든 보정이 완료되면, THE Report Agent SHALL 전체 계약서 누락 조항과 사용자 조항별 분석을 포함하는 JSON 구조를 생성한다
2. WHEN 보고서를 생성하면, THE Report Agent SHALL 전체 요약 통계(total, sufficient, insufficient, missing)를 최상위 레벨에 포함한다
3. WHEN 전체 계약서 누락 조항(overall_missing_clauses)이 존재하면, THE Report Agent SHALL 각 누락 조항의 global_id, 제목, A1 분석 텍스트를 포함한다
4. WHEN 사용자 조항별 분석을 생성하면, THE Report Agent SHALL 각 사용자 조항에 대해 조항 번호, 제목, insufficient 목록, missing 목록을 포함한다
5. WHEN insufficient 또는 missing 항목을 포함하면, THE Report Agent SHALL 각 항목의 표준 조항 global_id, 제목, A3 원본 분석 텍스트를 포함한다

### Requirement 6.5: 프론트엔드 보고서 표시

**User Story:** 사용자로서, 검증 완료 후 [리포트 보기] 버튼을 클릭하여 전용 페이지에서 최종 보고서를 확인하고 싶습니다.

#### Acceptance Criteria

1. WHEN 검증이 완료되면(status: "completed"), THE Frontend SHALL [리포트 보기] 버튼을 표시한다
2. WHEN 사용자가 [리포트 보기] 버튼을 클릭하면, THE Frontend SHALL 리포트 전용 페이지로 이동한다
3. WHEN 리포트 페이지를 표시하면, THE Frontend SHALL 계약서 정보(파일명, 유형, 검증일)를 헤더에 표시한다
4. WHEN 요약 통계를 표시하면, THE Frontend SHALL 전체 표준 조항 수, 충족/불충분/누락 개수와 비율을 시각적으로 표시한다
5. WHEN 전체 계약서 누락 조항이 있으면, THE Frontend SHALL "전체 계약서에서 누락된 조항" 섹션을 별도로 표시한다
6. WHEN 사용자 조항별 분석을 표시하면, THE Frontend SHALL 각 사용자 조항을 카드 형식으로 표시하고 불충분/누락 항목을 구분하여 표시한다
7. WHEN 분석 텍스트를 표시하면, THE Frontend SHALL 마크다운 형식을 렌더링하고 가독성을 위해 적절한 스타일을 적용한다
8. WHERE 보고서가 아직 생성 중이면(status: "generating_report"), THE Frontend SHALL 로딩 상태를 표시한다

### Requirement 7: 데이터베이스 저장

**User Story:** Report Agent 개발자로서, 생성된 중간 결과와 최종 보고서를 데이터베이스에 저장하여 디버깅 및 이후 조회에 활용하고 싶습니다.

#### Acceptance Criteria

1. WHEN 1차 정규화(사용자 조항 기준)가 완료되면, THE Report Agent SHALL ValidationResult 테이블의 report_step1_normalized 필드에 사용자 조항별 matched/insufficient/missing 표준 항목 ID 목록과 A1 전역 누락 목록(overall_missing_clauses)을 JSON 형식으로 저장한다
2. WHEN 2차 정규화(표준 항목 기준)가 완료되면, THE Report Agent SHALL ValidationResult 테이블의 report_step2_aggregated 필드에 표준 항목별 사용자 조항 목록과 상태 목록을 JSON 형식으로 저장한다
3. WHEN 충돌 해소(LLM 재검증 포함)가 완료되면, THE Report Agent SHALL ValidationResult 테이블의 report_step3_resolved 필드에 보정된 사용자 조항별 표준 항목 ID와 A3 원본 분석 텍스트를 JSON 형식으로 저장한다
4. WHEN 최종 보고서가 생성되면, THE Report Agent SHALL ValidationResult 테이블의 final_report 필드에 JSON 형식으로 저장한다
5. WHEN 데이터베이스에 저장하면, THE Report Agent SHALL 각 단계별 처리 시간, 보정 항목 수를 메타데이터로 함께 저장한다
6. WHEN 저장이 실패하면, THE Report Agent SHALL 최대 3회까지 재시도하고 실패 시 에러를 로깅한다
7. WHERE 동일 contract_id에 대한 기존 보고서가 있는 경우, THE Report Agent SHALL 기존 보고서를 덮어쓴다
8. WHERE 보고서 생성 중 오류가 발생한 경우, THE Report Agent SHALL 완료된 단계까지의 부분 결과를 저장하고 오류 정보를 error_log 필드에 기록한다

### Requirement 8: 비동기 처리 및 상태 관리

**User Story:** 시스템 관리자로서, Report Agent가 A1, A2, A3 완료 후 자동으로 실행되고 진행 상태를 추적할 수 있기를 원합니다.

#### Acceptance Criteria

1. WHEN A1, A2, A3 노드가 모두 완료되면, THE Report Agent SHALL Celery 태스크로 자동 실행된다
2. WHEN Report Agent가 실행되면, THE Report Agent SHALL ValidationResult의 status 필드를 "generating_report"로 업데이트한다
3. WHEN 보고서 생성이 완료되면, THE Report Agent SHALL status 필드를 "completed"로 업데이트한다
4. WHEN 보고서 생성이 실패하면, THE Report Agent SHALL status 필드를 "failed"로 업데이트하고 에러 메시지를 기록한다
5. WHERE 사용자가 진행 상태를 조회하면, THE System SHALL 현재 단계(정규화, 보정, 생성 등)와 진행률을 반환한다

### Requirement 9: 로깅 및 디버깅

**User Story:** 개발자로서, Report Agent의 보정 과정을 상세히 추적하여 문제 발생 시 디버깅할 수 있기를 원합니다.

#### Acceptance Criteria

1. WHEN 정규화 단계를 수행하면, THE Report Agent SHALL 파싱된 표준 항목 수와 관련 사용자 조항 수를 로깅한다
2. WHEN 충돌 해소를 수행하면, THE Report Agent SHALL 상태가 변경된 각 항목에 대해 변경 전후 상태와 이유를 로깅한다
3. WHEN 보고서 필터링을 수행하면, THE Report Agent SHALL 제외된 항목 수와 포함된 항목 수를 로깅한다
4. WHERE 디버깅 모드가 활성화된 경우, THE Report Agent SHALL 각 단계의 중간 결과를 JSON 파일로 저장한다
5. WHERE 예외가 발생한 경우, THE Report Agent SHALL 스택 트레이스와 함께 입력 데이터를 로깅하여 재현 가능하도록 한다

### Requirement 10: 성능 최적화

**User Story:** 시스템 관리자로서, Report Agent가 대량의 조항을 처리할 때도 합리적인 시간 내에 완료되기를 원합니다.

#### Acceptance Criteria

1. WHEN 표준 항목이 50개 이하인 경우, THE Report Agent SHALL 5초 이내에 보고서를 생성한다
2. WHEN 표준 항목이 100개 이하인 경우, THE Report Agent SHALL 10초 이내에 보고서를 생성한다
3. WHEN 정규화 단계를 수행하면, THE Report Agent SHALL 표준 항목 ID를 키로 하는 해시맵을 사용하여 O(1) 조회 성능을 보장한다
4. WHERE 메모리 사용량이 임계치를 초과하는 경우, THE Report Agent SHALL 배치 처리로 전환하여 메모리 사용량을 제한한다
5. WHERE 동일 contract_id에 대한 중복 요청이 발생한 경우, THE Report Agent SHALL 이미 실행 중인 태스크를 재사용하고 중복 실행을 방지한다
