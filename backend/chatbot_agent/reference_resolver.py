"""
ReferenceResolver - 조항 간 참조 해결기

계약서 내부의 조항 참조를 자동으로 탐지하고 해결합니다.
"""

import logging
import re
from typing import Dict, Any, List
from backend.chatbot_agent.models import ToolResult
from backend.chatbot_agent.tools import ToolRegistry

logger = logging.getLogger("uvicorn.error")


class ReferenceResolver:
    """
    조항 간 참조 해결기
    
    계약서 내부의 조항 참조를 자동으로 탐지하고 해결합니다.
    """
    
    def __init__(self, tool_registry: ToolRegistry):
        """
        Args:
            tool_registry: 도구 레지스트리
        """
        self.tool_registry = tool_registry
        
        # 내부 참조 패턴
        self.internal_reference_patterns = [
            r"제(\d+)조",           # 제5조
            r"별지\s*(\d+)",        # 별지1, 별지 2
            r"전\s*항",             # 전 항
            r"다음\s*항",           # 다음 항
            r"제(\d+)항",           # 제1항
            r"제(\d+)호"            # 제1호
        ]
        
        # 외부 참조 패턴 (제외)
        self.external_reference_patterns = [
            r"[\w\s]+법\s+제\d+조",      # OO법 제N조
            r"[\w\s]+법\s+시행령",       # OO법 시행령
            r"[\w\s]+법\s+시행규칙"      # OO법 시행규칙
        ]
        
        logger.info("ReferenceResolver 초기화")
    
    def resolve_references(
        self,
        contract_id: str,
        tool_results: List[ToolResult],
        user_message: str,
        max_depth: int = 2
    ) -> List[ToolResult]:
        """
        도구 결과에서 참조를 탐지하고 해결
        
        Args:
            contract_id: 계약서 ID
            tool_results: 1차 도구 실행 결과
            user_message: 사용자 질문
            max_depth: 최대 추적 깊이 (기본 2)
            
        Returns:
            추가 참조 조항을 포함한 도구 결과 목록
            
        흐름:
        1. 도구 결과에서 텍스트 추출
        2. 내부 참조 패턴 탐지
        3. 외부 참조 패턴 제외
        4. LLM에게 참조 필요성 판단 요청 (현재는 생략, 모든 참조 추적)
        5. 필요한 참조만 추가 도구 호출
        6. 최대 깊이까지 재귀적으로 반복
        """
        try:
            if max_depth <= 0:
                logger.info("최대 깊이 도달, 참조 해결 중단")
                return []
            
            # 도구 결과에서 텍스트 추출
            all_text = self._extract_text_from_results(tool_results)
            
            if not all_text:
                logger.info("참조 해결: 텍스트 없음")
                return []
            
            # 내부 참조 탐지
            references = self.detect_internal_references(all_text)
            
            if not references:
                logger.info("참조 해결: 내부 참조 없음")
                return []
            
            logger.info(f"참조 탐지: {len(references)}개")
            
            # 외부 참조 제외
            filtered_references = [
                ref for ref in references
                if not self.is_external_reference(all_text, ref)
            ]
            
            if not filtered_references:
                logger.info("참조 해결: 외부 참조만 존재")
                return []
            
            logger.info(f"내부 참조: {len(filtered_references)}개")
            
            # 추가 도구 호출
            additional_results = []
            
            for ref in filtered_references:
                if ref["type"] == "article":
                    # 조 번호로 조회
                    tool = self.tool_registry.get_tool("get_article_by_index")
                    result = tool.execute(
                        contract_id=contract_id,
                        article_numbers=[ref["number"]]
                    )
                    
                    if result.success:
                        additional_results.append(result)
                        logger.info(f"참조 해결: 제{ref['number']}조 추가")
                
                elif ref["type"] == "exhibit":
                    # 별지 번호로 조회
                    tool = self.tool_registry.get_tool("get_article_by_index")
                    result = tool.execute(
                        contract_id=contract_id,
                        exhibit_numbers=[ref["number"]]
                    )
                    
                    if result.success:
                        additional_results.append(result)
                        logger.info(f"참조 해결: 별지{ref['number']} 추가")
            
            # 재귀적 참조 해결 (최대 깊이 제한)
            if additional_results and max_depth > 1:
                nested_results = self.resolve_references(
                    contract_id=contract_id,
                    tool_results=additional_results,
                    user_message=user_message,
                    max_depth=max_depth - 1
                )
                additional_results.extend(nested_results)
            
            return additional_results
        
        except Exception as e:
            logger.error(f"참조 해결 실패: {e}")
            return []
    
    def detect_internal_references(
        self,
        text: str
    ) -> List[Dict[str, Any]]:
        """
        텍스트에서 내부 참조 탐지
        
        Args:
            text: 검색할 텍스트
            
        Returns:
            [
                {"type": "article", "number": 5},
                {"type": "exhibit", "number": 1}
            ]
        """
        references = []
        
        # 조 번호 패턴
        article_pattern = r"제(\d+)조"
        for match in re.finditer(article_pattern, text):
            article_no = int(match.group(1))
            references.append({
                "type": "article",
                "number": article_no
            })
        
        # 별지 번호 패턴
        exhibit_pattern = r"별지\s*(\d+)"
        for match in re.finditer(exhibit_pattern, text):
            exhibit_no = int(match.group(1))
            references.append({
                "type": "exhibit",
                "number": exhibit_no
            })
        
        # 중복 제거
        unique_refs = []
        seen = set()
        
        for ref in references:
            key = (ref["type"], ref["number"])
            if key not in seen:
                seen.add(key)
                unique_refs.append(ref)
        
        return unique_refs
    
    def is_external_reference(
        self,
        text: str,
        reference: Dict[str, Any]
    ) -> bool:
        """
        외부 법령 참조인지 판단
        
        Args:
            text: 전체 텍스트
            reference: 참조 정보
            
        Returns:
            외부 참조 여부
            
        예: "개인정보보호법 제2조" → True
        예: "제2조" → False
        """
        # 외부 참조 패턴 검사
        for pattern in self.external_reference_patterns:
            if re.search(pattern, text):
                return True
        
        return False
    
    def _extract_text_from_results(
        self,
        tool_results: List[ToolResult]
    ) -> str:
        """
        도구 결과에서 텍스트 추출
        
        Args:
            tool_results: 도구 실행 결과 리스트
            
        Returns:
            추출된 텍스트 (결합)
        """
        texts = []
        
        for result in tool_results:
            if not result.success or not result.data:
                continue
            
            if isinstance(result.data, dict):
                # HybridSearchTool 결과
                for topic_results in result.data.values():
                    if isinstance(topic_results, list):
                        for item in topic_results:
                            if isinstance(item, dict):
                                texts.append(item.get("chunk_text", ""))
                
                # ArticleIndexTool, ArticleTitleTool 결과
                matched_articles = result.data.get("matched_articles", [])
                for article in matched_articles:
                    if isinstance(article, dict):
                        texts.append(article.get("title", ""))
                        content = article.get("content", [])
                        if isinstance(content, list):
                            texts.extend(content)
        
        return "\n".join(texts)
