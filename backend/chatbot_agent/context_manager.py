"""
ContextManager - 대화 컨텍스트 관리자

대화 히스토리를 관리하고 토큰 제한을 처리합니다.
"""

import logging
from typing import List, Dict, Any
from datetime import datetime
from backend.shared.database import SessionLocal, ChatbotSession

logger = logging.getLogger("uvicorn.error")


class ContextManager:
    """
    대화 컨텍스트 관리자
    
    대화 히스토리를 관리하고 토큰 제한을 처리합니다.
    """
    
    def __init__(self, max_tokens: int = 4000):
        """
        Args:
            max_tokens: 최대 토큰 수 (기본 4000)
        """
        self.max_tokens = max_tokens
        logger.info(f"ContextManager 초기화 (max_tokens={max_tokens})")
    
    def load_history(
        self,
        contract_id: str,
        session_id: str
    ) -> List[Dict[str, str]]:
        """
        DB에서 대화 히스토리 로드
        
        Args:
            contract_id: 계약서 ID
            session_id: 세션 ID
            
        Returns:
            대화 히스토리 리스트
            [
                {"role": "user", "content": "..."},
                {"role": "assistant", "content": "..."},
                ...
            ]
        """
        try:
            db = SessionLocal()
            
            # 세션 ID와 계약서 ID로 대화 히스토리 조회
            sessions = db.query(ChatbotSession).filter(
                ChatbotSession.session_id == session_id,
                ChatbotSession.contract_id == contract_id
            ).order_by(ChatbotSession.created_at.asc()).all()
            
            history = []
            for session in sessions:
                history.append({
                    "role": session.role,
                    "content": session.content
                })
            
            logger.info(f"대화 히스토리 로드: {len(history)}개 메시지")
            
            # 토큰 제한 초과 시 축소
            if len(history) > 20:  # 간단한 휴리스틱
                history = self.truncate_history(history)
            
            return history
        
        except Exception as e:
            logger.error(f"대화 히스토리 로드 실패: {e}")
            return []
        
        finally:
            db.close()
    
    def save_message(
        self,
        contract_id: str,
        session_id: str,
        role: str,
        content: str,
        tool_calls: Dict[str, Any] = None
    ):
        """
        메시지를 DB에 저장
        
        Args:
            contract_id: 계약서 ID
            session_id: 세션 ID
            role: 역할 ('user' | 'assistant' | 'system')
            content: 메시지 내용
            tool_calls: Function Calling 정보 (선택)
        """
        try:
            db = SessionLocal()
            
            session = ChatbotSession(
                session_id=session_id,
                contract_id=contract_id,
                role=role,
                content=content,
                tool_calls=tool_calls
            )
            
            db.add(session)
            db.commit()
            
            logger.info(f"메시지 저장: {role}, {len(content)}자")
        
        except Exception as e:
            logger.error(f"메시지 저장 실패: {e}")
        
        finally:
            db.close()
    
    def truncate_history(
        self,
        history: List[Dict[str, str]]
    ) -> List[Dict[str, str]]:
        """
        토큰 제한 초과 시 오래된 대화 제거
        
        전략:
        - 최근 10개 메시지 유지
        - 시스템 메시지는 항상 유지
        
        Args:
            history: 대화 히스토리
            
        Returns:
            축소된 대화 히스토리
        """
        # 시스템 메시지 분리
        system_messages = [msg for msg in history if msg.get("role") == "system"]
        other_messages = [msg for msg in history if msg.get("role") != "system"]
        
        # 최근 10개 메시지만 유지
        if len(other_messages) > 10:
            other_messages = other_messages[-10:]
            logger.info(f"대화 히스토리 축소: {len(history)} → {len(system_messages) + len(other_messages)}개")
        
        # 시스템 메시지 + 최근 메시지
        truncated = system_messages + other_messages
        
        return truncated
    
    def create_session_id(self, contract_id: str) -> str:
        """
        새 세션 ID 생성
        
        Args:
            contract_id: 계약서 ID
            
        Returns:
            세션 ID
        """
        import uuid
        session_id = f"{contract_id}_{uuid.uuid4().hex[:8]}"
        logger.info(f"새 세션 생성: {session_id}")
        return session_id
