"""
SessionManager - 세션 관리 통합

기존 ChatbotSession 테이블과 LangGraph 체크포인트를 통합 관리합니다.
"""

import logging
import json
from typing import Dict, Any, Optional, List
from datetime import datetime
from sqlalchemy.orm import Session

from backend.shared.database import ChatbotSession, SessionLocal

logger = logging.getLogger(__name__)


class SessionManager:
    """
    세션 관리 통합
    
    LangGraph 체크포인트와 ChatbotSession DB를 통합하여 관리합니다.
    """
    
    def __init__(self, db_session: Optional[Session] = None):
        """
        Args:
            db_session: SQLAlchemy 세션 (None이면 자동 생성)
        """
        self.db = db_session or SessionLocal()
        self._auto_created = db_session is None
    
    def save_agent_state(
        self,
        session_id: str,
        contract_id: str,
        state: Dict[str, Any]
    ):
        """
        에이전트 상태를 DB에 저장
        
        LangGraph 체크포인트는 자동으로 저장되므로,
        여기서는 중요 정보만 ChatbotSession에 추가 저장합니다.
        
        Args:
            session_id: 세션 ID
            contract_id: 계약서 ID
            state: 에이전트 상태
        """
        try:
            # 중요 정보 추출
            iteration_count = state.get("iteration_count", 0)
            explored_articles = state.get("explored_articles", [])
            decision_log = state.get("decision_log", [])
            tool_history = state.get("tool_history", [])
            
            # 최근 정보만 저장 (DB 크기 최소화)
            recent_decision_log = decision_log[-5:] if len(decision_log) > 5 else decision_log
            recent_tool_history = tool_history[-10:] if len(tool_history) > 10 else tool_history
            
            # ChatbotSession에 저장
            session_entry = ChatbotSession(
                session_id=session_id,
                contract_id=contract_id,
                role="system",
                content=json.dumps({
                    "iteration_count": iteration_count,
                    "explored_articles": explored_articles,
                    "decision_log": recent_decision_log,
                    "timestamp": datetime.utcnow().isoformat()
                }, ensure_ascii=False),
                tool_calls=recent_tool_history
            )
            
            self.db.add(session_entry)
            self.db.commit()
            
            logger.info(
                f"에이전트 상태 저장 완료: session={session_id}, "
                f"iteration={iteration_count}, tools={len(tool_history)}"
            )
        
        except Exception as e:
            logger.error(f"에이전트 상태 저장 실패: {e}")
            self.db.rollback()
    
    def load_agent_state(
        self,
        session_id: str,
        contract_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        DB에서 에이전트 상태 로드
        
        Args:
            session_id: 세션 ID
            contract_id: 계약서 ID
        
        Returns:
            에이전트 상태 (없으면 None)
        """
        try:
            # 가장 최근 system 메시지 조회
            session_entry = self.db.query(ChatbotSession).filter(
                ChatbotSession.session_id == session_id,
                ChatbotSession.contract_id == contract_id,
                ChatbotSession.role == "system"
            ).order_by(ChatbotSession.created_at.desc()).first()
            
            if not session_entry:
                logger.debug(f"저장된 상태 없음: session={session_id}")
                return None
            
            # JSON 파싱
            state_data = json.loads(session_entry.content)
            
            logger.info(
                f"에이전트 상태 로드 완료: session={session_id}, "
                f"iteration={state_data.get('iteration_count', 0)}"
            )
            
            return {
                "iteration_count": state_data.get("iteration_count", 0),
                "explored_articles": state_data.get("explored_articles", []),
                "decision_log": state_data.get("decision_log", []),
                "tool_history": session_entry.tool_calls or [],
                "timestamp": state_data.get("timestamp")
            }
        
        except Exception as e:
            logger.error(f"에이전트 상태 로드 실패: {e}")
            return None
    
    def save_message(
        self,
        session_id: str,
        contract_id: str,
        role: str,
        content: str,
        tool_calls: Optional[List[Dict[str, Any]]] = None
    ):
        """
        대화 메시지 저장
        
        Args:
            session_id: 세션 ID
            contract_id: 계약서 ID
            role: 역할 ('user' | 'assistant' | 'system')
            content: 메시지 내용
            tool_calls: 툴 호출 정보
        """
        try:
            message_entry = ChatbotSession(
                session_id=session_id,
                contract_id=contract_id,
                role=role,
                content=content,
                tool_calls=tool_calls
            )
            
            self.db.add(message_entry)
            self.db.commit()
            
            logger.debug(f"메시지 저장 완료: session={session_id}, role={role}")
        
        except Exception as e:
            logger.error(f"메시지 저장 실패: {e}")
            self.db.rollback()
    
    def get_conversation_history(
        self,
        session_id: str,
        contract_id: str,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        대화 히스토리 조회
        
        Args:
            session_id: 세션 ID
            contract_id: 계약서 ID
            limit: 최대 메시지 개수
        
        Returns:
            대화 히스토리 리스트
        """
        try:
            messages = self.db.query(ChatbotSession).filter(
                ChatbotSession.session_id == session_id,
                ChatbotSession.contract_id == contract_id
            ).order_by(ChatbotSession.created_at.desc()).limit(limit).all()
            
            # 시간 순서대로 정렬 (최신이 마지막)
            messages = list(reversed(messages))
            
            history = []
            for msg in messages:
                history.append({
                    "role": msg.role,
                    "content": msg.content,
                    "tool_calls": msg.tool_calls,
                    "created_at": msg.created_at.isoformat()
                })
            
            logger.info(f"대화 히스토리 조회 완료: session={session_id}, count={len(history)}")
            return history
        
        except Exception as e:
            logger.error(f"대화 히스토리 조회 실패: {e}")
            return []
    
    def delete_session(
        self,
        session_id: str,
        contract_id: Optional[str] = None
    ):
        """
        세션 삭제
        
        Args:
            session_id: 세션 ID
            contract_id: 계약서 ID (None이면 모든 계약서)
        """
        try:
            query = self.db.query(ChatbotSession).filter(
                ChatbotSession.session_id == session_id
            )
            
            if contract_id:
                query = query.filter(ChatbotSession.contract_id == contract_id)
            
            deleted_count = query.delete()
            self.db.commit()
            
            logger.info(f"세션 삭제 완료: session={session_id}, count={deleted_count}")
        
        except Exception as e:
            logger.error(f"세션 삭제 실패: {e}")
            self.db.rollback()
    
    def close(self):
        """
        리소스 정리
        """
        if self._auto_created and self.db:
            self.db.close()
            logger.debug("SessionManager 리소스 정리 완료")
    
    def __enter__(self):
        """컨텍스트 매니저 진입"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """컨텍스트 매니저 종료"""
        self.close()
