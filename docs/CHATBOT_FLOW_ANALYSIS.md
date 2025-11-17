# 챗봇 에이전트 동작 흐름 분석 (최신)

**최종 업데이트**: 2024년 (LangGraph 기반 자율 탐색 에이전트)

## 핵심 변경사항

- ✅ `check_tool_needed` → `check_previous_context_needed` (이전 대화 참조만 판단)
- ✅ 툴 필요성 판단을 `planner`로 이동 (Function Calling `tool_choice="auto"`)
- ✅ `ScopeValidator`에서 이전 대화 참조 감지 (규칙 기반)
- ✅ JSON 응답 형식 강제 (`response_format={"type": "json_object"}`)
- ✅ 최대 반복 횟수: 4회

## 전체 플로우

```
사용자 질문
    ↓
[1] ChatbotOrchestrator
    ├─ ScopeValidator (범위 + 이전 대화 참조 감지)
    └─ AutonomousAgent (LangGraph)
        ↓
[2] check_previous_context (이전 대화 필요성)
        ↓
[3] planner (툴 선택, tool_choice="auto")
        ├─ 툴 있음 → executor
        └─ 툴 없음 → respond
        ↓
[4] executor (툴 실행, 정보 수집)
        ↓
[5] evaluator (충분성 평가)
        ├─ 불충분 → planner (반복, 최대 4회)
        └─ 충분 → respond
        ↓
[6] respond (최종 답변 생성)
```

---

## 상세 흐름

### [1] ChatbotOrchestrator (진입점)

**파일**: `backend/chatbot_agent/agent.py`

1. **ScopeValidator 검증**
   - 계약서 관련 질문인가? (규칙 + LLM)
   - 이전 대화 참조하는가? (규칙: "그", "방금", "아까" 등)
   
2. **대화 히스토리 로드** (직전 1턴)

3. **AutonomousAgent 실행**
   ```python
   self.autonomous_agent.run_stream(
       contract_id=contract_id,
       user_message=user_message,
       session_id=session_id,
       previous_turn=previous_turn,
       need_previous_context=scope_result.references_previous_context
   )
   ```

---

### [2] check_previous_context_needed

**파일**: `backend/chatbot_agent/autonomous_agent.py`

**목적**: 이전 대화 필요성 판단 (ScopeValidator에서 미리 판단 안 된 경우만)

**로직**:
```python
# 이미 설정되어 있으면 스킵
if state.get("need_previous_context") is not None:
    return state  # LLM 호출 없음

# 이전 대화 없으면 False
if len(messages) <= 1:
    state["need_previous_context"] = False
    return state

# LLM 판단
prompt = """이전 대화를 참조하는 질문인가요?
{
    "need_previous_context": true/false,
    "reasoning": "..."
}"""
```

**모델**: `gpt-4.1-nano`, JSON 모드

---

### [3] planner (핵심 변경!)

**파일**: `backend/chatbot_agent/autonomous_agent.py`

**목적**: 다음 툴 선택 (툴 불필요 시 빈 리스트 반환 가능)

**로직**:
1. **규칙 기반 툴 제안** (최초 1회만)
   - "제5조" → `get_article_by_index`
   
2. **Function Calling** (`tool_choice="auto"`)
   ```python
   prompt = """현재 상태를 분석하여 다음에 실행할 도구를 선택하세요.

   질문: {user_message}
   missing_info: {missing_info}  # evaluator에서 전달
   
   **중요**: 계약서 조회가 필요하지 않다면 도구를 선택하지 마세요.
   - 일반적인 인사, 감사 표현
   - 이전 답변으로 충분히 답할 수 있는 질문
   """
   
   result = function_adapter.call_with_functions(
       messages=messages,
       tool_choice="auto"  # 툴 선택 안 할 수도 있음
   )
   ```

3. **중복 검사**
   - 이미 실행한 툴 시그니처 확인
   - 중복이면 제외

**결과**: `next_tools` (빈 리스트 가능)

---

### [4] executor

**파일**: `backend/chatbot_agent/autonomous_agent.py`

**목적**: 툴 실행 및 정보 수집

**로직**:
```python
for tool_info in next_tools:
    result = self.runtime.execute_tool(tool_name, tool_args)
    state["tool_history"].append(...)
    state["collected_info"].append(...)
    self._update_explored_articles(state, tool_name, result)
```

---

### [5] evaluator (충분성 평가)

**파일**: `backend/chatbot_agent/autonomous_agent.py`

**목적**: 수집된 정보가 충분한지 평가

**로직**:
```python
# 반복 횟수 증가
state["iteration_count"] += 1

# 최대 반복 체크 (4회)
if state["iteration_count"] >= 4:
    return state  # 종료

# LLM 평가
prompt = """수집된 정보가 질문에 답변하기 충분한지 평가하세요.

질문: {user_message}

탐색 상태:
- 탐색한 항목: {explored_articles}
- 미탐색 항목: {unexplored_articles}

수집된 정보:
{collected_info_detail}

{
    "is_sufficient": true/false,
    "reasoning": "...",
    "missing_info": "부족한 정보 (없으면 null)"
}"""
```

**모델**: `gpt-4o`, JSON 모드

**결과**: `missing_info`를 planner에 전달

---

### [6] respond (최종 답변)

**파일**: `backend/chatbot_agent/autonomous_agent.py`

**목적**: 수집된 정보로 답변 생성

**로직**:
```python
context = self._build_context_from_collected_info(state)

# 이전 대화 포함 (필요 시)
if state.get("need_previous_context"):
    context = previous_context + "\n\n" + context

prompt = """수집된 정보:
{context}

질문: {user_message}

답변해주세요."""
```

**모델**: `gpt-4o`, 스트리밍

---

## 조건부 엣지

### should_execute_tools

```python
if not next_tools:
    return "no_tools"  # respond로 직행
elif can_execute_parallel(state):
    return "execute_parallel"
else:
    return "execute_sequential"
```

### should_continue

```python
if last_decision.action == "continue":
    return "continue"  # planner로 돌아감
else:
    return "finish"  # respond로
```

---

## 주요 특징

1. **툴 필요성을 planner가 판단** → 더 유연한 결정
2. **이전 대화 참조를 ScopeValidator가 감지** → LLM 호출 절약
3. **JSON 응답 강제** → 파싱 안정성 향상
4. **missing_info 전달** → 더 정확한 재탐색
5. **최대 4회 반복** → 효율성 향상

---

## 예시 플로우

**질문**: "그 참조항목들 내용 정리해서 보여줘봐"

1. **ScopeValidator**: "그" 감지 → `references_previous_context=True`
2. **check_previous_context**: 이미 설정됨 → 스킵
3. **planner**: 이전 답변 참조 → 툴 선택 안 함 (`next_tools=[]`)
4. **should_execute_tools**: `no_tools` → respond로 직행
5. **respond**: 이전 답변 포함하여 요약 생성
