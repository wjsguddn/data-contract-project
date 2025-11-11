"""
챗봇 에이전트 데이터 모델

Function Calling 기반 챗봇의 요청/응답 구조 정의
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime


@dataclass
class ChatbotResponse:
    """챗봇 응답 모델"""
    success: bool
    message: str
    sources: List[Dict[str, Any]] = field(default_factory=list)
    session_id: str = ""
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "success": self.success,
            "message": self.message,
            "sources": self.sources,
            "session_id": self.session_id,
            "error": self.error
        }


@dataclass
class ToolResult:
    """도구 실행 결과 모델"""
    success: bool
    tool_name: str
    data: Any
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "success": self.success,
            "tool_name": self.tool_name,
            "data": self.data,
            "error": self.error,
            "metadata": self.metadata
        }


@dataclass
class ValidationResult:
    """검증 결과 모델"""
    is_valid: bool
    reason: Optional[str] = None
    confidence: float = 1.0
    
    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "is_valid": self.is_valid,
            "reason": self.reason,
            "confidence": self.confidence
        }


@dataclass
class ToolPlan:
    """도구 실행 계획 모델"""
    intent: str  # 질문 의도 (조회, 비교, 검색 등)
    topics: List[Dict[str, Any]] = field(default_factory=list)
    # topics 구조:
    # [
    #   {
    #     "topic_name": "주제 이름",
    #     "tool": "도구 이름",
    #     "purpose": "사용 목적",
    #     "args": {...}
    #   }
    # ]
    
    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "intent": self.intent,
            "topics": self.topics
        }
