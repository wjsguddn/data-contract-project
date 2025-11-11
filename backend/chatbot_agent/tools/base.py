"""
BaseTool 추상 클래스

모든 챗봇 도구의 기본 인터페이스 정의
"""

from abc import ABC, abstractmethod
from typing import Dict, Any
from backend.chatbot_agent.models import ToolResult


class BaseTool(ABC):
    """
    도구 기본 클래스
    
    모든 도구는 이 클래스를 상속받아 구현합니다.
    Function Calling을 위한 JSON 스키마와 실행 로직을 제공합니다.
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """도구 이름 (Function Calling에서 사용)"""
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """
        도구 설명 (LLM이 이해할 수 있도록)
        
        사용 시기, 입력 형식, 출력 형식을 명확히 기술
        """
        pass
    
    @abstractmethod
    def get_schema(self) -> Dict[str, Any]:
        """
        Function Calling용 JSON 스키마
        
        Returns:
            {
                "name": str,
                "description": str,
                "parameters": {
                    "type": "object",
                    "properties": {...},
                    "required": [...]
                }
            }
        """
        pass
    
    @abstractmethod
    def execute(
        self,
        contract_id: str,
        **kwargs
    ) -> ToolResult:
        """
        도구 실행
        
        Args:
            contract_id: 계약서 ID
            **kwargs: 도구별 파라미터
            
        Returns:
            ToolResult: 실행 결과
        """
        pass
    
    def validate_result(self, result: ToolResult) -> bool:
        """
        결과 유효성 검증 (기본 구현 제공)
        
        Args:
            result: 도구 실행 결과
            
        Returns:
            bool: 유효성 여부
        """
        return result.success and result.data is not None
