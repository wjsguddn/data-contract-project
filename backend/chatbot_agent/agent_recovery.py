"""
AgentRecovery - 에이전트 복원 전략

체크포인트에서 에이전트 상태를 복원하고 재개합니다.
"""

import logging
from typing import Optional, Dict, Any

from langgraph.graph.graph import CompiledGraph

logger = logging.getLogger(__name__)


class AgentRecovery:
    """
    에이전트 복원 전략
    
    체크포인트에서 에이전트 상태를 복원하고 재개하는 기능을 제공합니다.
    """
    
    @staticmethod
    def recover_from_checkpoint(
        app: CompiledGraph,
        session_id: str,
        contract_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        마지막 체크포인트에서 복원
        
        Args:
            app: 컴파일된 워크플로우
            session_id: 세션 ID
            contract_id: 계약서 ID
        
        Returns:
            복원된 상태 (없으면 None)
        """
        config = {
            "configurable": {
                "thread_id": session_id,
                "checkpoint_ns": contract_id
            }
        }
        
        try:
            # 마지막 체크포인트 조회
            state_snapshot = app.get_state(config)
            
            if state_snapshot and state_snapshot.values:
                logger.info(
                    f"체크포인트 복원 성공: session={session_id}, "
                    f"iteration={state_snapshot.values.get('iteration_count', 0)}"
                )
                return state_snapshot.values
            
            logger.warning(f"복원할 체크포인트 없음: session={session_id}")
            return None
        
        except Exception as e:
            logger.error(f"체크포인트 복원 실패: {e}")
            return None
    
    @staticmethod
    def resume_from_checkpoint(
        app: CompiledGraph,
        session_id: str,
        contract_id: str,
        new_input: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        체크포인트에서 재개
        
        Args:
            app: 컴파일된 워크플로우
            session_id: 세션 ID
            contract_id: 계약서 ID
            new_input: 새로운 입력 (상태 업데이트용)
        
        Returns:
            최종 상태 (실패 시 None)
        """
        config = {
            "configurable": {
                "thread_id": session_id,
                "checkpoint_ns": contract_id
            }
        }
        
        try:
            # 새로운 입력이 있으면 상태 업데이트
            if new_input:
                app.update_state(config, new_input)
                logger.info(f"상태 업데이트 후 재개: session={session_id}")
            
            # 워크플로우 재개
            final_state = app.invoke(None, config=config)
            
            logger.info(
                f"체크포인트 재개 성공: session={session_id}, "
                f"iteration={final_state.get('iteration_count', 0)}"
            )
            
            return final_state
        
        except Exception as e:
            logger.error(f"체크포인트 재개 실패: {e}")
            return None
    
    @staticmethod
    def get_partial_result(
        recovered_state: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        부분 결과 추출
        
        에러 발생 시 복원된 상태에서 부분 결과를 추출합니다.
        
        Args:
            recovered_state: 복원된 상태
        
        Returns:
            부분 결과 (없으면 None)
        """
        if not recovered_state:
            return None
        
        # 수집된 정보가 있으면 부분 결과 생성
        collected_info = recovered_state.get("collected_info", [])
        tool_history = recovered_state.get("tool_history", [])
        
        if not collected_info and not tool_history:
            logger.warning("부분 결과 없음: 수집된 정보가 없습니다")
            return None
        
        # 부분 결과 구성
        partial_result = {
            "success": False,
            "message": "처리 중 오류가 발생했습니다. 부분 결과를 반환합니다.",
            "collected_info": collected_info,
            "tool_history": tool_history,
            "iteration_count": recovered_state.get("iteration_count", 0),
            "decision_log": recovered_state.get("decision_log", []),
            "sources": recovered_state.get("sources", [])
        }
        
        logger.info(
            f"부분 결과 생성: {len(collected_info)}개 정보, "
            f"{len(tool_history)}개 툴 실행"
        )
        
        return partial_result
