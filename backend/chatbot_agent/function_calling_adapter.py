"""
FunctionCallingAdapter - OpenAI Function Calling을 LangGraph에 통합

OpenAI의 공식 function calling 기능을 사용하여 툴 선택 및 실행을 처리합니다.
"""

import logging
import json
from typing import Dict, Any, List, Optional
from openai import OpenAI

logger = logging.getLogger("uvicorn.error")


class FunctionCallingAdapter:
    """
    OpenAI Function Calling 어댑터
    
    역할:
    1. 툴 스키마를 OpenAI function 형식으로 변환
    2. LLM 호출 시 tools 파라미터 전달
    3. tool_calls 응답을 파싱하여 LangGraph 상태에 맞게 변환
    4. 여러 툴 동시 선택 지원
    """
    
    def __init__(
        self,
        openai_client: OpenAI,
        tool_registry: 'ToolRegistry'
    ):
        """
        Args:
            openai_client: OpenAI 클라이언트
            tool_registry: 툴 레지스트리
        """
        self.client = openai_client
        self.tool_registry = tool_registry
        
        # 툴 스키마를 OpenAI function 형식으로 변환
        self.functions = self._build_function_schemas()
        
        # 시스템 프롬프트 (상세 가이드)
        self.system_prompt = self._build_system_prompt()
        
        logger.info(f"FunctionCallingAdapter 초기화: {len(self.functions)}개 함수")
    
    def _build_function_schemas(self) -> List[Dict[str, Any]]:
        """
        툴 레지스트리에서 OpenAI function 스키마 생성
        
        Returns:
            OpenAI function 스키마 리스트
        """
        functions = []
        
        for tool_name in self.tool_registry.list_tools():
            tool = self.tool_registry.get_tool(tool_name)
            
            # BaseTool의 get_schema()를 OpenAI function 형식으로 변환
            tool_schema = tool.get_schema()
            
            function_schema = {
                "type": "function",
                "function": {
                    "name": tool_schema["name"],
                    "description": self._get_short_description(tool),  # 짧은 설명만
                    "parameters": tool_schema["parameters"]
                }
            }
            
            functions.append(function_schema)
        
        return functions
    
    def _get_short_description(self, tool) -> str:
        """
        툴의 짧은 설명 추출 (첫 줄만)
        
        Args:
            tool: BaseTool 인스턴스
            
        Returns:
            짧은 설명 (1-2문장)
        """
        full_desc = tool.description.strip()
        
        # 첫 번째 줄만 추출
        lines = full_desc.split('\n')
        first_line = lines[0].strip()
        
        # 너무 길면 자르기
        if len(first_line) > 150:
            first_line = first_line[:147] + "..."
        
        return first_line
    
    def _build_system_prompt(self) -> str:
        """
        상세한 툴 사용 가이드를 포함한 시스템 프롬프트
        
        기존 tool_schemas의 가이드라인을 그대로 사용합니다.
        
        Returns:
            시스템 프롬프트
        """
        prompt = """당신은 계약서 질의응답 전문가입니다.

사용 가능한 도구와 사용 가이드:

1. **get_article_by_index**: 조 번호 또는 별지 번호로 해당 항목 내용 직접 조회
   사용 시기:
   - 사용자 계약서 미탐색 항목 중 질문과 연관된 정보가 있을 것으로 판단되는 항목들이 있다면 사용합니다.
   - 수집된 사용자 계약서의 내용에 특정 조나 별지에 대한 참조가 명시되어있고, 해당 참조의 내용이 필요하다고 판단되면 사용합니다.
   - 사용자 질문에서 조 번호나 별지 번호가 직접적으로 언급된 경우 사용합니다.
   - article_numbers와 exhibit_numbers를 모두 명시해도 좋고, 둘 중 하나만 명시해도 좋습니다.
   
   파라미터:
   - article_numbers: 조 번호 리스트 [번호, 번호, ...]
   - exhibit_numbers: 별지 번호 리스트 [번호, 번호, ...]

2. **get_article_by_title**: 조 제목 또는 별지 제목으로 해당 항목 내용 직접 조회
   사용 시기:
   - 사용자 질문에서 조의 제목이나 별지의 제목이 직접적으로 언급된 것으로 보이는 경우 사용합니다.
   - 수집된 정보에 사용자 계약서 구조가 있다면, 이 툴은 사용을 지양합니다.(get_article_by_index를 사용할 수 있기 때문에)
   
   파라미터:
   - titles: 제목 키워드 리스트 ['제목', '제목', ...]

3. **hybrid_search**: 쿼리 기반 하이브리드 검색
   사용 시기:
   - get_article_by_index 또는 get_article_by_title 툴을 통해서 직접 조회를 했음에도 원하는 정보를 얻지 못한 경우 사용합니다.
   - hybrid_search까지 사용하여 정보를 수집했음에도 원하는 정보를 얻지 못한 경우, 이전에 사용하지 않은 새로운 쿼리로 검색을 시도할 수 있습니다.
   
   파라미터:
   - topics: 검색 주제 리스트 [{'topic_name': '주제명', 'queries': ['검색쿼리', '검색쿼리']}, {...}]

4. **lookup_standard_contract**: 표준계약서 조문 조회 (참고용 템플릿)
   사용 시기:
   - 사용자가 계약서의 내용 검증이나 작성에 대한 질문을 한 경우 사용합니다.
   - 사용자 계약서의 조항 중에서 모범 템플릿 형식을 파악하고 싶은 조항의 번호와 해당 조항 관련 주제를 입력합니다.
   - 조항 번호를 특정할 수 없는 경우, 주제만 입력합니다.
   
   파라미터:
   - user_article_numbers: 조 번호 리스트 [번호, 번호, ...]
   - topic: 검색 주제 문자열

도구 선택 원칙:
- 조 번호 명시 → get_article_by_index
- 제목 언급 → get_article_by_title (단, 구조를 알면 get_article_by_index)
- 내용 기반 조회 필요 → hybrid_search
- 작성/검증 질문 → lookup_standard_contract

중요:
- 이미 실행한 도구는 같은 파라미터로 다시 호출하지 마세요
- 같은 도구를 다른 파라미터로는 호출 가능합니다
- 필요하다면 여러 도구를 동시에 선택할 수 있습니다
"""
        return prompt
    
    def call_with_functions(
        self,
        messages: List[Dict[str, str]],
        model: str = "gpt-4o",
        temperature: float = 0.3,
        tool_choice: str = "auto"
    ) -> Dict[str, Any]:
        """
        Function calling을 사용하여 LLM 호출
        
        Args:
            messages: 대화 메시지 리스트
            model: 모델 이름
            temperature: 온도
            tool_choice: "auto", "required", "none", 또는 특정 함수 지정
            
        Returns:
            {
                "has_tool_calls": bool,
                "tool_calls": List[{"id": str, "name": str, "args": dict}],
                "message": str,  # 텍스트 응답 (tool_calls 없을 때)
                "finish_reason": str
            }
        """
        try:
            # 시스템 프롬프트 추가 (첫 메시지가 system이 아니면)
            if not messages or messages[0].get("role") != "system":
                messages = [
                    {"role": "system", "content": self.system_prompt}
                ] + messages
            
            # 프롬프트 로깅
            logger.info("=" * 80)
            logger.info("[FunctionCalling] LLM 호출 프롬프트")
            logger.info("=" * 80)
            for idx, msg in enumerate(messages):
                role = msg.get("role", "")
                content = msg.get("content", "")
                logger.info(f"[Message {idx+1}] Role: {role}")
                if content:
                    logger.info(f"Content:\n{content}")
                if msg.get("tool_calls"):
                    logger.info(f"Tool Calls: {msg.get('tool_calls')}")
                logger.info("-" * 80)
            logger.info("=" * 80)
            
            # OpenAI API 호출
            response = self.client.chat.completions.create(
                model=model,
                messages=messages,
                tools=self.functions,
                tool_choice=tool_choice,
                temperature=temperature
            )
            
            choice = response.choices[0]
            message = choice.message
            
            # tool_calls 파싱
            if message.tool_calls:
                tool_calls = []
                for tc in message.tool_calls:
                    tool_calls.append({
                        "id": tc.id,
                        "name": tc.function.name,
                        "args": json.loads(tc.function.arguments)
                    })
                
                logger.info(
                    f"[FunctionCalling] {len(tool_calls)}개 함수 호출: "
                    f"{[tc['name'] for tc in tool_calls]}"
                )
                
                return {
                    "has_tool_calls": True,
                    "tool_calls": tool_calls,
                    "message": None,
                    "finish_reason": choice.finish_reason
                }
            else:
                # 텍스트 응답
                return {
                    "has_tool_calls": False,
                    "tool_calls": [],
                    "message": message.content,
                    "finish_reason": choice.finish_reason
                }
        
        except Exception as e:
            logger.error(f"[FunctionCalling] 오류: {e}")
            raise
    
    def format_tool_result_message(
        self,
        tool_call_id: str,
        tool_name: str,
        result: Any
    ) -> Dict[str, Any]:
        """
        툴 실행 결과를 OpenAI tool message 형식으로 변환
        
        Args:
            tool_call_id: tool_call의 ID
            tool_name: 툴 이름
            result: 툴 실행 결과 (ToolResult)
            
        Returns:
            OpenAI tool message
        """
        # ToolResult를 JSON 문자열로 변환
        if hasattr(result, 'dict'):
            content = json.dumps(result.dict(), ensure_ascii=False)
        else:
            content = json.dumps({"result": str(result)}, ensure_ascii=False)
        
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": content
        }
