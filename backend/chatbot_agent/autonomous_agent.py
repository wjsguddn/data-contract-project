"""
AutonomousAgent - LangGraph 기반 자율 탐색 에이전트

반복적 사고-행동-평가 루프를 통해 사용자 질문에 답변합니다.
"""

import logging
import json
from typing import Dict, Any, List, Optional
from datetime import datetime
from openai import OpenAI

from langgraph.graph import StateGraph, END
from concurrent.futures import ThreadPoolExecutor, as_completed

from backend.chatbot_agent.models import AgentState, DecisionLog, CollectedInfo
from backend.chatbot_agent.tools import ToolRegistry
from backend.chatbot_agent.lightweight_classifier import LightweightClassifier
from backend.chatbot_agent.agent_runtime import AgentRuntime
from backend.chatbot_agent.agent_persistence import AgentPersistence
from backend.chatbot_agent.agent_recovery import AgentRecovery
from backend.chatbot_agent.function_calling_adapter import FunctionCallingAdapter

logger = logging.getLogger("uvicorn.error")


class AutonomousAgent:
    """
    자율 탐색 에이전트
    
    LangGraph 기반 반복적 사고-행동-평가 루프:
    1. check_tool_needed: 툴 사용 필요성 판단
    2. plan_next_action: 다음 행동 계획
    3. execute_tools: 툴 실행
    4. evaluate_sufficiency: 정보 충분성 평가
    5. generate_response: 최종 답변 생성
    """
    
    def __init__(
        self,
        openai_client: OpenAI,
        tool_registry: ToolRegistry,
        max_iterations: int = 4,
        enable_cache: bool = True,
        persistence_mode: str = "sqlite",
        checkpoint_db_path: Optional[str] = None
    ):
        """
        Args:
            openai_client: OpenAI 클라이언트
            tool_registry: 툴 레지스트리
            max_iterations: 최대 반복 횟수
            enable_cache: LLM 캐시 활성화 여부
            persistence_mode: 영속화 모드 ("memory" 또는 "sqlite")
            checkpoint_db_path: 체크포인트 DB 경로 (persistence_mode="sqlite"인 경우)
        """
        self.openai_client = openai_client
        self.tool_registry = tool_registry
        self.max_iterations = max_iterations
        self.classifier = LightweightClassifier()
        
        # AgentRuntime 초기화
        self.runtime = AgentRuntime(
            openai_client=openai_client,
            tool_registry=tool_registry,
            enable_cache=enable_cache,
            max_retries=2
        )
        
        # FunctionCallingAdapter 초기화
        self.function_adapter = FunctionCallingAdapter(
            openai_client=openai_client,
            tool_registry=tool_registry
        )
        
        # AgentPersistence 초기화 (현재는 memory만 지원)
        self.persistence = AgentPersistence(
            persistence_mode="memory",  # 현재 memory만 지원
            db_path=checkpoint_db_path
        )
        
        # 워크플로우 구축 및 컴파일
        workflow = self._build_workflow()
        self.app = self.persistence.compile_workflow(workflow)
        
        logger.info(
            f"AutonomousAgent 초기화 완료 "
            f"(max_iterations={max_iterations}, cache={enable_cache}, "
            f"persistence={persistence_mode})"
        )
    
    def _build_workflow(self) -> StateGraph:
        """
        LangGraph 워크플로우 구축
        
        새로운 플로우:
        1. planner: 툴 선택 (툴 불필요 시 빈 리스트 반환 가능)
        2. [조건] 툴 있으면 executor → evaluator, 없으면 바로 respond
        3. evaluator: 충분성 평가 후 continue/finish 판단
        
        Returns:
            컴파일되지 않은 StateGraph (AgentPersistence에서 컴파일)
        """
        # StateGraph 초기화
        workflow = StateGraph(AgentState)
        
        # 노드 추가
        workflow.add_node("planner", self.plan_next_action)
        workflow.add_node("executor", self.execute_tools)
        workflow.add_node("parallel_executor", self.execute_parallel_tools)
        workflow.add_node("evaluator", self.evaluate_sufficiency)
        workflow.add_node("respond", self.generate_response)
        
        # 엣지 연결
        workflow.set_entry_point("planner")
        
        # planner → [조건] executor/parallel_executor (툴 있음) or respond/evaluator (툴 없음)
        workflow.add_conditional_edges(
            "planner",
            self.should_execute_tools,
            {
                "execute_parallel": "parallel_executor",
                "execute_sequential": "executor",
                "no_tools": "respond",
                "skip_to_evaluator": "evaluator"  # 중복 스킵 시 evaluator로
            }
        )
        
        # executor → evaluator
        workflow.add_edge("executor", "evaluator")
        
        # parallel_executor → evaluator
        workflow.add_edge("parallel_executor", "evaluator")
        
        # evaluator → planner or respond
        workflow.add_conditional_edges(
            "evaluator",
            self.should_continue,
            {
                "continue": "planner",
                "finish": "respond"
            }
        )
        
        # respond → END
        workflow.add_edge("respond", END)
        
        # 컴파일하지 않고 반환 (AgentPersistence에서 체크포인터와 함께 컴파일)
        return workflow
    
    def run_stream(
        self,
        contract_id: str,
        user_message: str,
        session_id: str,
        previous_turn: List[Dict[str, str]] = None,
        need_previous_context: Optional[bool] = None
    ):
        """
        에이전트 실행 (스트리밍 모드)
        
        Args:
            contract_id: 계약서 ID
            user_message: 사용자 메시지
            session_id: 세션 ID
            previous_turn: 직전 대화 이력 (plain dict)
            need_previous_context: 이전 대화 필요성 (ScopeValidator에서 미리 판단된 경우)
            
        Yields:
            dict: 스트리밍 이벤트
                - {"type": "token", "content": str} - 응답 토큰
                - {"type": "sources", "content": list} - 출처 정보
                - {"type": "thinking", "step": str, "content": str} - 사고 과정
                - {"type": "error", "content": str} - 에러 메시지
        """
        import time
        start_time = time.time()
        
        try:
            # 초기 상태 구성
            messages = []
            if previous_turn:
                messages.extend(previous_turn)
            messages.append({"role": "user", "content": user_message})
            
            unexplored_articles = self._load_contract_structure(contract_id)
            
            initial_state: AgentState = {
                "contract_id": contract_id,
                "user_message": user_message,
                "session_id": session_id,
                "messages": messages,
                "need_previous_context": need_previous_context,  # None, True, False 모두 가능
                "contract_structure": None,
                "tool_history": [],
                "collected_info": [],
                "explored_articles": [],
                "unexplored_articles": unexplored_articles,
                "iteration_count": 0,
                "max_iterations": self.max_iterations,
                "decision_log": [],
                "next_tools": [],
                "all_tools_skipped": False,
                "final_response": None,
                "sources": []
            }
            
            logger.info(f"[run_stream] 실행 시작: {user_message[:50]}...")
            
            # 체크포인트 설정
            config = {
                "configurable": {
                    "thread_id": session_id,
                    "checkpoint_ns": contract_id
                }
            }
            
            # 워크플로우 실행 (응답 생성 직전까지)
            # respond 노드를 제외한 모든 노드 실행
            final_state = None
            is_first_planner = True
            previous_user_articles = set()
            previous_std_articles = set()
            should_stop = False

            for state in self.app.stream(initial_state, config=config):
                # 마지막 상태 저장
                if state:
                    # state는 {node_name: node_output} 형식
                    for node_name, node_output in state.items():
                        if node_name == "planner":
                            next_tools = node_output.get("next_tools", [])

                            # 툴이 없으면 바로 답변 생성
                            if not next_tools:
                                yield {"type": "thinking", "step": "generating", "content": "..."}
                                # respond 노드로 가기 전에 중단
                                final_state = node_output
                                should_stop = True
                                break
                            else:
                                # 1. planner 최초 실행 시
                                if is_first_planner:
                                    yield {"type": "thinking", "step": "planning", "content": "탐색 계획 수립중..."}
                                    is_first_planner = False
                                else:
                                    # 5. 재탐색 시
                                    yield {"type": "thinking", "step": "replanning", "content": "계약서 조문 리스트업..."}

                                # 2. 도구 선택 완료 시
                                for thinking_event in self._generate_tool_selection_events(next_tools, contract_id):
                                    yield thinking_event

                            final_state = node_output

                        elif node_name in ["executor", "parallel_executor"]:
                            # 도구 실행 완료 후 추가 이벤트 생성
                            tool_history = node_output.get("tool_history", [])
                            if tool_history:
                                last_tool = tool_history[-1]
                                tool_name = last_tool.get("tool")
                                result = last_tool.get("result", {})

                                # lookup_standard_contract의 LLM 선별 완료 시
                                if tool_name == "lookup_standard_contract":
                                    if isinstance(result, dict):
                                        data = result.get("data", {})
                                        method = data.get("method")

                                        # topic 기반 조회이고 표준 조항이 선별된 경우
                                        if method == "topic_based":
                                            standard_articles = data.get("standard_articles", [])
                                            if standard_articles:
                                                articles_list = []
                                                for article in standard_articles[:3]:
                                                    parent_id = article.get("parent_id", "")
                                                    title = article.get("title", "")
                                                    if parent_id and title:
                                                        articles_list.append(f"{parent_id}({title})")

                                                if articles_list:
                                                    articles_text = ", ".join(articles_list)
                                                    if len(standard_articles) > 3:
                                                        articles_text += "..."
                                                    yield {"type": "thinking", "step": "tool_selected", "content": f"표준계약서 {articles_text}"}

                            final_state = node_output

                        elif node_name == "evaluator":
                            # 3. evaluate_sufficiency 진입 시 (새로 추가된 조항만 표시)
                            for thinking_event in self._generate_evaluation_events(node_output, previous_user_articles, previous_std_articles):
                                # 내부 업데이트 마커 확인
                                if thinking_event.get("_internal_update"):
                                    previous_user_articles = thinking_event["user_articles"]
                                    previous_std_articles = thinking_event["std_articles"]
                                    continue

                                # 일반 이벤트 출력
                                yield thinking_event

                            # 4. evaluate_sufficiency 완료 시
                            decision_log = node_output.get("decision_log", [])
                            if decision_log:
                                last_decision = decision_log[-1]
                                action = last_decision.get("action", "")

                                if action == "continue":
                                    # continue 액션이면 missing_info 출력
                                    missing_info = node_output.get("missing_info")
                                    if missing_info and missing_info != "null":
                                        yield {"type": "thinking", "step": "evaluation_result", "content": f"Evaluate {missing_info}"}
                                elif action == "finish":
                                    # finish 액션이면 답변 생성 시작
                                    yield {"type": "thinking", "step": "generating", "content": "..."}
                                    # respond 노드로 가기 전에 중단
                                    final_state = node_output
                                    should_stop = True
                                    break

                            final_state = node_output

                        elif node_name == "respond":
                            # respond 노드에 도달하면 안됨 (이미 위에서 중단했어야 함)
                            logger.warning("[run_stream] respond 노드에 도달함 (예상치 못한 동작)")
                            final_state = node_output
                            should_stop = True
                            break
                        else:
                            final_state = node_output

                # 중단 플래그 확인
                if should_stop:
                    break

            if not final_state:
                raise Exception("워크플로우 실행 실패")
            
            # 실행 통계 로깅
            elapsed_time = time.time() - start_time
            logger.info(
                f"[AutonomousAgent] 실행 완료: "
                f"{final_state.get('iteration_count', 0)}회 반복, "
                f"{len(final_state.get('tool_history', []))}개 툴 실행, "
                f"소요 시간: {elapsed_time:.2f}초"
            )
            
            logger.info(f"[run_stream] 워크플로우 완료, 스트리밍 응답 생성 시작")
            
            # 스트리밍 응답 생성
            context = self._build_context_from_collected_info(final_state)
            
            system_prompt = """당신은 계약서 질의응답 전문가입니다.

규칙:
1. 제공된 내용을 기반으로 답변하세요
2. 계약서에 없는 내용은 추측하지 마세요
3. 참조한 조항의 출처를 명시하세요
4. 명확하고 이해하기 쉽게 답변하세요
5. 불확실한 경우 솔직히 말하세요
6. 질문의 성향에 따라 표준계약서 내용이 제공될 수 있습니다. 표준계약서는 계약서 작성 시 형식 참고용 템플릿입니다. 표준계약서의 형식이 무조건 옳은 것은 아니며 표준계약서의 내용에 매몰되어선 안됩니다.
7. 사용자 계약서와 표준계약서의 차이를 명확히 인지하고 구분하세요. 질문이 표준계약서라고 직접 명시하지 않으면 그것은 사용자 계약서에 대한 내용입니다."""
            
            user_prompt = f"""
수집된 정보:

{context}

현재 질문: {final_state['user_message']}

수집된 정보를 기반으로 답변해 주세요.
- 단, 수집된 정보에 질문과 관련 없는 내용이 포함되어 있을 수도 있습니다. 활용할 필요가 없다고 판단되는 내용은 참고하지 않습니다.
- 답변은 구조화된 형태일수록 좋습니다.
- 계약서와 관련된 내용의 질문이 아니라면 "죄송합니다. 저는 계약서 내용에 대한 질문에만 답변할 수 있습니다. 계약서와 관련된 내용에 대해 질문해주세요." 라고만 답해야한다."""
            
            # 프롬프트 로깅
            # logger.info("=" * 80)
            # logger.info("[run_stream] 최종 응답 생성 LLM 호출 프롬프트")
            # logger.info("=" * 80)
            # logger.info(f"[SYSTEM]\n{system_prompt}")
            # logger.info("-" * 80)
            # logger.info(f"[USER]\n{user_prompt}")
            # logger.info("=" * 80)
            
            # 스트리밍 LLM 호출 (o1 시리즈는 temperature 미지원)
            for token in self.runtime.call_llm_stream(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                model="gpt-5.1",
                reasoning_effort="low",
                # model="gpt-4o",
                # temperature=0.3,
                max_completion_tokens=8000
            ):
                yield {"type": "token", "content": token}
            
            # 출처 정보 전송
            sources = self._extract_sources(final_state)
            yield {"type": "sources", "content": sources}
            
            logger.info(f"[run_stream] 스트리밍 완료")
            
        except Exception as e:
            logger.error(f"[run_stream] 오류 발생: {e}")
            import traceback
            logger.error(traceback.format_exc())
            yield {"type": "error", "content": str(e)}
    
    def run(
        self,
        contract_id: str,
        user_message: str,
        session_id: str,
        previous_turn: List[Dict[str, str]] = None
    ) -> AgentState:
        """
        [DEPRECATED] 에이전트 실행 (Non-streaming)

        ⚠️ 이 메서드는 더 이상 사용되지 않습니다. run_stream()을 사용하세요.

        Args:
            contract_id: 계약서 ID
            user_message: 사용자 메시지
            session_id: 세션 ID
            previous_turn: 직전 대화 이력 (plain dict)

        Returns:
            최종 AgentState
        """
        # 초기 상태 구성
        # 직전 대화를 messages에 포함 (plain dict 그대로 사용)
        messages = []
        if previous_turn:
            messages.extend(previous_turn)
        
        # 현재 질문 추가
        messages.append({"role": "user", "content": user_message})
        
        # 사용자 계약서 구조 로드하여 unexplored_articles 초기화
        unexplored_articles = self._load_contract_structure(contract_id)
        
        initial_state: AgentState = {
            "contract_id": contract_id,
            "user_message": user_message,
            "session_id": session_id,
            "messages": messages,
            "need_previous_context": False,  # check_tool_needed에서 판단
            "contract_structure": None,
            "tool_history": [],
            "collected_info": [],
            "explored_articles": [],
            "unexplored_articles": unexplored_articles,
            "iteration_count": 0,
            "max_iterations": self.max_iterations,
            "decision_log": [],
            "next_tools": [],
            "all_tools_skipped": False,
            "final_response": None,
            "sources": []
        }
        
        import time
        start_time = time.time()
        
        logger.info(f"[AutonomousAgent] 실행 시작: {user_message[:50]}...")
        
        # 체크포인트 설정
        config = {
            "configurable": {
                "thread_id": session_id,
                "checkpoint_ns": contract_id
            }
        }
        
        try:
            # 워크플로우 실행 (체크포인터 활성화)
            final_state = self.app.invoke(initial_state, config=config)
            
            elapsed_time = time.time() - start_time
            
            logger.info(
                f"[AutonomousAgent] 실행 완료: "
                f"{final_state.get('iteration_count', 0)}회 반복, "
                f"{len(final_state.get('tool_history', []))}개 툴 실행, "
                f"소요 시간: {elapsed_time:.2f}초"
            )
            
            return final_state
        
        except Exception as e:
            logger.error(f"[AutonomousAgent] 실행 중 오류 발생: {e}")
            
            # 체크포인트에서 복원 시도
            recovered_state = self.recover_from_checkpoint(session_id, contract_id)
            
            if recovered_state:
                logger.warning(
                    f"[AutonomousAgent] 체크포인트에서 복원됨: "
                    f"iteration={recovered_state.get('iteration_count', 0)}"
                )
                
                # 부분 결과 반환
                recovered_state["error"] = str(e)
                recovered_state["recovered"] = True
                return recovered_state
            else:
                # 복원 실패, 예외 재발생
                logger.error("[AutonomousAgent] 체크포인트 복원 실패")
                raise
    
    # ============================================
    # 노드 구현
    # ============================================

    def plan_next_action(self, state: AgentState) -> AgentState:
        """
        다음 행동 계획 (Function Calling 사용, 여러 툴 동시 선택 지원)
        
        Args:
            state: 현재 상태
            
        Returns:
            업데이트된 상태
        """
        logger.info("[plan_next_action] Function Calling으로 계획 수립")
        
        user_message = state["user_message"]
        tool_history = state.get("tool_history", [])
        
        # 중복 검색 방지: 이미 실행한 툴 확인
        executed_tool_signatures = set()
        for history in tool_history:
            tool_name = history.get("tool")
            args = history.get("args", {})
            signature = f"{tool_name}:{str(sorted(args.items()))}"
            executed_tool_signatures.add(signature)
        
        logger.info(f"[plan_next_action] 이미 실행한 툴: {len(executed_tool_signatures)}개")
        
        # 1. 규칙 기반 툴 제안 (최초 1회만)
        quick_suggestion = None
        if len(tool_history) == 0:
            quick_suggestion = self.classifier.suggest_tool(user_message)
        
        if quick_suggestion is not None:
            tool_name, args, reasoning = quick_suggestion
            
            signature = f"{tool_name}:{str(sorted(args.items()))}"
            if signature in executed_tool_signatures:
                logger.warning(f"[plan_next_action] 중복 툴 스킵: {tool_name}")
                state["next_tools"] = []
                state["all_tools_skipped"] = True  # 중복으로 스킵됨
                return state
            else:
                state["all_tools_skipped"] = False  # 정상 선택
                # 단일 툴을 리스트로 래핑
                state["next_tools"] = [{
                    "tool": tool_name,
                    "args": args,
                    "reasoning": reasoning,
                    "tool_call_id": None  # 규칙 기반은 ID 없음
                }]
                
                decision = DecisionLog(
                    step="planning",
                    reasoning=reasoning,
                    action=f"selected_tool: {tool_name}",
                    confidence=0.9,
                    timestamp=datetime.now().isoformat(),
                    method="rule_based"
                )
                state["decision_log"].append(decision.dict())
                
                logger.info(f"[plan_next_action] 규칙 기반 제안: tool={tool_name}")
                return state
        
        # 2. Function Calling 기반 계획
        status_summary = self._build_status_summary(state)
        
        # 이전 대화 컨텍스트 추가 (필요한 경우)
        previous_context_text = ""
        need_previous_context = state.get("need_previous_context", False)
        if need_previous_context:
            previous_context = self._build_previous_context(state)
            if previous_context:
                previous_context_text = f"\n\n{previous_context}\n"
        
        # missing_info 추가 (evaluator에서 전달된 경우)
        missing_info_text = ""
        missing_info = state.get("missing_info")
        if missing_info and missing_info != "null":
            missing_info_text = f"\n\n[탐색 추천 항목] {missing_info}\n(꼭 이 정보들을 탐색할 필요는 없음. 단순 추천일 뿐이므로 고려 대상으로 삼기만 해도 좋음. 결국 네가 필요하다고 생각하는 정보들을 탐색하기 위해 툴을 사용해야함.)"
        
        # 이전 툴 실행 이력 (중복 방지용)
        executed_tools_text = ""
        if tool_history:
            executed_list = []
            for history in tool_history:
                tool_name = history.get("tool")
                args = history.get("args", {})
                executed_list.append(f"- {tool_name} (args: {args})")
            executed_tools_text = f"\n\n이미 실행한 도구 (중복 실행 금지):\n" + "\n".join(executed_list)
        
        # 메시지 구성
        messages = [
            {
                "role": "user",
                "content": f"""현재 상태를 분석하여 다음에 실행할 도구를 선택하세요.
{previous_context_text}
{status_summary}

질문: {user_message}{missing_info_text}{executed_tools_text}

**중요**: 툴 사용이 필요하지 않은 질문이라면 도구를 선택하지 마세요.
- 일반적인 인사, 감사 표현
- 계약과 완전히 무관한 질문
- 이전 답변으로 충분히 답할 수 있는 질문(간략화 요청 등) **주의**: 이전 답변에서 파생된 질문이라 하더라도, 상세화를 요청하거나 추가적인 내용에 대한 요청이 있다면 툴을 사용해야 할 확률이 높음.

**중요**: 질문과 관련해서 확인해야 할 내용이 남아있거나, 탐색 추천 항목이 존재할 경우 반드시 툴을 사용하세요.

적절한 도구를 선택하세요. 필요하다면 여러 도구를 동시에 선택할 수 있습니다."""
            }
        ]
        
        try:
            # Function Calling 호출 (tool_choice="auto"로 변경 - 툴 선택 안 할 수도 있음)
            result = self.function_adapter.call_with_functions(
                messages=messages,
                tool_choice="auto"  # 툴 불필요 시 선택 안 함
            )
            
            if result["has_tool_calls"]:
                # 여러 tool_calls를 모두 처리
                tool_calls = result["tool_calls"]
                
                logger.info(f"[plan_next_action] LLM이 선택한 툴: {len(tool_calls)}개")
                
                # 중복 검사
                valid_tool_calls = []
                for tc in tool_calls:
                    signature = f"{tc['name']}:{str(sorted(tc['args'].items()))}"
                    
                    if signature not in executed_tool_signatures:
                        valid_tool_calls.append({
                            "tool": tc["name"],
                            "args": tc["args"],
                            "tool_call_id": tc["id"],
                            "reasoning": "Function calling으로 선택됨"
                        })
                        logger.info(f"[plan_next_action] 툴 추가: {tc['name']}")
                    else:
                        logger.warning(
                            f"[plan_next_action] 중복 툴 스킵: {tc['name']}, "
                            f"args={tc['args']}"
                        )
                
                state["next_tools"] = valid_tool_calls
                
                if valid_tool_calls:
                    state["all_tools_skipped"] = False  # 정상 선택
                    decision = DecisionLog(
                        step="planning",
                        reasoning=f"{len(valid_tool_calls)}개 툴 선택됨",
                        action=f"selected_tools: {[tc['tool'] for tc in valid_tool_calls]}",
                        timestamp=datetime.now().isoformat(),
                        method="function_calling"
                    )
                    state["decision_log"].append(decision.dict())
                    
                    logger.info(
                        f"[plan_next_action] 선택된 툴: "
                        f"{[tc['tool'] for tc in valid_tool_calls]}"
                    )
                else:
                    # 모든 툴이 중복으로 스킵됨 (evaluator로 가야 함)
                    state["all_tools_skipped"] = True
                    logger.warning("[plan_next_action] 모든 툴이 중복으로 스킵됨")
            else:
                # 툴 선택 안 됨 (종료)
                state["next_tools"] = []
                state["all_tools_skipped"] = False  # 의도적으로 선택 안 함
                logger.info("[plan_next_action] 툴 선택 안 됨 (종료)")
            
        except Exception as e:
            logger.error(f"[plan_next_action] 오류 발생: {e}")
            import traceback
            logger.error(traceback.format_exc())
            # 폴백: 하이브리드 검색
            state["next_tools"] = [{
                "tool": "hybrid_search",
                "args": {"topics": [{"topic_name": "general", "queries": [user_message[:100]]}]},
                "reasoning": "계획 실패, 기본 검색 사용",
                "tool_call_id": None
            }]
        
        return state
    
    def execute_tools(self, state: AgentState) -> AgentState:
        """
        툴 실행 (여러 툴 동시 실행 지원)
        
        Args:
            state: 현재 상태
            
        Returns:
            업데이트된 상태
        """
        next_tools = state.get("next_tools", [])
        
        if not next_tools:
            logger.warning("[execute_tools] next_tools가 비어있습니다")
            return state
        
        contract_id = state["contract_id"]
        
        logger.info(f"[execute_tools] {len(next_tools)}개 툴 실행 시작")
        
        # 여러 툴 순차 실행 (병렬 실행은 execute_parallel_tools에서)
        for tool_info in next_tools:
            tool_name = tool_info.get("tool")
            args = tool_info.get("args", {})
            tool_call_id = tool_info.get("tool_call_id")
            
            logger.info(f"[execute_tools] 툴 실행: {tool_name}, args={args}")
            
            try:
                # 툴 실행 (AgentRuntime 사용)
                tool_args = {**args, "contract_id": contract_id}
                result = self.runtime.execute_tool(
                    tool_name=tool_name,
                    tool_args=tool_args,
                    retry_on_failure=True
                )
                
                # tool_history에 기록
                state["tool_history"].append({
                    "tool": tool_name,
                    "args": args,
                    "result": result.dict() if hasattr(result, 'dict') else result,
                    "tool_call_id": tool_call_id,
                    "timestamp": datetime.now().isoformat()
                })
                
                # 툴별 상태 업데이트 (explored_articles 업데이트)
                self._update_explored_articles(state, tool_name, result)
                
                # collected_info에 추가
                if result.success and result.data:
                    # article_refs 추출
                    article_refs = self._extract_article_refs(tool_name, result)
                    
                    info = CollectedInfo(
                        source=tool_name,
                        content=result.data.dict() if hasattr(result.data, 'dict') else result.data,
                        relevance=result.relevance_score or 0.8,
                        timestamp=datetime.now().isoformat(),
                        article_refs=article_refs
                    )
                    state["collected_info"].append(info.dict())
                
                logger.info(f"[execute_tools] 툴 실행 완료: {tool_name}, success={result.success}")
                
            except Exception as e:
                logger.error(f"[execute_tools] 툴 실행 실패: {tool_name}, {e}")
                import traceback
                logger.error(traceback.format_exc())
        
        logger.info(f"[execute_tools] 전체 툴 실행 완료: {len(next_tools)}개")
        
        return state
    
    def evaluate_sufficiency(self, state: AgentState) -> AgentState:
        """
        정보 충분성 평가
        
        Args:
            state: 현재 상태
            
        Returns:
            업데이트된 상태
        """
        logger.info("[evaluate_sufficiency] 충분성 평가 시작")

        # 반복 횟수 증가
        state["iteration_count"] = state.get("iteration_count", 0) + 1

        # 최대 반복 체크
        if state["iteration_count"] >= state["max_iterations"]:
            logger.warning(f"[evaluate_sufficiency] 최대 반복 횟수 도달: {state['iteration_count']}")
            decision = DecisionLog(
                step="evaluation",
                reasoning="최대 반복 횟수 도달",
                action="finish",
                timestamp=datetime.now().isoformat(),
                method="rule_based"
            )
            state["decision_log"].append(decision.dict())
            return state
        
        # 이전 대화 컨텍스트 추가 (필요한 경우)
        previous_context_text = ""
        need_previous_context = state.get("need_previous_context", False)
        if need_previous_context:
            previous_context = self._build_previous_context(state)
            if previous_context:
                previous_context_text = f"\n\n{previous_context}\n"
        
        # 수집된 정보 상세
        collected_info = state.get("collected_info", [])
        collected_info_detail = self._build_collected_info_detail(collected_info)
        
        # 탐색 상태 정보
        explored_articles = state.get("explored_articles", [])
        unexplored_articles = state.get("unexplored_articles", [])
        
        # 탐색 상태 포맷팅
        explored_text = "\n".join(f"  - {article}" for article in explored_articles) if explored_articles else "  (없음)"
        unexplored_text = "\n".join(f"  - {article}" for article in unexplored_articles) if unexplored_articles else "  (없음)"
        
        # LLM으로 충분성 평가
        prompt = f"""수집된 정보가 질문에 답변하기 충분한지 평가하세요.
{previous_context_text}
질문: {state['user_message']}

[사용자 계약서 탐색 상태]
- 탐색한 항목 ({len(explored_articles)}개):
{explored_text}

- 미탐색 항목 ({len(unexplored_articles)}개):
{unexplored_text}

수집된 정보:
{collected_info_detail}

평가 기준:
1. **질문에 직접 답변할 수 있는가?**
   - 수집된 정보에 질문의 답이 명확히 포함되어 있는가?
   - 질문에 답하기 위해 필요한 내용들이 정확히 무엇인지, 수집 정보에 그 내용들이 모두 명확히 드러나 있는지를 파악해야함
   - 단순히 관련 조항이 있다는 것만으로는 불충분
   - 질문의 구체적인 내용(조건, 기간, 금액 등)에 대한 답이 있어야 함

2. **추가 탐색이 필요한가?**
   - 미탐색 항목중 살펴봐야 할 항목이 있는가?
   - 질문의 핵심 정보가 누락되었는가?
   - 조항은 찾았지만 내용이 불완전한가?

3. **중복 탐색 방지**
   - 반복 횟수: {state['iteration_count']}/{state['max_iterations']}

**판단 원칙**:
- 질문에 완전히 답변할 수 있을 때 is_sufficient=true
- 조항을 찾았지만 내용이 부족하면 is_sufficient=false
- 불확실하면 is_sufficient=false (추가 탐색 선호)

**중요**: reasoning과 missing_info는 각각 한 문장으로 간결하게 작성하세요

응답 형식 (JSON):
{{
    "is_sufficient": true/false,
    "reasoning": "평가 근거",
    "missing_info": "부족한 정보(없으면 null)"
}}

JSON만 응답하세요."""
        
        try:
            system_msg = "당신은 정보 충분성 평가 전문가입니다. JSON 형식으로만 응답하세요."
            
            # 프롬프트 로깅
            # logger.info("=" * 80)
            # logger.info("[evaluate_sufficiency] LLM 호출 프롬프트")
            # logger.info("=" * 80)
            # logger.info(f"[SYSTEM]\n{system_msg}")
            # logger.info("-" * 80)
            # logger.info(f"[USER]\n{prompt}")
            # logger.info("=" * 80)
            
            response_text = self.runtime.call_llm(
                messages=[
                    {
                        "role": "system",
                        "content": system_msg
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                model="gpt-4o",
                temperature=0.2,
                max_tokens=300,
                response_format={"type": "json_object"}
            )
            
            # 디버깅: LLM 응답 로그
            logger.debug(f"[evaluate_sufficiency] LLM 응답: {response_text}")
            
            # JSON 파싱 시도
            result = json.loads(response_text)

            # 필수 필드 검증
            if "is_sufficient" not in result:
                raise ValueError("응답에 is_sufficient 필드가 없습니다")
            
            is_sufficient = result.get("is_sufficient", False)
            reasoning = result.get("reasoning", "평가 근거 없음")
            missing_info = result.get("missing_info")

            # missing_info를 state에 저장 (UI 표시용)
            if missing_info and missing_info != "null":
                state["missing_info"] = missing_info
            else:
                state["missing_info"] = None

            decision = DecisionLog(
                step="evaluation",
                reasoning=reasoning,
                action="finish" if is_sufficient else "continue",
                timestamp=datetime.now().isoformat(),
                method="llm"
            )
            state["decision_log"].append(decision.dict())

            logger.info(
                f"[evaluate_sufficiency] 평가 완료: "
                f"is_sufficient={is_sufficient}, "
                f"reasoning={reasoning}, "
                f"missing_info={missing_info}"
            )
            
        except json.JSONDecodeError as e:
            logger.error(f"[evaluate_sufficiency] JSON 파싱 오류: {e}")
            logger.error(f"[evaluate_sufficiency] 문제가 된 응답: {response_text}")
            # 폴백: 충분하다고 판단
            decision = DecisionLog(
                step="evaluation",
                reasoning=f"JSON 파싱 실패 (line {e.lineno}, col {e.colno}), 종료",
                action="finish",
                timestamp=datetime.now().isoformat(),
                method="fallback"
            )
            state["decision_log"].append(decision.dict())
        except Exception as e:
            logger.error(f"[evaluate_sufficiency] 오류 발생: {e}")
            logger.error(f"[evaluate_sufficiency] 오류 타입: {type(e).__name__}")
            # 폴백: 충분하다고 판단
            decision = DecisionLog(
                step="evaluation",
                reasoning="평가 실패, 종료",
                action="finish",
                timestamp=datetime.now().isoformat(),
                method="fallback"
            )
            state["decision_log"].append(decision.dict())
        
        return state
    
    def generate_response(self, state: AgentState) -> AgentState:
        """
        [DEPRECATED] 최종 답변 생성 (Non-streaming)

        ⚠️ 이 메서드는 더 이상 사용되지 않습니다.
        run_stream()에서 직접 스트리밍 응답을 생성합니다.
        이 메서드는 run() 메서드에서만 호출되며, run()도 deprecated입니다.

        Args:
            state: 현재 상태

        Returns:
            업데이트된 상태
        """
        import time
        start_time = time.time()
        
        logger.info("[generate_response] 답변 생성 시작")
        
        # 수집된 정보를 컨텍스트로 변환
        context = self._build_context_from_collected_info(state)
        
        # 시스템 프롬프트
        system_prompt = """당신은 계약서 질의응답 전문가입니다.

규칙:
1. 제공된 내용을 기반으로 답변하세요
2. 계약서에 없는 내용은 추측하지 마세요
3. 참조한 조항의 출처를 명시하세요
4. 명확하고 이해하기 쉽게 답변하세요
5. 불확실한 경우 솔직히 말하세요
6. 질문의 성향에 따라 표준계약서 내용이 제공될 수 있습니다. 표준계약서는 계약서 작성 시 형식 참고용 템플릿입니다. 표준계약서의 형식이 무조건 옳은 것은 아니며 표준계약서의 내용에 매몰되어선 안됩니다.
7. 사용자 계약서와 표준계약서의 차이를 명확히 인지하고 구분하세요. 질문이 표준계약서라고 직접 명시하지 않으면 그것은 사용자 계약서에 대한 내용입니다."""
        
        # 사용자 프롬프트
        user_prompt = f"""
수집된 정보:

{context}

질문: {state['user_message']}

수집된 정보는 질문에 답하기 위해 선별되어 수집된 정보들입니다. 이를 종합하여 질문에 답변해주세요.
또한 답변은 구조화된 형태일수록 좋습니다."""
        
        try:
            # 프롬프트 로깅
            # logger.info("=" * 80)
            # logger.info("[generate_response] LLM 호출 프롬프트")
            # logger.info("=" * 80)
            # logger.info(f"[SYSTEM]\n{system_prompt}")
            # logger.info("-" * 80)
            # logger.info(f"[USER]\n{user_prompt}")
            # logger.info("=" * 80)
            
            # o1 시리즈는 temperature 미지원 (항상 1)
            response_text = self.runtime.call_llm(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                model="gpt-5.1",
                reasoning_effort="low",  # "low", "medium", "high"
                # temperature=0.3,
                max_completion_tokens=8000
            )
            
            # 출처 추출
            sources = self._extract_sources(state)
            
            state["final_response"] = response_text
            state["sources"] = sources
            
            elapsed_time = time.time() - start_time
            logger.info(f"[generate_response] 답변 생성 완료: {len(response_text)}자, 소요 시간: {elapsed_time:.2f}초")
            
        except Exception as e:
            logger.error(f"[generate_response] 오류 발생: {e}")
            state["final_response"] = "죄송합니다. 답변 생성 중 오류가 발생했습니다."
            state["sources"] = []
        
        return state
    
    # ============================================
    # 조건부 엣지 함수
    # ============================================
    
    def should_execute_tools(self, state: AgentState) -> str:
        """
        툴 실행 여부 및 방식 결정
        
        Returns:
            "execute_parallel": 병렬 실행
            "execute_sequential": 순차 실행
            "no_tools": 툴 없음 (바로 respond)
            "skip_to_evaluator": 중복 스킵 (evaluator로)
        """
        next_tools = state.get("next_tools", [])
        all_tools_skipped = state.get("all_tools_skipped", False)
        
        # 툴이 없는 경우
        if not next_tools:
            # 중복으로 인해 스킵된 경우 → evaluator로 (충분성 평가 필요)
            if all_tools_skipped:
                logger.warning(
                    "[should_execute_tools] 중복으로 툴 스킵됨 → "
                    "evaluator로 (충분성 평가)"
                )
                return "skip_to_evaluator"
            
            # 의도적으로 툴 선택 안 함 → respond
            logger.info("[should_execute_tools] 툴 선택 안 함 → respond")
            return "no_tools"
        
        # 툴이 있으면 병렬/순차 실행 결정
        if self.can_execute_parallel(state):
            logger.info(f"[should_execute_tools] {len(next_tools)}개 툴 병렬 실행")
            return "execute_parallel"
        else:
            logger.info(f"[should_execute_tools] {len(next_tools)}개 툴 순차 실행")
            return "execute_sequential"
    
    def should_continue(self, state: AgentState) -> str:
        """반복 계속 여부 결정"""
        decision_log = state.get("decision_log", [])
        
        if not decision_log:
            return "finish"
        
        last_decision = decision_log[-1]
        action = last_decision.get("action", "finish")
        
        if action == "continue":
            return "continue"
        else:
            return "finish"
    
    # ============================================
    # 헬퍼 메서드
    # ============================================
    
    def _build_status_summary(self, state: AgentState) -> str:
        """현재 상태 요약 (계획 수립용)"""
        # 수집된 정보 상세 가져오기 (evaluator와 동일한 방식)
        collected_info = state.get("collected_info", [])
        collected_info_detail = self._build_collected_info_detail(collected_info)
        
        # 탐색 상태 정보
        explored_articles = state.get("explored_articles", [])
        unexplored_articles = state.get("unexplored_articles", [])
        
        # 탐색 상태 포맷팅
        explored_text = "\n".join(f"  - {article}" for article in explored_articles) if explored_articles else "  (없음)"
        unexplored_text = "\n".join(f"  - {article}" for article in unexplored_articles) if unexplored_articles else "  (없음)"

        summary_parts = [
            f"[사용자 계약서 탐색 상태]",
            f"- 탐색한 항목 ({len(explored_articles)}개):",
            explored_text,
            f"\n- 미탐색 항목 ({len(unexplored_articles)}개):",
            unexplored_text,
            f"\n수집된 정보:\n{collected_info_detail}"
        ]

        return "\n".join(summary_parts)
    

    
    def _build_info_summary(self, state: AgentState) -> str:
        """수집된 정보 요약 - 더 이상 사용하지 않음 (상세 정보로 대체)"""
        # 이 메서드는 더 이상 evaluate_sufficiency에서 사용되지 않음
        # 하위 호환성을 위해 유지
        collected_info = state.get("collected_info", [])
        
        if not collected_info:
            return "수집된 정보: 없음"
        
        summary_parts = [f"수집된 정보: {len(collected_info)}개"]
        
        for idx, info in enumerate(collected_info, 1):
            source = info.get("source", "unknown")
            summary_parts.append(f"{idx}. {source}")
        
        return "\n".join(summary_parts)
    
    def _build_collected_info_detail(self, collected_info: List[Dict[str, Any]]) -> str:
        """수집된 정보 상세 (충분성 평가용) - 실제 내용 포함"""
        if not collected_info:
            return "없음"
        
        sections = []
        
        # 사용자 계약서 조항 (중복 제거 및 통합)
        articles_dict = {}  # {article_no: {title, text, content}}
        exhibits_dict = {}  # {exhibit_no: {title, text, content}}
        
        for info in collected_info:
            source = info.get("source")
            content = info.get("content", {})
            
            # get_article_by_index, get_article_by_title
            if source in ["get_article_by_index", "get_article_by_title"]:
                matched_articles = content.get("matched_articles", [])
                for article in matched_articles:
                    article_no = article.get("article_no", 0)
                    
                    # 별지는 article_no가 음수로 저장됨
                    if article_no < 0:
                        exhibit_no = str(-article_no)
                        if exhibit_no not in exhibits_dict:
                            exhibits_dict[exhibit_no] = {
                                "title": article.get("title", ""),  # "별지3 검수 기준표" 형식
                                "text": article.get("text", ""),    # "별지3"
                                "content": article.get("content", [])
                            }
                    else:
                        article_no_str = str(article_no)
                        if article_no_str and article_no_str not in articles_dict:
                            articles_dict[article_no_str] = {
                                "title": article.get("title", ""),
                                "text": article.get("text", ""),
                                "content": article.get("content", [])
                            }
            
            # hybrid_search
            elif source == "hybrid_search":
                results = content.get("results", {})
                for topic_name, articles_list in results.items():
                    for article in articles_list:
                        article_no = article.get("article_no", 0)
                        
                        # hybrid_search는 별지를 포함하지 않음 (조만 검색)
                        if article_no > 0:
                            article_no_str = str(article_no)
                            if article_no_str not in articles_dict:
                                articles_dict[article_no_str] = {
                                    "title": article.get("title", ""),
                                    "text": article.get("text", ""),
                                    "content": article.get("content", [])
                                }
        
        # 조항 텍스트 생성
        if articles_dict or exhibits_dict:
            articles_text = "[사용자 계약서 조항]"
            
            # 조 번호 순으로 정렬
            for article_no in sorted(articles_dict.keys(), key=lambda x: int(x) if x.isdigit() else 999):
                article = articles_dict[article_no]
                title = article["title"]
                text = article.get("text", "")
                content = article["content"]
                
                # text가 있으면 사용 (예: "제5조(가공서비스의 범위 및 수행)")
                # 없으면 조합 (예: "제5조(목적)")
                header = text if text else f"제{article_no}조({title})"
                
                articles_text += f"\n{header}\n"
                
                # content 처리 - "하위 항목:" 제거
                if isinstance(content, list) and content:
                    articles_text += "\n".join(content)
                else:
                    articles_text += str(content) if content else ""
                articles_text += "\n"
            
            # 별지
            for exhibit_no in sorted(exhibits_dict.keys(), key=lambda x: int(x) if x.isdigit() else 999):
                exhibit = exhibits_dict[exhibit_no]
                title = exhibit["title"]  # "별지3 검수 기준표" 형식으로 이미 저장됨
                content = exhibit["content"]
                
                # title이 이미 "별지3 검수 기준표" 형식이므로 그대로 사용
                articles_text += f"\n{title}\n"
                
                # content 처리 - "하위 항목:" 제거
                if isinstance(content, list) and content:
                    articles_text += "\n".join(content)
                else:
                    articles_text += str(content) if content else ""
                articles_text += "\n"
            
            sections.append(articles_text.strip())
        
        # 3. 표준계약서 템플릿 (lookup_standard_contract)
        standard_info = next((info for info in collected_info if info.get("source") == "lookup_standard_contract"), None)
        if standard_info:
            content = standard_info.get("content", {})
            standard_articles = content.get("standard_articles", [])
            
            if standard_articles:
                template_text = "[계약서 작성 참고용 템플릿(표준계약서) 조항]"
                
                for article in standard_articles:
                    parent_id = article.get("parent_id", "")  # "제18조"
                    title = article.get("title", "")
                    chunks = article.get("chunks", [])
                    
                    # parent_id와 title로 헤더 구성 (사용자 계약서와 동일한 형식)
                    template_text += f"\n{parent_id}({title})\n"
                    
                    # chunks 배열의 각 text_raw를 개행으로 연결 (원문 구조 유지)
                    if isinstance(chunks, list) and chunks:
                        template_text += "\n".join(chunks)
                    template_text += "\n"
                
                sections.append(template_text.strip())
        
        return "\n\n".join(sections) if sections else "없음"
    
    def _build_context_from_collected_info(self, state: AgentState) -> str:
        """수집된 정보를 컨텍스트로 변환 (상세 포맷팅)"""
        sections = []
        
        # 1. 이전 대화 컨텍스트 추가 (필요한 경우)
        need_previous_context = state.get("need_previous_context", False)
        if need_previous_context:
            previous_context = self._build_previous_context(state)
            if previous_context:
                sections.append(previous_context)
        
        # 2. 수집된 정보 추가
        collected_info = state.get("collected_info", [])
        if collected_info:
            # evaluator/planner와 동일한 방식 사용 (중복 제거, 정렬, 구조화)
            collected_detail = self._build_collected_info_detail(collected_info)
            sections.append(collected_detail)
        
        if not sections:
            return "관련 정보를 찾을 수 없습니다."
        
        return "\n\n".join(sections)
    
    def _build_previous_context(self, state: AgentState) -> str:
        """
        이전 대화를 "수집된 정보" 형식으로 변환
        
        Args:
            state: 현재 상태
            
        Returns:
            이전 대화 컨텍스트 문자열
        """
        messages = state.get("messages", [])
        
        # 현재 질문 제외하고 직전 1턴만 (최근 2개 메시지)
        if len(messages) <= 1:
            return ""
        
        previous_turn = messages[-3:-1] if len(messages) >= 3 else messages[:-1]
        
        if not previous_turn:
            return ""
        
        context_parts = ["[이전 대화 내용]"]
        
        for msg in previous_turn:
            role = msg.get("role", "")
            content = msg.get("content", "")
            
            if role == "user":
                context_parts.append(f"\n이전 질문:\n{content}")
            elif role == "assistant":
                context_parts.append(f"\n이전 답변:\n{content}")
        
        return "\n".join(context_parts)
    
    def _extract_sources(self, state: AgentState) -> List[Dict[str, Any]]:
        """출처 추출"""
        sources = []
        
        # TODO: collected_info에서 출처 정보 추출
        
        return sources
    
    def _load_contract_structure(self, contract_id: str) -> List[str]:
        """
        DB에서 사용자 계약서 구조를 로드하여 조 목록 반환
        
        Args:
            contract_id: 계약서 ID
        
        Returns:
            조 목록 (예: ['제1조(목적)', '제2조(정의)', ...])
        """
        try:
            from backend.shared.database import SessionLocal, ContractDocument
            
            db = SessionLocal()
            try:
                contract = db.query(ContractDocument).filter(
                    ContractDocument.contract_id == contract_id
                ).first()
                
                if not contract or not contract.parsed_data:
                    logger.warning(f"[_load_contract_structure] 계약서 데이터 없음: {contract_id}")
                    return []
                
                parsed_data = contract.parsed_data
                articles = parsed_data.get('articles', [])
                exhibits = parsed_data.get('exhibits', [])
                
                article_list = []
                
                # 조 목록 추출 (서문 제외)
                for article in articles:
                    article_no = article.get('number')
                    if article_no == 0:  # 서문 제외
                        continue
                    
                    title = article.get('title', '')
                    text = article.get('text', '')
                    
                    if text:
                        article_list.append(text)
                    elif title:
                        article_list.append(f"제{article_no}조({title})")
                    else:
                        article_list.append(f"제{article_no}조")
                
                # 별지 목록 추가
                for exhibit in exhibits:
                    exhibit_no = exhibit.get('number')
                    title = exhibit.get('title', '')
                    
                    if title:
                        article_list.append(f"별지{exhibit_no} {title}")
                    else:
                        article_list.append(f"별지{exhibit_no}")
                
                logger.info(f"[_load_contract_structure] 로드 완료: {len(article_list)}개 항목")
                return article_list
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"[_load_contract_structure] 오류 발생: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []
    
    def _extract_article_refs(self, tool_name: str, result: Any) -> List[str]:
        """
        툴 실행 결과에서 article_refs 추출
        
        Args:
            tool_name: 실행한 툴 이름
            result: 툴 실행 결과
            
        Returns:
            article_refs 리스트 (예: ["제3조", "별지1", "표준_제5조"])
        """
        article_refs = []
        
        if not result.success:
            return article_refs
        
        try:
            # hybrid_search 결과 처리
            if tool_name == "hybrid_search" and hasattr(result, 'data'):
                data = result.data
                if hasattr(data, 'results'):
                    for topic_name, articles_list in data.results.items():
                        for article in articles_list:
                            article_no = getattr(article, 'article_no', 0)
                            if article_no < 0:
                                # 별지
                                exhibit_no = abs(article_no)
                                article_refs.append(f"별지{exhibit_no}")
                            else:
                                # 조
                                article_refs.append(f"제{article_no}조")
            
            # get_article_by_index 결과 처리
            elif tool_name == "get_article_by_index" and hasattr(result, 'data'):
                data = result.data
                if hasattr(data, 'matched_articles'):
                    for article in data.matched_articles:
                        article_no = getattr(article, 'article_no', 0)
                        if article_no < 0:
                            exhibit_no = abs(article_no)
                            article_refs.append(f"별지{exhibit_no}")
                        else:
                            article_refs.append(f"제{article_no}조")
            
            # get_article_by_title 결과 처리
            elif tool_name == "get_article_by_title" and hasattr(result, 'data'):
                data = result.data
                if hasattr(data, 'matched_articles'):
                    for article in data.matched_articles:
                        article_no = getattr(article, 'article_no', 0)
                        if article_no < 0:
                            exhibit_no = abs(article_no)
                            article_refs.append(f"별지{exhibit_no}")
                        else:
                            article_refs.append(f"제{article_no}조")
            
            # lookup_standard_contract 결과 처리
            elif tool_name == "lookup_standard_contract" and hasattr(result, 'data'):
                data = result.data
                if hasattr(data, 'standard_articles'):
                    for article in data.standard_articles:
                        parent_id = getattr(article, 'parent_id', '')
                        if parent_id:
                            # parent_id가 "제5조" 또는 "별지1" 형식
                            article_refs.append(f"표준_{parent_id}")
            
        except Exception as e:
            logger.error(f"[_extract_article_refs] 오류 발생: {e}")
            import traceback
            logger.error(traceback.format_exc())
        
        return article_refs
    
    def _update_explored_articles(self, state: AgentState, tool_name: str, result: Any):
        """
        툴 실행 결과에 따라 explored_articles와 unexplored_articles 업데이트
        
        Args:
            state: 현재 상태
            tool_name: 실행한 툴 이름
            result: 툴 실행 결과
        """
        if not result.success:
            return
        
        explored = state.get("explored_articles", [])
        unexplored = state.get("unexplored_articles", [])
        
        try:
            # hybrid_search 결과 처리
            if tool_name == "hybrid_search" and hasattr(result, 'data'):
                data = result.data
                if hasattr(data, 'results'):
                    results = data.results
                    for topic_name, articles_list in results.items():
                        for article in articles_list:
                            # Pydantic 모델이므로 속성으로 접근
                            article_text = getattr(article, 'text', '')
                            if article_text and article_text not in explored:
                                explored.append(article_text)
                                if article_text in unexplored:
                                    unexplored.remove(article_text)
            
            # get_article_by_index 결과 처리
            elif tool_name == "get_article_by_index" and hasattr(result, 'data'):
                data = result.data
                if hasattr(data, 'matched_articles'):
                    for article in data.matched_articles:
                        article_no = getattr(article, 'article_no', 0)
                        
                        # 별지는 article_no가 음수
                        if article_no < 0:
                            # title이 "별지3 검수 기준표" 형식으로 저장됨
                            article_text = getattr(article, 'title', '')
                        else:
                            # 조는 text 사용 (예: "제5조(가공서비스의 범위 및 수행)")
                            article_text = getattr(article, 'text', '')
                        
                        if article_text and article_text not in explored:
                            explored.append(article_text)
                            if article_text in unexplored:
                                unexplored.remove(article_text)
            
            # get_article_by_title 결과 처리
            elif tool_name == "get_article_by_title" and hasattr(result, 'data'):
                data = result.data
                if hasattr(data, 'matched_articles'):
                    for article in data.matched_articles:
                        article_no = getattr(article, 'article_no', 0)
                        
                        # 별지는 article_no가 음수
                        if article_no < 0:
                            # title이 "별지3 검수 기준표" 형식으로 저장됨
                            article_text = getattr(article, 'title', '')
                        else:
                            # 조는 text 사용
                            article_text = getattr(article, 'text', '')
                        
                        if article_text and article_text not in explored:
                            explored.append(article_text)
                            if article_text in unexplored:
                                unexplored.remove(article_text)
            
            state["explored_articles"] = explored
            state["unexplored_articles"] = unexplored
            
        except Exception as e:
            logger.error(f"[_update_explored_articles] 오류 발생: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    def get_metrics(self) -> Dict[str, Any]:
        """
        에이전트 실행 메트릭 조회
        
        Returns:
            메트릭 딕셔너리
        """
        return self.runtime.get_metrics()
    
    def reset_metrics(self):
        """메트릭 초기화"""
        self.runtime.reset_metrics()
    
    def clear_cache(self):
        """캐시 삭제"""
        self.runtime.clear_cache()
    
    # ============================================
    # 병렬 처리 관련 메서드
    # ============================================
    
    def can_execute_parallel(self, state: AgentState) -> bool:
        """
        병렬 실행 가능 여부 판단
        
        Args:
            state: 현재 상태
            
        Returns:
            병렬 실행 가능 여부
        """
        # 여러 툴이 선택된 경우 병렬 실행 가능
        next_tools = state.get("next_tools", [])
        return len(next_tools) > 1
    
    def execute_parallel_tools(self, state: AgentState) -> AgentState:
        """
        병렬 툴 실행 (여러 툴 동시 실행)
        
        Args:
            state: 현재 상태
            
        Returns:
            업데이트된 상태
        """
        next_tools = state.get("next_tools", [])
        if not next_tools:
            return state
        
        contract_id = state["contract_id"]
        
        logger.info(f"[execute_parallel_tools] {len(next_tools)}개 툴 병렬 실행 시작")
        
        # ThreadPoolExecutor로 병렬 실행
        results = []
        with ThreadPoolExecutor(max_workers=min(len(next_tools), 4)) as executor:
            future_to_tool = {}
            
            for tool_info in next_tools:
                tool_name = tool_info.get("tool")
                args = tool_info.get("args", {})
                tool_call_id = tool_info.get("tool_call_id")
                
                tool_args = {**args, "contract_id": contract_id}
                future = executor.submit(
                    self.runtime.execute_tool,
                    tool_name,
                    tool_args,
                    True  # retry_on_failure
                )
                future_to_tool[future] = (tool_name, args, tool_call_id)
            
            # 결과 수집
            for future in as_completed(future_to_tool):
                tool_name, args, tool_call_id = future_to_tool[future]
                try:
                    result = future.result()
                    results.append((tool_name, args, tool_call_id, result))
                    logger.info(f"[execute_parallel_tools] 완료: {tool_name}")
                except Exception as e:
                    logger.error(f"[execute_parallel_tools] 실패: {tool_name}, {e}")
        
        # 결과를 상태에 반영
        for tool_name, args, tool_call_id, result in results:
            # tool_history에 기록
            state["tool_history"].append({
                "tool": tool_name,
                "args": args,
                "result": result.dict() if hasattr(result, 'dict') else result,
                "tool_call_id": tool_call_id,
                "timestamp": datetime.now().isoformat()
            })
            
            # 툴별 상태 업데이트 (explored_articles 업데이트)
            self._update_explored_articles(state, tool_name, result)
            
            # collected_info에 추가
            if result.success and result.data:
                # article_refs 추출
                article_refs = self._extract_article_refs(tool_name, result)
                
                info = CollectedInfo(
                    source=tool_name,
                    content=result.data.dict() if hasattr(result.data, 'dict') else result.data,
                    relevance=result.relevance_score or 0.8,
                    timestamp=datetime.now().isoformat(),
                    article_refs=article_refs
                )
                state["collected_info"].append(info.dict())
        
        logger.info(f"[execute_parallel_tools] 병렬 실행 완료: {len(results)}개 툴")
        
        return state

    # ============================================
    # 체크포인트 복원 관련 메서드
    # ============================================
    
    def get_checkpoint_state(self, session_id: str, contract_id: str) -> Optional[Dict[str, Any]]:
        """
        마지막 체크포인트 조회
        
        Args:
            session_id: 세션 ID
            contract_id: 계약서 ID
        
        Returns:
            체크포인트 상태 (없으면 None)
        """
        return self.persistence.get_state(self.app, session_id, contract_id)
    
    def update_checkpoint_state(
        self,
        session_id: str,
        contract_id: str,
        updates: Dict[str, Any]
    ) -> bool:
        """
        체크포인트 상태 업데이트
        
        Args:
            session_id: 세션 ID
            contract_id: 계약서 ID
            updates: 업데이트할 상태
        
        Returns:
            성공 여부
        """
        return self.persistence.update_state(self.app, session_id, contract_id, updates)
    
    def recover_from_checkpoint(
        self,
        session_id: str,
        contract_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        체크포인트에서 복원
        
        Args:
            session_id: 세션 ID
            contract_id: 계약서 ID
        
        Returns:
            복원된 상태 (없으면 None)
        """
        return AgentRecovery.recover_from_checkpoint(self.app, session_id, contract_id)
    
    def resume_from_checkpoint(
        self,
        session_id: str,
        contract_id: str,
        new_input: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        체크포인트에서 재개
        
        Args:
            session_id: 세션 ID
            contract_id: 계약서 ID
            new_input: 새로운 입력 (상태 업데이트용)
        
        Returns:
            최종 상태 (실패 시 None)
        """
        return AgentRecovery.resume_from_checkpoint(
            self.app,
            session_id,
            contract_id,
            new_input
        )
    
    def get_partial_result(
        self,
        session_id: str,
        contract_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        부분 결과 추출
        
        에러 발생 시 복원된 상태에서 부분 결과를 추출합니다.
        
        Args:
            session_id: 세션 ID
            contract_id: 계약서 ID
        
        Returns:
            부분 결과 (없으면 None)
        """
        recovered_state = self.recover_from_checkpoint(session_id, contract_id)
        return AgentRecovery.get_partial_result(recovered_state)
    
    # ============================================
    # 사고 과정 이벤트 생성 메서드
    # ============================================
    
    def _generate_tool_selection_events(
        self,
        next_tools: List[Dict[str, Any]],
        contract_id: str
    ):
        """
        도구 선택 완료 시 사고 과정 이벤트 생성
        
        Args:
            next_tools: 선택된 도구 리스트
            contract_id: 계약서 ID
            
        Yields:
            thinking 이벤트
        """
        for tool_info in next_tools:
            tool_name = tool_info.get("tool")
            args = tool_info.get("args", {})
            
            if tool_name == "get_article_by_index":
                # 제1조, 제2조... (최대 3개)
                article_numbers = args.get("article_numbers", [])
                if article_numbers:
                    articles_text = ", ".join([f"제{num}조" for num in article_numbers[:3]])
                    if len(article_numbers) > 3:
                        articles_text += "..."
                    yield {"type": "thinking", "step": "tool_selected", "content": articles_text}
            
            elif tool_name == "get_article_by_title":
                # 목적 조항, 정의 조항... (최대 3개)
                keywords = args.get("keywords", [])
                if keywords:
                    keywords_text = ", ".join([f"{kw} 조항" for kw in keywords[:3]])
                    if len(keywords) > 3:
                        keywords_text += "..."
                    yield {"type": "thinking", "step": "tool_selected", "content": keywords_text}
            
            elif tool_name == "lookup_standard_contract":
                user_article_numbers = args.get("user_article_numbers")
                topic = args.get("topic")
                
                if user_article_numbers:
                    # A1 매칭 결과 확인
                    matched_std_articles = self._get_matched_std_articles(contract_id, user_article_numbers)
                    
                    if matched_std_articles:
                        # A1 매칭 결과 존재
                        articles_text = ", ".join(matched_std_articles[:3])
                        if len(matched_std_articles) > 3:
                            articles_text += "..."
                        yield {"type": "thinking", "step": "tool_selected", "content": f"표준계약서 {articles_text}"}
                    else:
                        # A1 매칭 결과 없음
                        yield {"type": "thinking", "step": "std_contract_listing", "content": "표준계약서 조문 리스트업..."}
                elif topic:
                    # topic만 사용
                    yield {"type": "thinking", "step": "std_contract_listing", "content": "표준계약서 조문 리스트업..."}
            
            elif tool_name == "hybrid_search":
                # 주제별 쿼리 검색 - "주제: 🔍 쿼리, 쿼리..." 형식
                topics = args.get("topics", [])
                
                for topic_info in topics:
                    topic_name = topic_info.get("topic_name", "")
                    queries = topic_info.get("queries", [])
                    
                    if topic_name and queries:
                        # 쿼리들을 쉼표로 나열 (이모지는 주제 앞에만)
                        queries_text = ", ".join(queries)
                        content = f"{topic_name}: 🔍 {queries_text}"
                        yield {"type": "thinking", "step": "hybrid_search_topic", "content": content}
    
    def _generate_evaluation_events(self, state: AgentState, previous_user_articles: set = None, previous_std_articles: set = None):
        """
        evaluate_sufficiency 진입 시 사고 과정 이벤트 생성
        
        Args:
            state: 현재 상태
            previous_user_articles: 이전에 읽은 사용자 조항 (중복 제거용)
            previous_std_articles: 이전에 읽은 표준 조항 (중복 제거용)
            
        Yields:
            thinking 이벤트
        """
        collected_info = state.get("collected_info", [])
        
        # 사용자 계약서 조항 추출 (중복 제거)
        user_articles = set()
        std_articles = set()
        
        # 이전에 읽은 조항 초기화
        if previous_user_articles is None:
            previous_user_articles = set()
        if previous_std_articles is None:
            previous_std_articles = set()
        
        for info in collected_info:
            source = info.get("source")
            content = info.get("content", {})
            
            if source in ["get_article_by_index", "get_article_by_title", "hybrid_search"]:
                # 사용자 계약서
                if source == "hybrid_search":
                    results = content.get("results", {})
                    for topic_name, articles_list in results.items():
                        for article in articles_list:
                            text = article.get("text", "")
                            if text:
                                user_articles.add(text)
                else:
                    matched_articles = content.get("matched_articles", [])
                    for article in matched_articles:
                        article_no = article.get("article_no", 0)
                        if article_no < 0:
                            # 별지
                            title = article.get("title", "")
                            if title:
                                user_articles.add(title)
                        else:
                            # 조
                            text = article.get("text", "")
                            if text:
                                user_articles.add(text)
            
            elif source == "lookup_standard_contract":
                # 표준계약서
                standard_articles = content.get("standard_articles", [])
                for article in standard_articles:
                    parent_id = article.get("parent_id", "")
                    title = article.get("title", "")
                    if parent_id and title:
                        std_articles.add(f"{parent_id}({title})")
        
        # Read 이벤트 생성 (최대 5개, 새로 추가된 것만)
        new_user_articles = user_articles - previous_user_articles
        new_std_articles = std_articles - previous_std_articles
        
        if new_user_articles:
            user_articles_list = sorted(list(new_user_articles))[:5]
            articles_text = ", ".join(user_articles_list)
            if len(new_user_articles) > 5:
                articles_text += "..."
            yield {"type": "thinking", "step": "reading", "content": f"Reading {articles_text}"}
        
        if new_std_articles:
            std_articles_list = sorted(list(new_std_articles))[:5]
            articles_text = ", ".join(std_articles_list)
            if len(new_std_articles) > 5:
                articles_text += "..."
            yield {"type": "thinking", "step": "reading", "content": f"Reading 표준계약서 {articles_text}"}
        
        # 마지막에 업데이트된 조항 정보 반환 (특별한 마커로)
        yield {"_internal_update": True, "user_articles": user_articles, "std_articles": std_articles}
    
    def _get_matched_std_articles(
        self,
        contract_id: str,
        user_article_numbers: List[int]
    ) -> List[str]:
        """
        A1 매칭 결과에서 표준 조항 추출
        
        Args:
            contract_id: 계약서 ID
            user_article_numbers: 사용자 조 번호 리스트
            
        Returns:
            표준 조항 리스트 (예: ["제1조(목적)", "제2조(정의)"])
        """
        try:
            from backend.shared.database import SessionLocal, ValidationResult
            
            db = SessionLocal()
            try:
                validation = db.query(ValidationResult).filter(
                    ValidationResult.contract_id == contract_id
                ).first()
                
                if not validation or not validation.completeness_check:
                    return []
                
                matching_details = validation.completeness_check.get('matching_details', [])
                
                # 사용자 조 번호로 표준 조 parent_id 추출
                standard_parent_ids = set()
                
                for detail in matching_details:
                    user_no = detail.get('user_article_no')
                    if user_no in user_article_numbers:
                        matched_articles = detail.get('matched_articles', [])
                        standard_parent_ids.update(matched_articles)
                
                return sorted(list(standard_parent_ids))
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"[_get_matched_std_articles] 오류 발생: {e}")
            return []
