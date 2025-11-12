"""
AutonomousAgent - LangGraph 기반 자율 탐색 에이전트

반복적 사고-행동-평가 루프를 통해 사용자 질문에 답변합니다.
"""

import logging
import json
from typing import Dict, Any, List, Optional
from datetime import datetime
from openai import AzureOpenAI

from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from concurrent.futures import ThreadPoolExecutor, as_completed

from backend.chatbot_agent.models import AgentState, DecisionLog, CollectedInfo
from backend.chatbot_agent.tools import ToolRegistry
from backend.chatbot_agent.lightweight_classifier import LightweightClassifier
from backend.chatbot_agent.agent_runtime import AgentRuntime
from backend.chatbot_agent.agent_persistence import AgentPersistence
from backend.chatbot_agent.agent_recovery import AgentRecovery

logger = logging.getLogger(__name__)


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
        azure_client: AzureOpenAI,
        tool_registry: ToolRegistry,
        max_iterations: int = 5,
        enable_cache: bool = True,
        persistence_mode: str = "sqlite",
        checkpoint_db_path: Optional[str] = None
    ):
        """
        Args:
            azure_client: Azure OpenAI 클라이언트
            tool_registry: 툴 레지스트리
            max_iterations: 최대 반복 횟수
            enable_cache: LLM 캐시 활성화 여부
            persistence_mode: 영속화 모드 ("memory" 또는 "sqlite")
            checkpoint_db_path: 체크포인트 DB 경로 (persistence_mode="sqlite"인 경우)
        """
        self.azure_client = azure_client
        self.tool_registry = tool_registry
        self.max_iterations = max_iterations
        self.classifier = LightweightClassifier()
        
        # AgentRuntime 초기화
        self.runtime = AgentRuntime(
            azure_client=azure_client,
            tool_registry=tool_registry,
            enable_cache=enable_cache,
            max_retries=2
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
        
        Returns:
            컴파일되지 않은 StateGraph (AgentPersistence에서 컴파일)
        """
        # StateGraph 초기화
        workflow = StateGraph(AgentState)
        
        # 노드 추가
        workflow.add_node("tool_needed_check", self.check_tool_needed)
        workflow.add_node("planner", self.plan_next_action)
        workflow.add_node("executor", self.execute_tools)
        workflow.add_node("parallel_executor", self.execute_parallel_tools)
        workflow.add_node("evaluator", self.evaluate_sufficiency)
        workflow.add_node("respond", self.generate_response)
        
        # 엣지 연결
        workflow.set_entry_point("tool_needed_check")
        
        # tool_needed_check → planner or respond
        workflow.add_conditional_edges(
            "tool_needed_check",
            self.should_use_tools,
            {
                "use_tools": "planner",
                "direct_response": "respond"
            }
        )
        
        # planner → executor or parallel_executor
        workflow.add_conditional_edges(
            "planner",
            self.should_execute_parallel,
            {
                "parallel": "parallel_executor",
                "sequential": "executor"
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
    
    def run(
        self,
        contract_id: str,
        user_message: str,
        session_id: str
    ) -> AgentState:
        """
        에이전트 실행
        
        Args:
            contract_id: 계약서 ID
            user_message: 사용자 메시지
            session_id: 세션 ID
            
        Returns:
            최종 AgentState
        """
        # 초기 상태 구성
        initial_state: AgentState = {
            "contract_id": contract_id,
            "user_message": user_message,
            "session_id": session_id,
            "messages": [HumanMessage(content=user_message)],
            "contract_structure": None,
            "tool_history": [],
            "collected_info": [],
            "explored_articles": [],
            "unexplored_articles": [],
            "iteration_count": 0,
            "max_iterations": self.max_iterations,
            "decision_log": [],
            "next_tool": None,
            "final_response": None,
            "sources": []
        }
        
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
            
            logger.info(
                f"[AutonomousAgent] 실행 완료: "
                f"{final_state.get('iteration_count', 0)}회 반복, "
                f"{len(final_state.get('tool_history', []))}개 툴 실행"
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
    
    def check_tool_needed(self, state: AgentState) -> AgentState:
        """
        툴 사용 필요성 판단 (규칙 기반 + LLM)
        
        Args:
            state: 현재 상태
            
        Returns:
            업데이트된 상태
        """
        user_message = state["user_message"]
        
        logger.info("[check_tool_needed] 툴 필요성 판단 시작")
        
        # 1. 규칙 기반 빠른 판단
        quick_result = self.classifier.classify(user_message)
        
        if quick_result is not None:
            needs_tools = quick_result.get("needs_tools", True)
            reasoning = quick_result.get("reasoning", "규칙 기반 판단")
            confidence = quick_result.get("confidence", 0.8)
            
            decision = DecisionLog(
                step="tool_needed_check",
                reasoning=reasoning,
                action="use_tools" if needs_tools else "direct_response",
                confidence=confidence,
                timestamp=datetime.now().isoformat(),
                method="rule_based"
            )
            
            state["decision_log"].append(decision.dict())
            
            logger.info(
                f"[check_tool_needed] 규칙 기반 판단: "
                f"needs_tools={needs_tools}, confidence={confidence}"
            )
            
            return state
        
        # 2. LLM 판단
        prompt = f"""다음 질문이 계약서 내용 조회를 필요로 하는지 판단하세요.

질문: {user_message}

판단 기준:
- 계약서 조항, 내용, 조건 등을 물어보는 경우 → 툴 필요
- 일반적인 인사, 감사 표현 → 툴 불필요
- 계약서와 무관한 질문 → 툴 불필요

응답 형식 (JSON):
{{
    "needs_tools": true/false,
    "reasoning": "판단 근거"
}}

JSON만 응답하세요."""
        
        try:
            response_text = self.runtime.call_llm(
                messages=[
                    {
                        "role": "system",
                        "content": "당신은 질문 분석 전문가입니다. JSON 형식으로만 응답하세요."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                model="gpt-4o",
                temperature=0.2,
                max_tokens=200,
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response_text)
            
            needs_tools = result.get("needs_tools", True)
            reasoning = result.get("reasoning", "")
            
            decision = DecisionLog(
                step="tool_needed_check",
                reasoning=reasoning,
                action="use_tools" if needs_tools else "direct_response",
                confidence=0.9 if needs_tools else 0.8,
                timestamp=datetime.now().isoformat(),
                method="llm"
            )
            
            state["decision_log"].append(decision.dict())
            
            logger.info(
                f"[check_tool_needed] LLM 판단: "
                f"needs_tools={needs_tools}"
            )
            
        except Exception as e:
            logger.error(f"[check_tool_needed] 오류 발생: {e}")
            # 폴백: 툴 사용
            decision = DecisionLog(
                step="tool_needed_check",
                reasoning="판단 실패, 기본값 사용",
                action="use_tools",
                confidence=0.5,
                timestamp=datetime.now().isoformat(),
                method="fallback"
            )
            state["decision_log"].append(decision.dict())
        
        return state
    
    def plan_next_action(self, state: AgentState) -> AgentState:
        """
        다음 행동 계획 (중복 검색 방지 포함)
        
        Args:
            state: 현재 상태
            
        Returns:
            업데이트된 상태
        """
        logger.info("[plan_next_action] 행동 계획 수립 시작")
        
        user_message = state["user_message"]
        tool_history = state.get("tool_history", [])
        
        # 중복 검색 방지: 이미 실행한 툴 확인 (툴 이름 + 파라미터 해시)
        executed_tool_signatures = set()
        for history in tool_history:
            tool_name = history.get("tool")
            args = history.get("args", {})
            # 파라미터를 문자열로 변환하여 시그니처 생성
            signature = f"{tool_name}:{str(sorted(args.items()))}"
            executed_tool_signatures.add(signature)
        
        logger.info(f"[plan_next_action] 이미 실행한 툴: {len(executed_tool_signatures)}개")
        
        # 1. 규칙 기반 툴 제안
        quick_suggestion = self.classifier.suggest_tool(user_message)
        
        if quick_suggestion is not None:
            tool_name, args, reasoning = quick_suggestion
            
            # 중복 검색 방지 (시그니처 비교)
            signature = f"{tool_name}:{str(sorted(args.items()))}"
            if signature in executed_tool_signatures:
                logger.warning(f"[plan_next_action] 중복 툴 스킵: {tool_name} (이미 실행됨)")
                # 이미 실행했으면 종료 (더 이상 계획하지 않음)
                state["next_tool"] = None
                return state
            else:
                state["next_tool"] = {
                    "tool": tool_name,
                    "args": args,
                    "reasoning": reasoning
                }
                
                decision = DecisionLog(
                    step="planning",
                    reasoning=reasoning,
                    action=f"selected_tool: {tool_name}",
                    confidence=0.9,
                    timestamp=datetime.now().isoformat(),
                    method="rule_based"
                )
                state["decision_log"].append(decision.dict())
                
                logger.info(
                    f"[plan_next_action] 규칙 기반 제안: "
                    f"tool={tool_name}"
                )
                
                return state
        
        # 2. LLM 기반 계획
        status_summary = self._build_status_summary(state)
        tool_descriptions = self._build_tool_descriptions()
        
        # 이미 실행한 툴 목록을 명시적으로 제공
        executed_tools_list = []
        for history in tool_history:
            tool_name = history.get("tool")
            args = history.get("args", {})
            executed_tools_list.append(f"{tool_name} (args: {args})")
        
        prompt = f"""현재 상태를 분석하여 다음에 실행할 툴을 선택하세요.

{status_summary}

이미 실행한 툴:
{chr(10).join([f"- {t}" for t in executed_tools_list]) if executed_tools_list else "없음"}

사용 가능한 툴:
{tool_descriptions}

**중요**: 
1. 위에 나열된 "이미 실행한 툴"은 절대 다시 선택하지 마세요
2. 같은 툴을 다른 파라미터로 실행하는 것은 가능하지만, 같은 파라미터로는 불가능합니다

다음 툴을 선택하고 파라미터를 결정하세요.

응답 형식 (JSON):
{{
    "tool": "툴 이름",
    "args": {{}},
    "reasoning": "선택 근거"
}}

JSON만 응답하세요."""
        
        try:
            response_text = self.runtime.call_llm(
                messages=[
                    {
                        "role": "system",
                        "content": "당신은 계약서 분석 전문가입니다. JSON 형식으로만 응답하세요."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                model="gpt-4o",
                temperature=0.3,
                max_tokens=500,
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response_text)
            
            # 중복 검사: LLM이 이미 실행한 툴을 선택했는지 확인
            selected_tool = result.get("tool")
            selected_args = result.get("args", {})
            selected_signature = f"{selected_tool}:{str(sorted(selected_args.items()))}"
            
            if selected_signature in executed_tool_signatures:
                logger.warning(
                    f"[plan_next_action] LLM이 중복 툴 선택: {selected_tool}, "
                    f"args={selected_args}. 계획 취소."
                )
                state["next_tool"] = None
                return state
            
            state["next_tool"] = result
            
            decision = DecisionLog(
                step="planning",
                reasoning=result.get("reasoning", ""),
                action=f"selected_tool: {result.get('tool')}",
                timestamp=datetime.now().isoformat(),
                method="llm"
            )
            state["decision_log"].append(decision.dict())
            
            logger.info(
                f"[plan_next_action] LLM 계획: "
                f"tool={result.get('tool')}"
            )
            
        except Exception as e:
            logger.error(f"[plan_next_action] 오류 발생: {e}")
            # 폴백: 구조 파악 툴
            state["next_tool"] = {
                "tool": "get_contract_structure",
                "args": {},
                "reasoning": "계획 실패, 기본 툴 사용"
            }
        
        return state
    
    def execute_tools(self, state: AgentState) -> AgentState:
        """
        툴 실행 (타입 안전)
        
        Args:
            state: 현재 상태
            
        Returns:
            업데이트된 상태
        """
        next_tool = state.get("next_tool")
        
        if not next_tool:
            logger.warning("[execute_tools] next_tool이 없습니다")
            return state
        
        tool_name = next_tool.get("tool")
        args = next_tool.get("args", {})
        contract_id = state["contract_id"]
        
        logger.info(f"[execute_tools] 툴 실행: {tool_name}, args={args}")
        
        try:
            # 툴 실행 (AgentRuntime 사용)
            # contract_id를 args에 추가
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
                "timestamp": datetime.now().isoformat()
            })
            
            # 툴별 상태 업데이트
            if tool_name == "get_contract_structure" and result.success:
                state["contract_structure"] = result.data.dict() if hasattr(result.data, 'dict') else result.data
            
            # collected_info에 추가
            if result.success and result.data:
                info = CollectedInfo(
                    source=tool_name,
                    content=result.data.dict() if hasattr(result.data, 'dict') else result.data,
                    relevance=result.relevance_score or 0.8,
                    timestamp=datetime.now().isoformat(),
                    article_refs=[]
                )
                state["collected_info"].append(info.dict())
            
            logger.info(f"[execute_tools] 툴 실행 완료: success={result.success}")
            
        except Exception as e:
            logger.error(f"[execute_tools] 툴 실행 실패: {e}")
            import traceback
            logger.error(traceback.format_exc())
        
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
        
        # 수집된 정보 요약
        info_summary = self._build_info_summary(state)
        collected_info = state.get("collected_info", [])
        
        # LLM으로 충분성 평가
        prompt = f"""수집된 정보가 질문에 답변하기 충분한지 평가하세요.

질문: {state['user_message']}

{info_summary}

수집된 정보 상세:
{self._build_collected_info_detail(collected_info)}

평가 기준:
1. **질문에 직접 답변할 수 있는가?**
   - 수집된 정보에 질문의 답이 포함되어 있는가?
   - 예: "해지 조건이 있나?" → 해지 관련 조항이 수집되었는가?

2. **추가 탐색이 필요한가?**
   - 질문의 핵심 정보가 누락되었는가?
   - 이미 수집한 정보와 중복되는 탐색은 불필요

3. **중복 탐색 방지**
   - 이미 같은 주제로 검색했다면 추가 탐색 불필요
   - 반복 횟수: {state['iteration_count']}/{state['max_iterations']}

응답 형식 (JSON):
{{
    "is_sufficient": true/false,
    "reasoning": "평가 근거 (구체적으로)",
    "missing_info": "부족한 정보 (있다면, 없으면 null)"
}}

**중요**: 이미 관련 정보가 충분히 수집되었다면 is_sufficient=true로 판단하세요.

JSON만 응답하세요."""
        
        try:
            response_text = self.runtime.call_llm(
                messages=[
                    {
                        "role": "system",
                        "content": "당신은 정보 충분성 평가 전문가입니다. JSON 형식으로만 응답하세요."
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
            
            result = json.loads(response_text)
            
            is_sufficient = result.get("is_sufficient", False)
            reasoning = result.get("reasoning", "")
            
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
                f"is_sufficient={is_sufficient}"
            )
            
        except Exception as e:
            logger.error(f"[evaluate_sufficiency] 오류 발생: {e}")
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
        최종 답변 생성
        
        Args:
            state: 현재 상태
            
        Returns:
            업데이트된 상태
        """
        logger.info("[generate_response] 답변 생성 시작")
        
        # 수집된 정보를 컨텍스트로 변환
        context = self._build_context_from_collected_info(state)
        
        # 시스템 프롬프트
        system_prompt = """당신은 계약서 질의응답 전문가입니다.

규칙:
1. 제공된 계약서 내용만을 기반으로 답변하세요
2. 계약서에 없는 내용은 추측하지 마세요
3. 참조한 조항의 출처를 명시하세요
4. 명확하고 이해하기 쉽게 답변하세요
5. 불확실한 경우 솔직히 말하세요"""
        
        # 사용자 프롬프트
        user_prompt = f"""계약서 내용:
{context}

질문: {state['user_message']}

위 계약서 내용을 바탕으로 질문에 답변해주세요."""
        
        try:
            response_text = self.runtime.call_llm(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                model="gpt-4o",
                temperature=0.3,
                max_tokens=1000
            )
            
            # 출처 추출
            sources = self._extract_sources(state)
            
            state["final_response"] = response_text
            state["sources"] = sources
            
            logger.info(f"[generate_response] 답변 생성 완료: {len(response_text)}자")
            
        except Exception as e:
            logger.error(f"[generate_response] 오류 발생: {e}")
            state["final_response"] = "죄송합니다. 답변 생성 중 오류가 발생했습니다."
            state["sources"] = []
        
        return state
    
    # ============================================
    # 조건부 엣지 함수
    # ============================================
    
    def should_use_tools(self, state: AgentState) -> str:
        """툴 사용 여부 결정"""
        decision_log = state.get("decision_log", [])
        
        if not decision_log:
            return "use_tools"
        
        last_decision = decision_log[-1]
        action = last_decision.get("action", "use_tools")
        
        if action == "direct_response":
            return "direct_response"
        else:
            return "use_tools"
    
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
    
    def should_execute_parallel(self, state: AgentState) -> str:
        """병렬 실행 여부 결정"""
        if self.can_execute_parallel(state):
            logger.info("[should_execute_parallel] 병렬 실행 선택")
            return "parallel"
        else:
            return "sequential"
    
    # ============================================
    # 헬퍼 메서드
    # ============================================
    
    def _build_status_summary(self, state: AgentState) -> str:
        """현재 상태 요약"""
        summary_parts = [
            f"질문: {state['user_message']}",
            f"반복 횟수: {state.get('iteration_count', 0)}/{state['max_iterations']}",
            f"실행한 툴: {len(state.get('tool_history', []))}개",
            f"수집된 정보: {len(state.get('collected_info', []))}개"
        ]
        
        return "\n".join(summary_parts)
    
    def _build_tool_descriptions(self) -> str:
        """가용 툴 목록 생성 (파라미터 스키마 포함)"""
        descriptions = []
        
        tool_schemas = {
            "get_contract_structure": {
                "description": "사용자 계약서의 구조(조 목록, 별지 목록)를 파악합니다.",
                "parameters": {"contract_id": "계약서 ID (자동 제공)"}
            },
            "hybrid_search": {
                "description": "키워드 기반 하이브리드 검색으로 관련 조항을 찾습니다.",
                "parameters": {
                    "contract_id": "계약서 ID (자동 제공)",
                    "topics": "검색 주제 리스트 [{'topic_name': '주제명', 'queries': ['검색어1', '검색어2']}]"
                }
            },
            "get_article_by_index": {
                "description": "조 번호 또는 별지 번호로 직접 조회합니다.",
                "parameters": {
                    "contract_id": "계약서 ID (자동 제공)",
                    "article_numbers": "조 번호 리스트 [1, 3, 5]",
                    "exhibit_numbers": "별지 번호 리스트 [1, 2]"
                }
            },
            "get_article_by_title": {
                "description": "조 제목으로 조항을 검색합니다.",
                "parameters": {
                    "contract_id": "계약서 ID (자동 제공)",
                    "titles": "제목 키워드 리스트 ['데이터 제공', '보안']"
                }
            },
            "lookup_standard_contract": {
                "description": "표준계약서 조문을 조회합니다.",
                "parameters": {
                    "contract_id": "계약서 ID (자동 제공)",
                    "user_article_numbers": "사용자 조 번호 리스트 [3, 5] (매칭 기반)",
                    "topic": "검색 주제 문자열 (주제 기반)"
                }
            }
        }
        
        for tool_name in self.tool_registry.list_tools():
            if tool_name in tool_schemas:
                schema = tool_schemas[tool_name]
                desc = f"- **{tool_name}**: {schema['description']}\n"
                desc += f"  파라미터: {schema['parameters']}"
                descriptions.append(desc)
            else:
                try:
                    tool = self.tool_registry.get_tool(tool_name)
                    descriptions.append(f"- {tool_name}: {tool.description[:100]}...")
                except Exception as e:
                    logger.error(f"툴 설명 생성 실패: {tool_name}, {e}")
        
        return "\n".join(descriptions)
    
    def _build_info_summary(self, state: AgentState) -> str:
        """수집된 정보 요약"""
        collected_info = state.get("collected_info", [])
        
        if not collected_info:
            return "수집된 정보: 없음"
        
        summary_parts = [f"수집된 정보: {len(collected_info)}개"]
        
        for idx, info in enumerate(collected_info, 1):
            source = info.get("source", "unknown")
            summary_parts.append(f"{idx}. {source}")
        
        return "\n".join(summary_parts)
    
    def _build_collected_info_detail(self, collected_info: List[Dict[str, Any]]) -> str:
        """수집된 정보 상세 (충분성 평가용)"""
        if not collected_info:
            return "없음"
        
        details = []
        for idx, info in enumerate(collected_info, 1):
            source = info.get("source", "unknown")
            content = info.get("content", {})
            
            # 내용 요약
            if isinstance(content, dict):
                if "total_articles" in content:
                    details.append(f"{idx}. {source}: {content.get('total_articles', 0)}개 조")
                elif "results" in content:
                    total = sum(len(articles) for articles in content.get("results", {}).values())
                    details.append(f"{idx}. {source}: {total}개 조 검색됨")
                elif "matched_articles" in content:
                    details.append(f"{idx}. {source}: {len(content.get('matched_articles', []))}개 조")
                else:
                    details.append(f"{idx}. {source}: 정보 수집됨")
            else:
                details.append(f"{idx}. {source}: 정보 수집됨")
        
        return "\n".join(details)
    
    def _build_context_from_collected_info(self, state: AgentState) -> str:
        """수집된 정보를 컨텍스트로 변환"""
        collected_info = state.get("collected_info", [])
        
        if not collected_info:
            return "관련 정보를 찾을 수 없습니다."
        
        context_parts = []
        
        for info in collected_info:
            content = info.get("content", {})
            context_parts.append(str(content))
        
        return "\n\n".join(context_parts)
    
    def _extract_sources(self, state: AgentState) -> List[Dict[str, Any]]:
        """출처 추출"""
        sources = []
        
        # TODO: collected_info에서 출처 정보 추출
        
        return sources
    
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
        # 병렬 실행 가능한 시나리오:
        # 1. 계약서 구조 파악 + 하이브리드 검색
        # 2. 여러 조 번호 동시 조회
        # 3. 표준계약서 + 사용자 계약서 동시 조회
        
        next_tool = state.get("next_tool")
        if not next_tool:
            return False
        
        tool_name = next_tool.get("tool")
        tool_history = state.get("tool_history", [])
        
        # 시나리오 1: 첫 번째 툴 실행이고 하이브리드 검색인 경우
        # → 계약서 구조 파악과 병렬 실행 가능
        if len(tool_history) == 0 and tool_name == "hybrid_search":
            return True
        
        # 시나리오 2: article_index_tool이고 여러 조 번호가 있는 경우
        if tool_name == "article_index_tool":
            args = next_tool.get("args", {})
            article_numbers = args.get("article_numbers", [])
            if len(article_numbers) > 1:
                return True
        
        return False
    
    def execute_parallel_tools(self, state: AgentState) -> AgentState:
        """
        병렬 툴 실행
        
        Args:
            state: 현재 상태
            
        Returns:
            업데이트된 상태
        """
        next_tool = state.get("next_tool")
        if not next_tool:
            return state
        
        tool_name = next_tool.get("tool")
        args = next_tool.get("args", {})
        contract_id = state["contract_id"]
        
        logger.info(f"[execute_parallel_tools] 병렬 실행 시작: {tool_name}")
        
        # 병렬 실행할 툴 목록 구성
        parallel_tasks = []
        
        # 시나리오 1: 하이브리드 검색 + 계약서 구조 파악
        if tool_name == "hybrid_search" and len(state.get("tool_history", [])) == 0:
            parallel_tasks = [
                ("get_contract_structure", {}),
                (tool_name, args)
            ]
        
        # 시나리오 2: 여러 조 번호 동시 조회
        elif tool_name == "article_index_tool":
            article_numbers = args.get("article_numbers", [])
            if len(article_numbers) > 1:
                # 각 조 번호별로 개별 태스크 생성
                for article_no in article_numbers:
                    parallel_tasks.append((
                        tool_name,
                        {"article_numbers": [article_no]}
                    ))
            else:
                # 병렬 실행 불가능, 일반 실행으로 폴백
                return self.execute_tools(state)
        else:
            # 병렬 실행 불가능, 일반 실행으로 폴백
            return self.execute_tools(state)
        
        # ThreadPoolExecutor로 병렬 실행
        results = []
        with ThreadPoolExecutor(max_workers=min(len(parallel_tasks), 4)) as executor:
            future_to_task = {}
            
            for task_tool_name, task_args in parallel_tasks:
                tool_args = {**task_args, "contract_id": contract_id}
                future = executor.submit(
                    self.runtime.execute_tool,
                    task_tool_name,
                    tool_args,
                    True  # retry_on_failure
                )
                future_to_task[future] = (task_tool_name, task_args)
            
            # 결과 수집
            for future in as_completed(future_to_task):
                task_tool_name, task_args = future_to_task[future]
                try:
                    result = future.result()
                    results.append((task_tool_name, task_args, result))
                    logger.info(f"[execute_parallel_tools] 완료: {task_tool_name}")
                except Exception as e:
                    logger.error(f"[execute_parallel_tools] 실패: {task_tool_name}, {e}")
        
        # 결과를 상태에 반영
        for task_tool_name, task_args, result in results:
            # tool_history에 기록
            state["tool_history"].append({
                "tool": task_tool_name,
                "args": task_args,
                "result": result.dict() if hasattr(result, 'dict') else result,
                "timestamp": datetime.now().isoformat()
            })
            
            # 툴별 상태 업데이트
            if task_tool_name == "get_contract_structure" and result.success:
                state["contract_structure"] = result.data.dict() if hasattr(result.data, 'dict') else result.data
            
            # collected_info에 추가
            if result.success and result.data:
                info = CollectedInfo(
                    source=task_tool_name,
                    content=result.data.dict() if hasattr(result.data, 'dict') else result.data,
                    relevance=result.relevance_score or 0.8,
                    timestamp=datetime.now().isoformat(),
                    article_refs=[]
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
