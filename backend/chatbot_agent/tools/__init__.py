"""
도구 레지스트리 및 관리

Function Calling 도구 등록, 조회, 실행 관리
"""

import logging
import time
from typing import Dict, List, Any
from backend.chatbot_agent.tools.base import BaseTool
from backend.chatbot_agent.models import ToolResult

logger = logging.getLogger("uvicorn.error")


class ToolRegistry:
    """
    도구 레지스트리
    
    책임:
    - 도구 등록 및 조회
    - 도구 스키마 생성 (Function Calling용)
    - 도구 실행 및 에러 처리
    """
    
    def __init__(self):
        """도구 레지스트리 초기화"""
        self.tools: Dict[str, BaseTool] = {}
        logger.info("ToolRegistry 초기화")
    
    def register(self, tool: BaseTool):
        """
        도구 등록
        
        Args:
            tool: 등록할 도구 인스턴스
        """
        tool_name = tool.name
        if tool_name in self.tools:
            logger.warning(f"도구 '{tool_name}' 이미 등록됨 - 덮어쓰기")
        
        self.tools[tool_name] = tool
        logger.info(f"도구 등록: {tool_name}")
    
    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """
        Function Calling용 도구 스키마 반환
        
        Returns:
            도구 스키마 리스트
        """
        schemas = []
        for tool in self.tools.values():
            try:
                schema = tool.get_schema()
                schemas.append(schema)
            except Exception as e:
                logger.error(f"도구 스키마 생성 실패: {tool.name}, {e}")
        
        logger.debug(f"도구 스키마 생성 완료: {len(schemas)}개")
        return schemas
    
    def execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        contract_id: str,
        max_retries: int = 3
    ) -> ToolResult:
        """
        도구 실행 및 결과 검증 (재시도 로직 포함)
        
        Args:
            tool_name: 도구 이름
            arguments: 도구 파라미터
            contract_id: 계약서 ID
            max_retries: 최대 재시도 횟수 (기본 3회)
            
        Returns:
            ToolResult: 실행 결과
        """
        # 도구 존재 확인
        if tool_name not in self.tools:
            error_msg = f"도구를 찾을 수 없습니다: {tool_name}"
            logger.error(error_msg)
            return ToolResult(
                success=False,
                tool_name=tool_name,
                data=None,
                error=error_msg
            )
        
        tool = self.tools[tool_name]
        
        # 재시도 로직 (지수 백오프)
        for attempt in range(max_retries):
            try:
                logger.info(f"도구 실행: {tool_name} (시도 {attempt + 1}/{max_retries})")
                
                # 도구 실행
                result = tool.execute(contract_id=contract_id, **arguments)
                
                # 결과 검증
                if tool.validate_result(result):
                    logger.info(f"도구 실행 성공: {tool_name}")
                    return result
                else:
                    logger.warning(f"도구 결과 검증 실패: {tool_name}")
                    if attempt < max_retries - 1:
                        # 재시도 대기 (지수 백오프: 1초, 2초, 4초)
                        wait_time = 2 ** attempt
                        logger.info(f"{wait_time}초 후 재시도...")
                        time.sleep(wait_time)
                    else:
                        # 최종 실패
                        return result
            
            except Exception as e:
                logger.error(f"도구 실행 오류: {tool_name}, {e}")
                
                if attempt < max_retries - 1:
                    # 재시도 대기
                    wait_time = 2 ** attempt
                    logger.info(f"{wait_time}초 후 재시도...")
                    time.sleep(wait_time)
                else:
                    # 최종 실패
                    return ToolResult(
                        success=False,
                        tool_name=tool_name,
                        data=None,
                        error=str(e)
                    )
        
        # 모든 재시도 실패
        return ToolResult(
            success=False,
            tool_name=tool_name,
            data=None,
            error=f"최대 재시도 횟수 초과: {max_retries}회"
        )
    
    def get_tool(self, tool_name: str) -> BaseTool:
        """
        도구 인스턴스 조회
        
        Args:
            tool_name: 도구 이름
            
        Returns:
            BaseTool: 도구 인스턴스
            
        Raises:
            KeyError: 도구가 존재하지 않는 경우
        """
        if tool_name not in self.tools:
            raise KeyError(f"도구를 찾을 수 없습니다: {tool_name}")
        return self.tools[tool_name]
    
    def list_tools(self) -> List[str]:
        """
        등록된 도구 목록 반환
        
        Returns:
            도구 이름 리스트
        """
        return list(self.tools.keys())
