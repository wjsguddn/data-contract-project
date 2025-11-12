"""
LightweightClassifier - 규칙 기반 툴 필요성 빠른 판단

LLM 호출 전에 간단한 패턴 매칭으로 툴 필요성을 빠르게 판단합니다.
확실한 경우만 판단하고, 불확실하면 LLM에 위임합니다.
"""

import re
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class LightweightClassifier:
    """
    규칙 기반 툴 필요성 분류기
    
    빠른 패턴 매칭으로 명확한 경우만 판단하고,
    불확실한 경우는 None을 반환하여 LLM에 위임합니다.
    """
    
    # 조 번호 패턴 (제1조, 제 1조, 제1조의2 등)
    ARTICLE_NUMBER_PATTERN = re.compile(r'제\s*(\d+)\s*조')
    
    # 별지 번호 패턴 (별지1, 별지 1, 별지1호 등)
    EXHIBIT_NUMBER_PATTERN = re.compile(r'별지\s*(\d+)')
    
    # 계약서 내용 관련 키워드
    CONTRACT_CONTENT_KEYWORDS = [
        '계약서', '조항', '내용', '규정', '명시', '기재',
        '포함', '있는지', '있나요', '어떻게', '무엇',
        '어디', '언제', '누가', '왜'
    ]
    
    # 일반 대화 키워드 (툴 불필요)
    GENERAL_CONVERSATION_KEYWORDS = [
        '안녕', '감사', '고마워', '미안', '죄송',
        '도와줘', '알려줘', '설명해줘'
    ]
    
    def __init__(self):
        """초기화"""
        logger.info("LightweightClassifier 초기화 완료")
    
    def classify(self, user_message: str) -> Optional[Dict[str, Any]]:
        """
        사용자 메시지를 분석하여 툴 필요성을 빠르게 판단
        
        Args:
            user_message: 사용자 메시지
            
        Returns:
            {
                "needs_tools": bool,
                "confidence": float,  # 0.0 ~ 1.0
                "reason": str,
                "suggested_tool": Optional[str]  # 추천 툴 (있는 경우)
            }
            또는 None (불확실한 경우 - LLM에 위임)
        """
        message_lower = user_message.lower().strip()
        
        # 1. 조 번호 명시 → 툴 필요 (높은 확신)
        article_matches = self.ARTICLE_NUMBER_PATTERN.findall(user_message)
        if article_matches:
            logger.info(f"조 번호 감지: {article_matches}")
            return {
                "needs_tools": True,
                "confidence": 0.95,
                "reason": f"조 번호가 명시됨: {', '.join([f'제{n}조' for n in article_matches])}",
                "suggested_tool": "article_index_tool"
            }
        
        # 2. 별지 번호 명시 → 툴 필요 (높은 확신)
        exhibit_matches = self.EXHIBIT_NUMBER_PATTERN.findall(user_message)
        if exhibit_matches:
            logger.info(f"별지 번호 감지: {exhibit_matches}")
            return {
                "needs_tools": True,
                "confidence": 0.95,
                "reason": f"별지 번호가 명시됨: {', '.join([f'별지{n}' for n in exhibit_matches])}",
                "suggested_tool": "article_index_tool"
            }
        
        # 3. 일반 대화 키워드만 있음 → 툴 불필요 (중간 확신)
        has_general_only = any(
            keyword in message_lower 
            for keyword in self.GENERAL_CONVERSATION_KEYWORDS
        )
        has_contract_keywords = any(
            keyword in message_lower 
            for keyword in self.CONTRACT_CONTENT_KEYWORDS
        )
        
        if has_general_only and not has_contract_keywords:
            logger.info("일반 대화 키워드만 감지")
            return {
                "needs_tools": False,
                "confidence": 0.7,
                "reason": "일반적인 인사 또는 대화로 판단됨",
                "suggested_tool": None
            }
        
        # 4. 계약서 내용 키워드 있음 → 툴 필요 (중간 확신)
        if has_contract_keywords:
            logger.info("계약서 내용 키워드 감지")
            return {
                "needs_tools": True,
                "confidence": 0.75,
                "reason": "계약서 내용 관련 질문으로 판단됨",
                "suggested_tool": None  # 구체적인 툴은 LLM이 결정
            }
        
        # 5. 불확실 → LLM에 위임
        logger.info("패턴 매칭 실패 - LLM에 위임")
        return None
    
    def extract_article_numbers(self, user_message: str) -> list[int]:
        """
        메시지에서 조 번호 추출
        
        Args:
            user_message: 사용자 메시지
            
        Returns:
            조 번호 리스트 (예: [1, 3, 5])
        """
        matches = self.ARTICLE_NUMBER_PATTERN.findall(user_message)
        return [int(n) for n in matches]
    
    def extract_exhibit_numbers(self, user_message: str) -> list[int]:
        """
        메시지에서 별지 번호 추출
        
        Args:
            user_message: 사용자 메시지
            
        Returns:
            별지 번호 리스트 (예: [1, 2])
        """
        matches = self.EXHIBIT_NUMBER_PATTERN.findall(user_message)
        return [int(n) for n in matches]
    
    def has_explicit_references(self, user_message: str) -> bool:
        """
        명시적인 참조(조 번호, 별지 번호)가 있는지 확인
        
        Args:
            user_message: 사용자 메시지
            
        Returns:
            명시적 참조 존재 여부
        """
        has_articles = bool(self.ARTICLE_NUMBER_PATTERN.search(user_message))
        has_exhibits = bool(self.EXHIBIT_NUMBER_PATTERN.search(user_message))
        return has_articles or has_exhibits
    
    def suggest_tool(self, user_message: str) -> Optional[tuple]:
        """
        규칙 기반 툴 제안
        
        Args:
            user_message: 사용자 메시지
            
        Returns:
            (tool_name, args, reasoning) 또는 None
        """
        # 조 번호 명시 → article_index_tool
        article_numbers = self.extract_article_numbers(user_message)
        if article_numbers:
            return (
                "get_article_by_index",
                {"article_numbers": article_numbers},
                f"조 번호가 명시됨: {article_numbers}"
            )
        
        # 별지 번호 명시 → article_index_tool
        exhibit_numbers = self.extract_exhibit_numbers(user_message)
        if exhibit_numbers:
            return (
                "get_article_by_index",
                {"exhibit_numbers": exhibit_numbers},
                f"별지 번호가 명시됨: {exhibit_numbers}"
            )
        
        # 불확실 → None 반환
        return None
