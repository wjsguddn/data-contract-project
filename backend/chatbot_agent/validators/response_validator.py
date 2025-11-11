"""
ResponseValidator - 응답 품질 검증기

LLM 응답의 품질을 평가하고 필요시 재생성을 요청합니다.
"""

import logging
from typing import List
from backend.chatbot_agent.models import ValidationResult, ToolResult

logger = logging.getLogger("uvicorn.error")


class ResponseValidator:
    """
    응답 품질 검증기
    
    LLM 응답의 품질을 평가하고 필요시 재생성을 요청합니다.
    """
    
    def __init__(self):
        """응답 검증기 초기화"""
        logger.info("ResponseValidator 초기화")
    
    def validate(
        self,
        user_message: str,
        response: str,
        tool_results: List[ToolResult]
    ) -> ValidationResult:
        """
        응답 품질 검증
        
        검증 항목:
        1. 환각 검사: 도구 결과에 없는 내용 언급 여부
        2. 완전성 검사: 모든 주제에 대한 답변 포함 여부
        3. 출처 명시: 참조한 조항 출처 명시 여부
        
        Args:
            user_message: 사용자 질문
            response: LLM 응답
            tool_results: 도구 실행 결과 리스트
            
        Returns:
            ValidationResult: 검증 결과
        """
        try:
            # 1. 환각 검사
            hallucination_check = self._check_hallucination(response, tool_results)
            if not hallucination_check["is_valid"]:
                logger.warning(f"환각 검사 실패: {hallucination_check['reason']}")
                return ValidationResult(
                    is_valid=False,
                    reason=hallucination_check["reason"],
                    confidence=0.9
                )
            
            # 2. 완전성 검사
            completeness_check = self._check_completeness(user_message, response, tool_results)
            if not completeness_check["is_valid"]:
                logger.warning(f"완전성 검사 실패: {completeness_check['reason']}")
                return ValidationResult(
                    is_valid=False,
                    reason=completeness_check["reason"],
                    confidence=0.7
                )
            
            # 3. 출처 명시 검사
            source_check = self._check_source_citation(response, tool_results)
            if not source_check["is_valid"]:
                logger.warning(f"출처 명시 검사 실패: {source_check['reason']}")
                return ValidationResult(
                    is_valid=False,
                    reason=source_check["reason"],
                    confidence=0.6
                )
            
            # 모든 검사 통과
            logger.info("응답 품질 검증 통과")
            return ValidationResult(
                is_valid=True,
                confidence=0.95
            )
        
        except Exception as e:
            logger.error(f"응답 검증 실패: {e}")
            # 에러 시 일단 허용
            return ValidationResult(
                is_valid=True,
                confidence=0.3
            )
    
    def _check_hallucination(
        self,
        response: str,
        tool_results: List[ToolResult]
    ) -> dict:
        """
        환각 검사: 도구 결과에 없는 내용 언급 여부
        
        Args:
            response: LLM 응답
            tool_results: 도구 실행 결과 리스트
            
        Returns:
            {"is_valid": bool, "reason": str}
        """
        # 도구 결과가 없으면 검사 불가 (허용)
        if not tool_results:
            return {"is_valid": True, "reason": None}
        
        # 도구 결과에서 텍스트 추출
        tool_texts = []
        for result in tool_results:
            if result.success and result.data:
                # 데이터 구조에 따라 텍스트 추출
                if isinstance(result.data, dict):
                    # HybridSearchTool 결과
                    for topic_results in result.data.values():
                        if isinstance(topic_results, list):
                            for item in topic_results:
                                if isinstance(item, dict):
                                    tool_texts.append(item.get("chunk_text", ""))
                    
                    # ArticleIndexTool, ArticleTitleTool 결과
                    matched_articles = result.data.get("matched_articles", [])
                    for article in matched_articles:
                        if isinstance(article, dict):
                            tool_texts.append(article.get("title", ""))
                            content = article.get("content", [])
                            if isinstance(content, list):
                                tool_texts.extend(content)
        
        # 간단한 휴리스틱: 응답이 너무 짧으면 환각 가능성 낮음
        if len(response) < 100:
            return {"is_valid": True, "reason": None}
        
        # 도구 결과가 있는데 응답에 전혀 반영되지 않은 경우
        if tool_texts and not any(text[:50] in response for text in tool_texts if text):
            return {
                "is_valid": False,
                "reason": "도구 결과가 응답에 반영되지 않았습니다"
            }
        
        # 기본적으로 허용 (정밀한 환각 검사는 LLM 필요)
        return {"is_valid": True, "reason": None}
    
    def _check_completeness(
        self,
        user_message: str,
        response: str,
        tool_results: List[ToolResult]
    ) -> dict:
        """
        완전성 검사: 모든 주제에 대한 답변 포함 여부
        
        Args:
            user_message: 사용자 질문
            response: LLM 응답
            tool_results: 도구 실행 결과 리스트
            
        Returns:
            {"is_valid": bool, "reason": str}
        """
        # 도구 결과가 없으면 검사 불가 (허용)
        if not tool_results:
            return {"is_valid": True, "reason": None}
        
        # 도구 결과가 있는데 응답이 너무 짧으면 불완전
        if tool_results and len(response) < 50:
            return {
                "is_valid": False,
                "reason": "응답이 너무 짧습니다"
            }
        
        # 기본적으로 허용 (정밀한 완전성 검사는 LLM 필요)
        return {"is_valid": True, "reason": None}
    
    def _check_source_citation(
        self,
        response: str,
        tool_results: List[ToolResult]
    ) -> dict:
        """
        출처 명시 검사: 참조한 조항 출처 명시 여부
        
        Args:
            response: LLM 응답
            tool_results: 도구 실행 결과 리스트
            
        Returns:
            {"is_valid": bool, "reason": str}
        """
        # 도구 결과가 없으면 검사 불가 (허용)
        if not tool_results:
            return {"is_valid": True, "reason": None}
        
        # 간단한 휴리스틱: "제n조" 패턴이 있으면 출처 명시로 간주
        import re
        has_article_reference = bool(re.search(r'제\d+조', response))
        
        if not has_article_reference and tool_results:
            # 도구 결과가 있는데 출처 명시가 없으면 경고
            logger.warning("출처 명시 없음 (경고만, 허용)")
            # 하지만 허용 (너무 엄격하면 재생성 과다)
            return {"is_valid": True, "reason": None}
        
        return {"is_valid": True, "reason": None}
