# 챗봇 에이전트 동작 흐름 분석

## 개요

챗봇 에이전트는 **LangGraph 기반 자율 탐색 에이전트**로, 사용자 질문에 대해 반복적인 사고-행동-평가 루프를 통해 답변을 생성합니다.

## 전체 아키텍처

```
사용자 질문
    ↓
ChatbotOrchestrator (진입점)
    ↓
AutonomousAgent (LangGraph 워크플로우)
    ↓
[check_tool_needed → planner → executor → evaluator → respond]
    ↓
최종 답변
```

---

## 1단계: 진입점 (ChatbotOrchestrator)

### 파일: `backend/chatbot_agent/agent.py`

### 메서드: `process_message()`

**역할**: 사용자 메시지를 받아 전체 처리 흐름을 시작합니다.

**처리 단계**:

1. **세션 ID 생성/확인**
   - 없으면 자동 생성: `ContextManager.create_session_id()`

2. **질문 범위 검증** (`ScopeValidator`)
   ```python
   scope_result = self.scope_validator.validate(user_message)
   ```
   
   **프롬프트 구성** (추정):
   - 시스템: "계약서 관련 질문인지 판단하세요"
   - 사용자: 질문 내용
   - 응답: `{"is_valid": true/false, "reason": "..."}`

3. **LangGraph 워크플로우 실행**
   ```python
   final_state = self.autonomous_agent.run(
       contract_id=contract_id,
       user_message=user_message,
       session_id=session_id
   )
   ```

4. **대화 히스토리 저장**
   - 사용자 메시지 저장
   - 어시스턴트 응답 저장

---

## 2단계: LangGraph 워크플로우 (AutonomousAgent)

### 파일: `backend/chatbot_agent/autonomous_agent.py`

### 워크플로우 구조

```
[START]
    ↓
check_tool_needed (툴 필요성 판단)
    ↓
should_use_tools? (조건부 분기)
    ├─ use_tools → planner
    └─ direct_response → respond
    
planner (다음 행동 계획)
    ↓
should_execute_parallel? (조건부 분기)
    ├─ parallel → parallel_executor
    └─ sequential → executor
    
executor / parallel_executor (툴 실행)
    ↓
evaluator (정보 충분성 평가)
    ↓
should_continue? (조건부 분기)
    ├─ continue → planner (반복)
    └─ finish → respond
    
respond (최종 답변 생성)
    ↓
[END]
```

---

## 3단계: 각 노드별 상세 분석

### 3.1 check_tool_needed (툴 필요성 판단)

**파일**: `autonomous_agent.py` - `check_tool_needed()`

**목적**: 사용자 질문이 계약서 조회 툴을 필요로 하는지 판단

**처리 흐름**:

1. **규칙 기반 빠른 판단** (`LightweightClassifier`)
   - 패턴 매칭으로 빠르게 판단
   - 예: "안녕", "감사" → 툴 불필요
   - 예: "제5조", "해지 조건" → 툴 필요

2. **LLM 판단** (규칙 기반 실패 시)
   
   **프롬프트**:
   ```
   시스템: "당신은 질문 분석 전문가입니다. JSON 형식으로만 응답하세요."
   
   사용자:
   다음 질문이 계약서 내용 조회를 필요로 하는지 판단하세요.
   
   질문: {user_message}
   
   판단 기준:
   - 계약서 조항, 내용, 조건 등을 물어보는 경우 → 툴 필요
   - 일반적인 인사, 감사 표현 → 툴 불필요
   - 계약서와 무관한 질문 → 툴 불필요
   
   응답 형식 (JSON):
   {
       "needs_tools": true/false,
       "reasoning": "판단 근거"
   }
   ```
   
   **모델**: `gpt-4o`
   **온도**: `0.2`
   **최대 토큰**: `200`
   **응답 형식**: `{"type": "json_object"}`

**결과**: `decision_log`에 판단 결과 기록

---

### 3.2 planner (다음 행동 계획)

**파일**: `autonomous_agent.py` - `plan_next_action()`

**목적**: 다음에 실행할 툴과 파라미터를 결정

**처리 흐름**:

1. **중복 검색 방지**
   - 이미 실행한 툴 시그니처 확인
   - 시그니처 = `{tool_name}:{sorted(args.items())}`
   - 중복이면 계획 취소 (`next_tool = None`)

2. **규칙 기반 툴 제안** (`LightweightClassifier`)
   - 패턴 매칭으로 툴 추천
   - 예: "제5조" → `get_article_by_index`
   - 예: "해지 조건" → `hybrid_search`

3. **LLM 기반 계획** (규칙 기반 실패 시)
   
   **프롬프트**:
   ```
   시스템: "당신은 계약서 분석 전문가입니다. JSON 형식으로만 응답하세요."
   
   사용자:
   현재 상태를 분석하여 다음에 실행할 툴을 선택하세요.
   
   질문: {user_message}
   반복 횟수: {iteration_count}/{max_iterations}
   실행한 툴: {len(tool_history)}개
   수집된 정보: {len(collected_info)}개
   
   이미 실행한 툴:
   - {tool_name} (args: {args})
   - ...
   
   사용 가능한 툴:
   - **get_contract_structure**: 사용자 계약서의 구조(조 목록, 별지 목록)를 파악합니다.
     파라미터: {"contract_id": "계약서 ID (자동 제공)"}
   
   - **hybrid_search**: 키워드 기반 하이브리드 검색으로 관련 조항을 찾습니다.
     파라미터: {
       "contract_id": "계약서 ID (자동 제공)",
       "topics": "검색 주제 리스트 [{'topic_name': '주제명', 'queries': ['검색어1', '검색어2']}]"
     }
   
   - **get_article_by_index**: 조 번호 또는 별지 번호로 직접 조회합니다.
     파라미터: {
       "contract_id": "계약서 ID (자동 제공)",
       "article_numbers": "조 번호 리스트 [1, 3, 5]",
       "exhibit_numbers": "별지 번호 리스트 [1, 2]"
     }
   
   - **get_article_by_title**: 조 제목으로 조항을 검색합니다.
     파라미터: {
       "contract_id": "계약서 ID (자동 제공)",
       "titles": "제목 키워드 리스트 ['데이터 제공', '보안']"
     }
   
   - **lookup_standard_contract**: 표준계약서 조문을 조회합니다.
     파라미터: {
       "contract_id": "계약서 ID (자동 제공)",
       "user_article_numbers": "사용자 조 번호 리스트 [3, 5] (매칭 기반)",
       "topic": "검색 주제 문자열 (주제 기반)"
     }
   
   **중요**: 
   1. 위에 나열된 "이미 실행한 툴"은 절대 다시 선택하지 마세요
   2. 같은 툴을 다른 파라미터로 실행하는 것은 가능하지만, 같은 파라미터로는 불가능합니다
   
   다음 툴을 선택하고 파라미터를 결정하세요.
   
   응답 형식 (JSON):
   {
       "tool": "툴 이름",
       "args": {},
       "reasoning": "선택 근거"
   }
   ```
   
   **모델**: `gpt-4o`
   **온도**: `0.3`
   **최대 토큰**: `500`
   **응답 형식**: `{"type": "json_object"}`

4. **중복 검사 (LLM 응답)**
   - LLM이 중복 툴을 선택했는지 재확인
   - 중복이면 계획 취소

**결과**: `next_tool`에 선택된 툴 정보 저장

---

### 3.3 executor / parallel_executor (툴 실행)

**파일**: `autonomous_agent.py` - `execute_tools()` / `execute_parallel_tools()`

**목적**: 계획된 툴을 실행하고 결과를 수집

**처리 흐름**:

1. **파라미터 매핑** (`AgentRuntime._map_tool_parameters()`)
   - LLM이 잘못된 파라미터를 생성한 경우 수정
   - 예: `query` → `topics` (hybrid_search)
   - 예: `title` → `titles` (get_article_by_title)

2. **툴 실행** (`AgentRuntime.execute_tool()`)
   - 재시도 로직 포함 (최대 2회)
   - 에러 처리 및 로깅

3. **결과 저장**
   - `tool_history`에 실행 기록 추가
   - `collected_info`에 수집된 정보 추가
   - `contract_structure` 업데이트 (구조 파악 툴인 경우)

**병렬 실행 조건**:
- 첫 번째 툴이 `hybrid_search`인 경우 → `get_contract_structure`와 병렬 실행
- `get_article_by_index`에서 여러 조 번호 조회 시 → 각 조별로 병렬 실행

---

### 3.4 evaluator (정보 충분성 평가)

**파일**: `autonomous_agent.py` - `evaluate_sufficiency()`

**목적**: 수집된 정보가 질문에 답변하기 충분한지 평가

**처리 흐름**:

1. **반복 횟수 증가**
   - `iteration_count += 1`

2. **최대 반복 체크**
   - `iteration_count >= max_iterations` → 종료

3. **LLM 충분성 평가**
   
   **프롬프트**:
   ```
   시스템: "당신은 정보 충분성 평가 전문가입니다. JSON 형식으로만 응답하세요."
   
   사용자:
   수집된 정보가 질문에 답변하기 충분한지 평가하세요.
   
   질문: {user_message}
   
   수집된 정보: {len(collected_info)}개
   1. get_contract_structure: 15개 조
   2. hybrid_search: 3개 조 검색됨
   ...
   
   수집된 정보 상세:
   1. get_contract_structure: 15개 조
   2. hybrid_search: 3개 조 검색됨
   ...
   
   평가 기준:
   1. **질문에 직접 답변할 수 있는가?**
      - 수집된 정보에 질문의 답이 포함되어 있는가?
      - 예: "해지 조건이 있나?" → 해지 관련 조항이 수집되었는가?
   
   2. **추가 탐색이 필요한가?**
      - 질문의 핵심 정보가 누락되었는가?
      - 이미 수집한 정보와 중복되는 탐색은 불필요
   
   3. **중복 탐색 방지**
      - 이미 같은 주제로 검색했다면 추가 탐색 불필요
      - 반복 횟수: {iteration_count}/{max_iterations}
   
   응답 형식 (JSON):
   {
       "is_sufficient": true/false,
       "reasoning": "평가 근거 (구체적으로)",
       "missing_info": "부족한 정보 (있다면, 없으면 null)"
   }
   
   **중요**: 이미 관련 정보가 충분히 수집되었다면 is_sufficient=true로 판단하세요.
   ```
   
   **모델**: `gpt-4o`
   **온도**: `0.2`
   **최대 토큰**: `300`
   **응답 형식**: `{"type": "json_object"}`

**결과**: `decision_log`에 평가 결과 기록

---

### 3.5 respond (최종 답변 생성)

**파일**: `autonomous_agent.py` - `generate_response()`

**목적**: 수집된 정보를 바탕으로 최종 답변 생성

**처리 흐름**:

1. **컨텍스트 구성**
   - `collected_info`를 텍스트로 변환
   - 조항 내용, 검색 결과 등을 포맷팅

2. **LLM 답변 생성**
   
   **프롬프트**:
   ```
   시스템:
   당신은 계약서 질의응답 전문가입니다.
   
   규칙:
   1. 제공된 계약서 내용만을 기반으로 답변하세요
   2. 계약서에 없는 내용은 추측하지 마세요
   3. 참조한 조항의 출처를 명시하세요
   4. 명확하고 이해하기 쉽게 답변하세요
   5. 불확실한 경우 솔직히 말하세요
   
   사용자:
   계약서 내용:
   [제5조 대가 및 지급조건]
   1. 데이터 제공자는 ...
   2. 지급 기한은 ...
   
   [제10조 계약의 해지]
   1. 당사자는 다음의 경우 계약을 해지할 수 있다.
   ...
   
   질문: {user_message}
   
   위 계약서 내용을 바탕으로 질문에 답변해주세요.
   ```
   
   **모델**: `gpt-4o`
   **온도**: `0.3`
   **최대 토큰**: `1000`

3. **출처 추출**
   - `collected_info`에서 참조한 조항 정보 추출
   - `sources` 리스트 구성

**결과**: 
- `final_response`: 최종 답변 텍스트
- `sources`: 출처 정보 리스트

---

## 4단계: 조건부 분기 로직

### 4.1 should_use_tools

**조건**: `decision_log`의 마지막 결정이 `"direct_response"`인가?
- Yes → `"direct_response"` (respond로 이동)
- No → `"use_tools"` (planner로 이동)

### 4.2 should_execute_parallel

**조건**: 병렬 실행 가능한가?
- 첫 번째 툴이 `hybrid_search` → `"parallel"`
- `get_article_by_index`에서 여러 조 번호 → `"parallel"`
- 그 외 → `"sequential"`

### 4.3 should_continue

**조건**: `decision_log`의 마지막 결정이 `"continue"`인가?
- Yes → `"continue"` (planner로 돌아가 반복)
- No → `"finish"` (respond로 이동)

---

## 5단계: 상태 관리 (AgentState)

### 주요 상태 필드

```python
{
    "contract_id": str,              # 계약서 ID
    "user_message": str,             # 사용자 질문
    "session_id": str,               # 세션 ID
    "messages": List[Message],       # 대화 메시지 (LangChain 형식)
    "contract_structure": Dict,      # 계약서 구조 (조 목록 등)
    "tool_history": List[Dict],      # 툴 실행 기록
    "collected_info": List[Dict],    # 수집된 정보
    "explored_articles": List[int],  # 탐색한 조 번호
    "unexplored_articles": List[int],# 미탐색 조 번호
    "iteration_count": int,          # 반복 횟수
    "max_iterations": int,           # 최대 반복 횟수 (기본 5)
    "decision_log": List[Dict],      # 의사결정 로그
    "next_tool": Dict,               # 다음 실행할 툴
    "final_response": str,           # 최종 답변
    "sources": List[Dict]            # 출처 정보
}
```

---

## 6단계: 체크포인트 및 복원

### AgentPersistence

**역할**: LangGraph 워크플로우의 상태를 체크포인트로 저장

**저장 시점**: 각 노드 실행 후 자동 저장

**복원 시나리오**:
1. 에러 발생 시 마지막 체크포인트에서 복원
2. 부분 결과 추출 가능
3. 세션 재개 가능

---

## 7단계: 캐싱 및 성능 최적화

### LLMCache

**역할**: LLM 호출 결과를 캐싱하여 중복 호출 방지

**캐시 키**: `{prompt}:{model}:{temperature}:{max_tokens}`

**캐시 TTL**: 3600초 (1시간)

**메트릭**:
- `llm_cache_hits`: 캐시 히트 횟수
- `llm_cache_misses`: 캐시 미스 횟수
- `llm_cache_hit_rate`: 캐시 히트율

---

## 전체 흐름 예시

### 사용자 질문: "해지 조건이 뭐야?"

1. **check_tool_needed**
   - LLM 판단: `needs_tools=true` (계약서 조회 필요)

2. **planner (1차)**
   - LLM 계획: `hybrid_search` 선택
   - 파라미터: `topics=[{"topic_name": "해지", "queries": ["해지", "계약 종료"]}]`

3. **parallel_executor**
   - `get_contract_structure` + `hybrid_search` 병렬 실행
   - 결과: 제10조 "계약의 해지" 검색됨

4. **evaluator (1차)**
   - LLM 평가: `is_sufficient=false` (상세 내용 필요)

5. **planner (2차)**
   - LLM 계획: `get_article_by_index` 선택
   - 파라미터: `article_numbers=[10]`

6. **executor**
   - 제10조 전체 내용 조회

7. **evaluator (2차)**
   - LLM 평가: `is_sufficient=true` (충분)

8. **respond**
   - 최종 답변 생성: "제10조에 따르면, 계약 해지 조건은 다음과 같습니다..."
   - 출처: [제10조 계약의 해지]

---

## 주요 특징

### 1. 자율 탐색
- LLM이 스스로 필요한 툴을 선택하고 실행
- 반복적 사고-행동-평가 루프

### 2. 중복 방지
- 툴 시그니처 기반 중복 검색 방지
- LLM에게 이미 실행한 툴 명시적 제공

### 3. 병렬 처리
- 독립적인 툴 실행을 병렬화
- ThreadPoolExecutor 사용

### 4. 상태 영속화
- LangGraph 체크포인터로 상태 저장
- 에러 발생 시 복원 가능

### 5. 캐싱
- LLM 호출 결과 캐싱
- 중복 호출 방지로 성능 향상

### 6. 메트릭 추적
- LLM 호출, 툴 실행, 캐시 히트 등 추적
- 성능 분석 및 최적화 가능

---

## 개선 가능 영역

1. **프롬프트 최적화**
   - 각 단계별 프롬프트를 더 명확하게 개선
   - Few-shot 예시 추가

2. **툴 선택 정확도**
   - 규칙 기반 분류기 강화
   - 툴 설명 개선

3. **충분성 평가 정확도**
   - 평가 기준 명확화
   - 질문 유형별 평가 전략

4. **스트리밍 지원**
   - LangGraph 모드에서 스트리밍 응답 지원

5. **대화 컨텍스트 활용**
   - 이전 대화 내용을 더 적극적으로 활용
   - 참조 해결 개선
