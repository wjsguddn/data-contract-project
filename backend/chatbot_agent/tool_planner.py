"""
ToolPlanner - 도구 계획 수립기

사용자 질문을 분석하여 필요한 도구와 실행 순서를 결정합니다.
"""

import logging
import json
from typing import List, Dict, Any
from openai import AzureOpenAI
from backend.chatbot_agent.models import ToolPlan
from backend.chatbot_agent.tools import ToolRegistry

logger = logging.getLogger("uvicorn.error")


class ToolPlanner:
    """
    도구 계획 수립기
    
    사용자 질문을 분석하여 필요한 도구와 실행 순서를 결정합니다.
    """
    
    def __init__(self, azure_client: AzureOpenAI, tool_registry: ToolRegistry):
        """
        Args:
            azure_client: Azure OpenAI 클라이언트
            tool_registry: 도구 레지스트리
        """
        self.client = azure_client
        self.tool_registry = tool_registry
        logger.info("ToolPlanner 초기화")
    
    def plan(
        self,
        user_message: str,
        conversation_history: List[Dict[str, str]]
    ) -> ToolPlan:
        """
        도구 실행 계획 수립
        
        Args:
            user_message: 사용자 질문
            conversation_history: 대화 히스토리
            
        Returns:
            ToolPlan: 도구 실행 계획
            
        흐름:
        1. 질문 의도 분석 (비교, 조회, 검색 등)
        2. 필요한 주제 식별
        3. 각 주제별로 적절한 도구 선택
        4. 도구 실행 순서 결정
        5. 각 도구의 목적 명시
        """
        try:
            # 도구 목록 생성
            available_tools = self.tool_registry.list_tools()
            tools_description = self._build_tools_description()
            
            # 프롬프트 생성
            prompt = f"""사용자 질문을 분석하여 필요한 도구와 실행 순서를 결정하세요.

사용자 질문: {user_message}

사용 가능한 도구:
{tools_description}

분석 항목:
1. 질문 의도 (조회, 비교, 검색 등)
2. 언급된 주제 목록
3. 각 주제별 적절한 도구
4. 도구 실행 순서

답변 형식 (JSON):
{{
  "intent": "조회|비교|검색",
  "topics": [
    {{
      "topic_name": "주제 이름",
      "tool": "도구 이름",
      "purpose": "이 도구를 사용하는 이유",
      "args": {{...}}
    }}
  ]
}}

예시:
- "제5조 내용이 뭐야?" → get_article_by_index (조 번호 명시)
  {{
    "topic_name": "제5조",
    "tool": "get_article_by_index",
    "purpose": "사용자가 명시한 조 번호 조회",
    "args": {{"article_numbers": [5]}}
  }}

- "데이터 제공 조항 찾아줘" → get_article_by_title (제목 명시)
  {{
    "topic_name": "데이터 제공",
    "tool": "get_article_by_title",
    "purpose": "제목으로 조항 검색",
    "args": {{"title_keywords": ["데이터 제공"]}}
  }}

- "데이터 보안에 대한 내용 있어?" → hybrid_search (내용 기반 검색)
  {{
    "topic_name": "데이터 보안",
    "tool": "hybrid_search",
    "purpose": "내용 기반으로 관련 조항 검색",
    "args": {{
      "topics": [
        {{
          "topic_name": "데이터 보안",
          "queries": ["데이터 보안", "보안 조치", "정보 보호"]
        }}
      ]
    }}
  }}

중요: hybrid_search 도구의 args는 반드시 위 형식을 따라야 합니다.
"""

            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "당신은 계약서 질의응답 시스템의 도구 계획 수립 전문가입니다."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0,
                max_tokens=500
            )
            
            # JSON 파싱
            content = response.choices[0].message.content.strip()
            
            # JSON 블록 추출 (```json ... ``` 형식 처리)
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            plan_json = json.loads(content)
            
            logger.info(f"도구 계획 수립 완료: {plan_json.get('intent')}, {len(plan_json.get('topics', []))}개 주제")
            
            return ToolPlan(
                intent=plan_json.get("intent", "search"),
                topics=plan_json.get("topics", [])
            )
            
        except Exception as e:
            logger.error(f"Tool planning 실패: {e}")
            import traceback
            logger.error(traceback.format_exc())
            
            # 폴백: 기본 계획 반환 (하이브리드 검색)
            logger.warning("폴백: 기본 하이브리드 검색 계획 사용")
            return ToolPlan(
                intent="search",
                topics=[{
                    "topic_name": "general",
                    "tool": "hybrid_search",
                    "purpose": "일반 검색",
                    "args": {
                        "topics": [{
                            "topic_name": "general",
                            "queries": [user_message]
                        }]
                    }
                }]
            )
    
    def _build_tools_description(self) -> str:
        """
        도구 목록 설명 생성
        
        Returns:
            도구 설명 문자열
        """
        descriptions = []
        
        for tool_name in self.tool_registry.list_tools():
            try:
                tool = self.tool_registry.get_tool(tool_name)
                descriptions.append(f"- {tool_name}: {tool.description}...")
            except Exception as e:
                logger.error(f"도구 설명 생성 실패: {tool_name}, {e}")
        
        return "\n".join(descriptions)
