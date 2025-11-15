"""
AgentPersistence - LangGraph 체크포인터 기반 상태 영속화

세션 복원 및 재개 기능을 제공합니다.
"""

import logging
from typing import Optional, Literal
from pathlib import Path

from langgraph.graph import StateGraph
from langgraph.graph.graph import CompiledGraph
from langgraph.checkpoint.memory import MemorySaver

logger = logging.getLogger(__name__)


class AgentPersistence:
    """
    에이전트 상태 영속화 관리
    
    LangGraph Checkpointer를 활용하여 에이전트 상태를 저장하고 복원합니다.
    """
    
    def __init__(
        self,
        persistence_mode: Literal["memory"] = "memory",
        db_path: Optional[str] = None
    ):
        """
        Args:
            persistence_mode: 영속화 모드
                - "memory": 메모리 기반 (현재 유일한 옵션)
            db_path: 사용되지 않음 (하위 호환성 유지)
        
        Note:
            LangGraph 0.2.45에서는 MemorySaver만 기본 제공됩니다.
            SqliteSaver는 별도 패키지(langgraph-checkpoint-sqlite)가 필요합니다.
        """
        self.persistence_mode = persistence_mode
        self.checkpointer = MemorySaver()
        logger.info("AgentPersistence 초기화: MemorySaver (메모리 기반)")
    
    def compile_workflow(self, workflow: StateGraph) -> CompiledGraph:
        """
        체크포인터와 함께 워크플로우 컴파일
        
        Args:
            workflow: LangGraph StateGraph
        
        Returns:
            컴파일된 워크플로우 (체크포인터 포함)
        """
        logger.debug(f"워크플로우 컴파일 (persistence_mode={self.persistence_mode})")
        return workflow.compile(checkpointer=self.checkpointer)
    
    def get_checkpointer(self):
        """
        체크포인터 인스턴스 반환
        
        Returns:
            MemorySaver 또는 SqliteSaver 인스턴스
        """
        return self.checkpointer
    
    def get_state(self, app: CompiledGraph, session_id: str, contract_id: str) -> Optional[dict]:
        """
        마지막 체크포인트 조회
        
        Args:
            app: 컴파일된 워크플로우
            session_id: 세션 ID
            contract_id: 계약서 ID
        
        Returns:
            체크포인트 상태 (없으면 None)
        """
        config = {
            "configurable": {
                "thread_id": session_id,
                "checkpoint_ns": contract_id
            }
        }
        
        try:
            state_snapshot = app.get_state(config)
            
            if state_snapshot and state_snapshot.values:
                logger.info(f"체크포인트 조회 성공: session={session_id}, contract={contract_id}")
                return state_snapshot.values
            
            logger.debug(f"체크포인트 없음: session={session_id}, contract={contract_id}")
            return None
        
        except Exception as e:
            logger.error(f"체크포인트 조회 실패: {e}")
            return None
    
    def update_state(
        self,
        app: CompiledGraph,
        session_id: str,
        contract_id: str,
        updates: dict
    ) -> bool:
        """
        상태 업데이트
        
        Args:
            app: 컴파일된 워크플로우
            session_id: 세션 ID
            contract_id: 계약서 ID
            updates: 업데이트할 상태
        
        Returns:
            성공 여부
        """
        config = {
            "configurable": {
                "thread_id": session_id,
                "checkpoint_ns": contract_id
            }
        }
        
        try:
            app.update_state(config, updates)
            logger.info(f"상태 업데이트 성공: session={session_id}, contract={contract_id}")
            return True
        
        except Exception as e:
            logger.error(f"상태 업데이트 실패: {e}")
            return False
    
    def close(self):
        """
        리소스 정리
        
        SQLite 연결 등을 정리합니다.
        """
        if self.persistence_mode == "sqlite" and hasattr(self.checkpointer, "close"):
            self.checkpointer.close()
            logger.info("AgentPersistence 리소스 정리 완료")
