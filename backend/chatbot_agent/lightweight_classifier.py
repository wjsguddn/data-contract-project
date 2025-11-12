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
    
    # 조 번호 패턴
    # - "제n조", "제 n조", "제 n 조" (표준 형식)
    # - "n조", "n 조" (축약 형식)
    ARTICLE_NUMBER_PATTERN = re.compile(r'(?:제\s*)?(\d+)\s*조')
    
    # 별지 번호 패턴
    # - "별지n", "별지 n" (표준 형식)
    # - "n번 별지" (역순 형식)
    EXHIBIT_NUMBER_PATTERN = re.compile(r'(?:별지\s*(\d+)|(\d+)\s*번\s*별지)')
    
    def __init__(self):
        """초기화"""
        logger.info("LightweightClassifier 초기화 완료")
    
    def classify(self, user_message: str) -> Optional[Dict[str, Any]]:
        """
        사용자 메시지를 분석하여 툴 필요성을 빠르게 판단
        
        명확한 패턴(조 번호, 별지 번호)만 감지하고,
        나머지는 모두 LLM에 위임합니다.
        
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
        # 조 번호와 별지 번호 모두 체크
        article_matches = self.ARTICLE_NUMBER_PATTERN.findall(user_message)
        exhibit_matches = self.EXHIBIT_NUMBER_PATTERN.findall(user_message)
        
        # 둘 중 하나라도 있으면 툴 필요
        if article_matches or exhibit_matches:
            reasons = []
            if article_matches:
                reasons.append(f"조 번호: {', '.join([f'제{n}조' for n in article_matches])}")
            if exhibit_matches:
                # exhibit_matches는 튜플 리스트이므로 처리 필요
                exhibit_nums = [n1 or n2 for n1, n2 in exhibit_matches]
                reasons.append(f"별지 번호: {', '.join([f'별지{n}' for n in exhibit_nums])}")
            
            reason = ", ".join(reasons) + " 명시됨"
            logger.info(f"명시적 참조 감지: {reason}")
            
            return {
                "needs_tools": True,
                "confidence": 0.95,
                "reason": reason,
                "suggested_tool": "article_index_tool"
            }
        
        # 명시적 참조 없음 → LLM에 위임
        logger.info("명시적 참조 없음 - LLM에 위임")
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
        # 정규식이 2개의 캡처 그룹을 반환하므로 (별지n, n번 별지)
        # 각 매치는 튜플 형태: ('1', '') 또는 ('', '1')
        # 비어있지 않은 그룹을 선택
        return [int(n1 or n2) for n1, n2 in matches]
    
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
        # 조 번호와 별지 번호 모두 추출
        article_numbers = self.extract_article_numbers(user_message)
        exhibit_numbers = self.extract_exhibit_numbers(user_message)
        
        # 둘 중 하나라도 있으면 article_index_tool 제안
        if article_numbers or exhibit_numbers:
            args = {}
            reasons = []
            
            if article_numbers:
                args["article_numbers"] = article_numbers
                reasons.append(f"조 번호: {article_numbers}")
            
            if exhibit_numbers:
                args["exhibit_numbers"] = exhibit_numbers
                reasons.append(f"별지 번호: {exhibit_numbers}")
            
            reasoning = ", ".join(reasons) + " 명시됨"
            
            return (
                "get_article_by_index",
                args,
                reasoning
            )
        
        # 불확실 → None 반환
        return None
